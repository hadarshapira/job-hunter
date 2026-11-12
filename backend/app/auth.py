"""Single-user auth: one password from .env, signed session cookie."""

import hmac
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import Settings, get_settings
from app.schemas import LoginRequest

COOKIE = "jh_session"
router = APIRouter(prefix="/api/auth", tags=["auth"])

# Simple in-memory brute-force protection
_failures: dict[str, list[float]] = {}
MAX_FAILURES, WINDOW = 5, 300


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="jh-session")


def require_user(request: Request, settings: Settings = Depends(get_settings)) -> None:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")
    try:
        _serializer(settings).loads(token, max_age=settings.session_days * 86400)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response, settings: Settings = Depends(get_settings)):
    ip = request.client.host if request.client else "?"
    now = time.time()
    recent = [t for t in _failures.get(ip, []) if now - t < WINDOW]
    if len(recent) >= MAX_FAILURES:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, wait 5 minutes")
    if not hmac.compare_digest(body.password.encode(), settings.app_password.encode()):
        _failures[ip] = recent + [now]
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong password")
    _failures.pop(ip, None)
    response.set_cookie(
        COOKIE,
        _serializer(settings).dumps({"u": "me"}),
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/me", dependencies=[Depends(require_user)])
def me():
    return {"user": "me"}
