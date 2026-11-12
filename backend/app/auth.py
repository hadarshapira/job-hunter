"""Multi-user auth: email + password sign-up, Google Sign-In, signed session cookie."""

import asyncio
import time
from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.models import User
from app.schemas import GoogleLogin, LoginRequest, SignupRequest, UserOut

COOKIE = "jh_session"
router = APIRouter(prefix="/api/auth", tags=["auth"])
hasher = PasswordHasher()
# Used so a login for an unknown email takes as long as a real one
_DUMMY_HASH = hasher.hash("not-a-real-password")

# Simple in-memory brute-force protection per client IP
_failures: dict[str, list[float]] = {}
MAX_FAILURES, WINDOW = 10, 300


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="jh-session")


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _check_rate(request: Request) -> None:
    now = time.time()
    recent = [t for t in _failures.get(_ip(request), []) if now - t < WINDOW]
    _failures[_ip(request)] = recent
    if len(recent) >= MAX_FAILURES:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, wait 5 minutes")


def _fail(request: Request, detail: str, code: int = status.HTTP_401_UNAUTHORIZED) -> HTTPException:
    _failures.setdefault(_ip(request), []).append(time.time())
    return HTTPException(code, detail)


async def current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")
    try:
        data = _serializer(settings).loads(token, max_age=settings.session_days * 86400)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    user = await session.get(User, data.get("uid")) if isinstance(data, dict) else None
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found")
    return user


async def _start_session(user: User, response: Response, session: AsyncSession, settings: Settings) -> UserOut:
    user.last_login_at = datetime.now(timezone.utc)
    await session.commit()
    response.set_cookie(
        COOKIE,
        _serializer(settings).dumps({"uid": user.id}),
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return UserOut.from_user(user)


@router.get("/config")
def auth_config(settings: Settings = Depends(get_settings)):
    """Public: tells the sign-in screen which options to show."""
    return {"google_client_id": settings.google_client_id or None, "signup_enabled": settings.signup_enabled}


@router.post("/signup", response_model=UserOut, status_code=201)
async def signup(
    body: SignupRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    if not settings.signup_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign-up is closed")
    _check_rate(request)
    email = body.email.lower()
    if await session.scalar(select(User).where(User.email == email)):
        raise _fail(request, "An account with this email already exists. Sign in instead.", status.HTTP_409_CONFLICT)
    user = User(email=email, name=body.name.strip(), password_hash=await asyncio.to_thread(hasher.hash, body.password))
    session.add(user)
    await session.flush()
    return await _start_session(user, response, session, settings)


@router.post("/login", response_model=UserOut)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    _check_rate(request)
    user = await session.scalar(select(User).where(User.email == body.email.lower()))
    stored = user.password_hash if user and user.password_hash else _DUMMY_HASH
    try:
        await asyncio.to_thread(hasher.verify, stored, body.password)
        ok = user is not None and user.password_hash is not None
    except (VerifyMismatchError, InvalidHashError):
        ok = False
    if not ok:
        if user and not user.password_hash:
            raise _fail(request, "This account uses Google sign-in. Use the Google button.")
        raise _fail(request, "Wrong email or password")
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = await asyncio.to_thread(hasher.hash, body.password)
    _failures.pop(_ip(request), None)
    return await _start_session(user, response, session, settings)


def verify_google_token(credential: str, client_id: str) -> dict:
    """Verify a Google Identity Services ID token (signature, audience, expiry). Replaced in tests."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(credential, google_requests.Request(), client_id)


@router.post("/google", response_model=UserOut)
async def google_login(
    body: GoogleLogin,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    if not settings.google_client_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Google sign-in is not configured")
    _check_rate(request)
    try:
        info = await asyncio.to_thread(verify_google_token, body.credential, settings.google_client_id)
    except ValueError:
        raise _fail(request, "Google sign-in failed, please try again")
    if not info.get("email") or not info.get("email_verified"):
        raise _fail(request, "Your Google account has no verified email")

    sub, email = info["sub"], info["email"].lower()
    user = await session.scalar(select(User).where(User.google_sub == sub))
    if not user:
        user = await session.scalar(select(User).where(User.email == email))
        if user:
            # Link Google to an existing email account. Google has proven the email belongs to this
            # person; if the password account was never verified, drop its password so nobody who
            # registered the address beforehand keeps access.
            if not user.email_verified:
                user.password_hash = None
        else:
            if not settings.signup_enabled:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign-up is closed")
            user = User(email=email)
            session.add(user)
        user.google_sub = sub
    user.email_verified = True
    user.name = user.name or info.get("name", "")
    user.picture = info.get("picture") or user.picture
    await session.flush()
    _failures.pop(_ip(request), None)
    return await _start_session(user, response, session, settings)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return UserOut.from_user(user)
