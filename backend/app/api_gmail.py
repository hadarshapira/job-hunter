"""Gmail connection and the job emails the app acted on. Everything is scoped to the signed-in user."""

import secrets
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import COOKIE, _serializer, current_user
from app.config import Settings, get_settings
from app.db import get_session
from app.models import GmailAccount, GmailMessage, Job, User
from app.services.gmail import oauth
from app.services.gmail.client import Gmail
from app.services.gmail import sync as gsync

router = APIRouter(prefix="/api/gmail", tags=["gmail"])


def http_client() -> httpx.AsyncClient:  # replaced in tests
    return httpx.AsyncClient()


class GmailStatus(BaseModel):
    configured: bool
    connected: bool
    email: str = ""
    connected_at: datetime | None = None
    last_sync_at: datetime | None = None
    last_error: str = ""
    label: str = gsync.LABEL_NAME


class GmailMessageOut(BaseModel):
    id: int
    sender: str
    subject: str
    received_at: datetime | None
    kind: str
    action: str
    job_id: int | None
    job_title: str = ""
    job_company: str = ""
    company_guess: str
    title_guess: str
    moved: bool
    link: str


class AssignRequest(BaseModel):
    job_id: int


def _state_signer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="jh-gmail-state")


def _redirect_uri(request: Request, settings: Settings) -> str:
    """Must be exactly one of the redirect URIs registered in Google Cloud."""
    if settings.public_url:
        return settings.public_url.rstrip("/") + "/api/gmail/callback"
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost").split(":")[0]
    if host in ("localhost", "127.0.0.1"):
        return "http://localhost:8088/api/gmail/callback"
    return f"https://{host}/api/gmail/callback"


def _configured(settings: Settings) -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


@router.get("/status", response_model=GmailStatus)
async def gmail_status(user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                       settings: Settings = Depends(get_settings)):
    acc = await session.get(GmailAccount, user.id)
    if not acc:
        return GmailStatus(configured=_configured(settings), connected=False)
    return GmailStatus(configured=_configured(settings), connected=True, email=acc.email, connected_at=acc.connected_at,
                       last_sync_at=acc.last_sync_at, last_error=acc.last_error)


@router.get("/connect")
async def connect(request: Request, user: User = Depends(current_user), settings: Settings = Depends(get_settings)):
    if not _configured(settings):
        raise HTTPException(400, "Gmail isn't set up on the server (GOOGLE_CLIENT_SECRET is missing)")
    state = _state_signer(settings).dumps({"uid": user.id, "n": secrets.token_urlsafe(8)})
    return RedirectResponse(oauth.auth_url(settings, _redirect_uri(request, settings), state, login_hint=user.email), 303)


def _back(result: str) -> RedirectResponse:
    return RedirectResponse(f"/settings?gmail={result}#gmail", 303)


@router.get("/callback")
async def callback(request: Request, state: str = "", code: str = "", error: str = "",
                   session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    try:
        uid = _state_signer(settings).loads(state, max_age=900)["uid"]
    except (BadSignature, SignatureExpired, KeyError, TypeError):
        return _back("expired")
    # If the browser is signed in, it must be the same user who started connecting
    if (cookie := request.cookies.get(COOKIE)):
        try:
            if _serializer(settings).loads(cookie).get("uid") != uid:
                return _back("wrong_user")
        except (BadSignature, AttributeError):
            pass
    if error or not code:
        return _back("cancelled")
    async with http_client() as client:
        try:
            tokens = await oauth.exchange_code(client, settings, code, _redirect_uri(request, settings))
        except oauth.GmailAuthError:
            return _back("failed")
        if oauth.SCOPE not in tokens.get("scope", "").split() or not tokens.get("refresh_token"):
            return _back("missing_permission")
        profile = await Gmail(client, tokens["access_token"]).profile()
    acc = await session.get(GmailAccount, uid) or GmailAccount(user_id=uid)
    acc.email = profile.get("emailAddress", "")
    acc.refresh_token = oauth.encrypt(settings, tokens["refresh_token"])
    acc.history_id = str(profile.get("historyId") or "") or None  # only mail from now on
    acc.connected_at = datetime.now(timezone.utc)
    acc.last_sync_at = None
    acc.last_error = ""
    session.add(acc)
    await session.commit()
    return _back("connected")


@router.post("/disconnect", status_code=204)
async def disconnect(user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                     settings: Settings = Depends(get_settings)):
    acc = await session.get(GmailAccount, user.id)
    if acc:
        try:
            token = oauth.decrypt(settings, acc.refresh_token)
            async with http_client() as client:
                await oauth.revoke(client, token)
        except oauth.GmailAuthError:
            pass
        await session.delete(acc)
        await session.commit()


async def _account(session: AsyncSession, user: User) -> GmailAccount:
    acc = await session.get(GmailAccount, user.id)
    if not acc:
        raise HTTPException(400, "Connect Gmail first")
    return acc


@router.post("/sync")
async def sync_now(user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
                   settings: Settings = Depends(get_settings)):
    acc = await _account(session, user)
    async with http_client() as client:
        summary = await gsync.sync_account(session, client, settings, acc)
    return {**summary, "error": acc.last_error}


async def _out(session: AsyncSession, acc: GmailAccount | None, msgs: list[GmailMessage]) -> list[GmailMessageOut]:
    ids = {m.job_id for m in msgs if m.job_id}
    jobs = {j.id: j for j in (await session.scalars(select(Job).where(Job.id.in_(ids)))).all()} if ids else {}
    out = []
    for m in msgs:
        j = jobs.get(m.job_id) if m.job_id else None
        out.append(GmailMessageOut(
            id=m.id, sender=m.sender, subject=m.subject, received_at=m.received_at, kind=m.kind, action=m.action,
            job_id=m.job_id, job_title=j.title if j else "", job_company=j.company if j else "",
            company_guess=m.company_guess, title_guess=m.title_guess, moved=m.moved,
            link=gsync.gmail_link(acc, m.gmail_id) if acc else ""))
    return out


@router.get("/messages", response_model=list[GmailMessageOut])
async def messages(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    msgs = (await session.scalars(select(GmailMessage).where(GmailMessage.user_id == user.id)
                                  .order_by(GmailMessage.created_at.desc()).limit(30))).all()
    return await _out(session, await session.get(GmailAccount, user.id), list(msgs))


async def _message(session: AsyncSession, user: User, msg_id: int) -> GmailMessage:
    msg = await session.scalar(select(GmailMessage).where(GmailMessage.id == msg_id, GmailMessage.user_id == user.id))
    if not msg:
        raise HTTPException(404, "Email not found")
    return msg


@router.post("/messages/{msg_id}/assign", response_model=GmailMessageOut)
async def assign(msg_id: int, body: AssignRequest, user: User = Depends(current_user),
                 session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    msg = await _message(session, user, msg_id)
    if msg.action != "unmatched":
        raise HTTPException(400, "This email is already linked to a job")
    job = await session.scalar(select(Job).where(Job.id == body.job_id, Job.user_id == user.id)
                               .options(selectinload(Job.events)))
    if not job:
        raise HTTPException(404, "Job not found")
    acc = await _account(session, user)
    async with http_client() as client:
        try:
            gmail = await gsync.open_gmail(client, settings, acc)
        except oauth.GmailAuthError as e:
            raise HTTPException(400, str(e))
        await gsync.act(session, gmail, acc, msg, job)
    await session.commit()
    return (await _out(session, acc, [msg]))[0]


@router.post("/messages/{msg_id}/undo", response_model=GmailMessageOut)
async def undo(msg_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session),
               settings: Settings = Depends(get_settings)):
    msg = await _message(session, user, msg_id)
    if msg.action in ("undone", "unmatched"):
        raise HTTPException(400, "Nothing to undo")
    acc = await session.get(GmailAccount, user.id)
    async with http_client() as client:
        gmail = None
        if acc and msg.moved:
            try:
                gmail = await gsync.open_gmail(client, settings, acc)
            except oauth.GmailAuthError as e:
                raise HTTPException(400, str(e))
        await gsync.undo(session, gmail, msg)
    await session.commit()
    return (await _out(session, acc, [msg]))[0]
