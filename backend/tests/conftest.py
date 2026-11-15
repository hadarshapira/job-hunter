import os

os.environ["SECRET_KEY"] = "test-secret"
os.environ["GOOGLE_CLIENT_ID"] = "test-client.apps.googleusercontent.com"
os.environ["SIGNUP_ENABLED"] = "true"

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import _failures
from app.config import get_settings
from app.db import Base, get_session
from app.main import app

get_settings.cache_clear()


@pytest.fixture(autouse=True)
def no_linkedin_delay(monkeypatch):
    from app.collectors import linkedin

    monkeypatch.setattr(linkedin, "DELAY", (0, 0))


@pytest.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    m = async_sessionmaker(engine, expire_on_commit=False)

    async def _session():
        async with m() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    _failures.clear()
    yield m
    app.dependency_overrides.clear()
    await engine.dispose()


def new_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def client(maker):
    async with new_client() as c:
        yield c


async def signup(c: AsyncClient, email: str, password: str = "correct-horse-1", name: str = "") -> dict:
    r = await c.post("/api/auth/signup", json={"email": email, "password": password, "name": name})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
async def authed(client):
    await signup(client, "dana@example.com", name="Dana")
    return client
