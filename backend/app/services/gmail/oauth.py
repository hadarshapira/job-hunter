"""Google OAuth for Gmail: sign-in link, code exchange, token refresh and revoke, token encryption."""

import base64
import hashlib
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings

SCOPE = "https://www.googleapis.com/auth/gmail.modify"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"


class GmailAuthError(Exception):
    """Google refused the stored access (revoked, expired or app changed): the user must connect again."""


def _fernet(settings: Settings) -> Fernet:
    key = hashlib.sha256(f"{settings.secret_key}|gmail-token".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(settings: Settings, token: str) -> str:
    return _fernet(settings).encrypt(token.encode()).decode()


def decrypt(settings: Settings, value: str) -> str:
    try:
        return _fernet(settings).decrypt(value.encode()).decode()
    except InvalidToken as e:
        raise GmailAuthError("Stored Gmail access can't be read (the app's secret key changed)") from e


def auth_url(settings: Settings, redirect_uri: str, state: str, login_hint: str = "") -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",  # always return a refresh token
        "state": state,
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code(client: httpx.AsyncClient, settings: Settings, code: str, redirect_uri: str) -> dict:
    r = await client.post(TOKEN_URL, data={
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=30)
    if r.status_code != 200:
        raise GmailAuthError(f"Google didn't accept the sign-in ({r.status_code})")
    return r.json()


async def access_token(client: httpx.AsyncClient, settings: Settings, refresh_token: str) -> str:
    r = await client.post(TOKEN_URL, data={
        "refresh_token": refresh_token,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "grant_type": "refresh_token",
    }, timeout=30)
    if r.status_code in (400, 401):
        raise GmailAuthError("Gmail access was removed or expired. Connect Gmail again.")
    r.raise_for_status()
    return r.json()["access_token"]


async def revoke(client: httpx.AsyncClient, refresh_token: str) -> None:
    try:
        await client.post(REVOKE_URL, data={"token": refresh_token}, timeout=15)
    except httpx.HTTPError:
        pass  # best effort; the stored token is deleted anyway
