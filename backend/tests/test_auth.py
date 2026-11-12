import pytest
from sqlalchemy import select

from app import auth as auth_module
from app.models import User
from tests.conftest import new_client, signup


async def test_signup_login_logout(client):
    me = await signup(client, "Dana@Example.com", name="Dana")
    assert me["email"] == "dana@example.com" and me["has_password"] and not me["google_linked"]
    assert (await client.get("/api/auth/me")).json()["name"] == "Dana"

    await client.post("/api/auth/logout")
    client.cookies.clear()
    assert (await client.get("/api/auth/me")).status_code == 401

    bad = await client.post("/api/auth/login", json={"email": "dana@example.com", "password": "wrong-pass"})
    assert bad.status_code == 401 and bad.json()["detail"] == "Wrong email or password"
    unknown = await client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever1"})
    assert unknown.json()["detail"] == "Wrong email or password"  # same message: no account probing

    ok = await client.post("/api/auth/login", json={"email": "DANA@example.com", "password": "correct-horse-1"})
    assert ok.status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 200


async def test_signup_validation(client):
    r = await client.post("/api/auth/signup", json={"email": "x@example.com", "password": "short"})
    assert r.status_code == 422
    r = await client.post("/api/auth/signup", json={"email": "not-an-email", "password": "long-enough-1"})
    assert r.status_code == 422
    await signup(client, "dup@example.com")
    r = await client.post("/api/auth/signup", json={"email": "DUP@example.com", "password": "long-enough-1"})
    assert r.status_code == 409


async def test_users_cannot_see_each_others_jobs(maker):
    async with new_client() as a, new_client() as b:
        await signup(a, "a@example.com")
        await signup(b, "b@example.com")
        job = (await a.post("/api/jobs", json={"title": "Senior Data Engineer", "company": "Acme"})).json()

        assert len((await a.get("/api/jobs")).json()) == 1
        assert (await b.get("/api/jobs")).json() == []
        assert (await b.get(f"/api/jobs/{job['id']}")).status_code == 404
        assert (await b.patch(f"/api/jobs/{job['id']}", json={"status": "offer"})).status_code == 404
        assert (await b.delete(f"/api/jobs/{job['id']}")).status_code == 404
        assert (await b.get("/api/stats")).json()["by_status"] == {}

        # Same job saved by B is not a "duplicate" of A's
        job_b = (await b.post("/api/jobs", json={"title": "Senior Data Engineer", "company": "Acme"})).json()
        assert job_b["id"] != job["id"]


def fake_google(info: dict):
    def verify(credential: str, client_id: str) -> dict:
        assert client_id == "test-client.apps.googleusercontent.com"
        if credential == "bad-token-xyz":
            raise ValueError("invalid")
        return info

    return verify


GOOGLE_INFO = {"sub": "1234567890", "email": "Noa@Gmail.com", "email_verified": True, "name": "Noa", "picture": "https://x/p.png"}


async def test_google_creates_account_then_signs_in(client, monkeypatch):
    monkeypatch.setattr(auth_module, "verify_google_token", fake_google(GOOGLE_INFO))
    r = await client.post("/api/auth/google", json={"credential": "good-token-abc"})
    assert r.status_code == 200
    me = r.json()
    assert me["email"] == "noa@gmail.com" and me["google_linked"] and not me["has_password"]
    assert me["picture"] == "https://x/p.png"

    # Second sign-in reuses the same account
    again = await client.post("/api/auth/google", json={"credential": "good-token-abc"})
    assert again.json()["id"] == me["id"]

    # Password login is refused with a helpful message for a Google-only account
    r = await client.post("/api/auth/login", json={"email": "noa@gmail.com", "password": "anything-1"})
    assert r.status_code == 401 and "Google" in r.json()["detail"]


async def test_google_links_existing_email_account_and_drops_unverified_password(client, maker, monkeypatch):
    me = await signup(client, "noa@gmail.com")
    monkeypatch.setattr(auth_module, "verify_google_token", fake_google(GOOGLE_INFO))
    linked = (await client.post("/api/auth/google", json={"credential": "good-token-abc"})).json()
    assert linked["id"] == me["id"] and linked["google_linked"]
    assert not linked["has_password"]  # someone could have pre-registered this address
    async with maker() as s:
        user = await s.scalar(select(User).where(User.email == "noa@gmail.com"))
        assert user.email_verified


@pytest.mark.parametrize("info", [{**GOOGLE_INFO, "email_verified": False}, {"sub": "1", "email_verified": True}])
async def test_google_requires_verified_email(client, monkeypatch, info):
    monkeypatch.setattr(auth_module, "verify_google_token", fake_google(info))
    assert (await client.post("/api/auth/google", json={"credential": "good-token-abc"})).status_code == 401


async def test_google_bad_token(client, monkeypatch):
    monkeypatch.setattr(auth_module, "verify_google_token", fake_google(GOOGLE_INFO))
    assert (await client.post("/api/auth/google", json={"credential": "bad-token-xyz"})).status_code == 401


async def test_auth_config_and_rate_limit(client):
    cfg = (await client.get("/api/auth/config")).json()
    assert cfg == {"google_client_id": "test-client.apps.googleusercontent.com", "signup_enabled": True}
    for _ in range(10):
        await client.post("/api/auth/login", json={"email": "x@example.com", "password": "wrong-pass"})
    r = await client.post("/api/auth/login", json={"email": "x@example.com", "password": "wrong-pass"})
    assert r.status_code == 429
