"""
Shared fixtures for the Task Tracker test suite.

Test isolation strategy
-----------------------
Each test gets a fresh, isolated SQLite database via aiosqlite (file-based in
a per-test tmp_path). This is fast (no Postgres required in CI) and fully
isolated between tests.

We override the `get_db` FastAPI dependency so every request made through
TestClient uses the same test session.

API versioning
--------------
Phase 7 moved the API under /api/v1. To keep existing test bodies unchanged,
the test clients transparently prepend /api/v1 to feature paths (/tasks,
/auth, /users). Infrastructure paths (/health, /ready) and already-versioned
paths are passed through untouched.

Rate limiting
-------------
Disabled for the whole suite via RATE_LIMIT_ENABLED=false (set before the app
is imported). Rate-limit behavior is tested explicitly in test_rate_limiting.py
with its own app instance.

Fixtures provided:
  - db_session         : the isolated AsyncSession
  - anon_client        : versioned TestClient with NO auth header
  - client             : versioned TestClient pre-authenticated as user A
  - second_user_token  : a Bearer token for a distinct user B
"""

import os

# ---------------------------------------------------------------------------
# Configure the environment *before* any app module is imported.
# ---------------------------------------------------------------------------
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_default.db")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base, get_db

API_V1_PREFIX = "/api/v1"
# Feature path roots that live under the version prefix.
_VERSIONED_ROOTS = ("/tasks", "/auth", "/users")


def _version_path(url: str) -> str:
    """Prepend /api/v1 to feature paths; leave infra/versioned paths alone."""
    if url.startswith(API_V1_PREFIX):
        return url
    for root in _VERSIONED_ROOTS:
        if url == root or url.startswith((root + "/", root + "?")):
            return API_V1_PREFIX + url
    return url


# ---------------------------------------------------------------------------
# Per-test async engine + session (file-based SQLite for isolation)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def db_session(tmp_path):
    """Yield an AsyncSession backed by a fresh, isolated SQLite DB."""
    db_url = f"sqlite+aiosqlite:///{tmp_path}/test_tasks.db"
    engine = create_async_engine(db_url, echo=False)

    # Import ORM models so their tables are registered on Base.metadata
    import app.models.orm  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


# ---------------------------------------------------------------------------
# Version-aware TestClient
# ---------------------------------------------------------------------------

def _make_versioned_client(db_session):
    """Build a TestClient that auto-prefixes feature paths with /api/v1."""
    from fastapi.testclient import TestClient

    from app.main import app

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    class _VersionedClient(TestClient):
        def request(self, method, url, *args, **kwargs):
            return super().request(method, _version_path(url), *args, **kwargs)

    return app, _VersionedClient(app)


@pytest.fixture()
def anon_client(db_session):
    """A version-aware TestClient with the DB override but NO auth header."""
    app, c = _make_versioned_client(db_session)
    with c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _register_and_login(client, email: str, password: str = "password123") -> str:
    """Register a user (ignore duplicate) and return their Bearer token."""
    client.post("/auth/register", json={"email": email, "password": password})
    resp = client.post(
        "/auth/login",
        data={"username": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture()
def client(anon_client):
    """A version-aware TestClient pre-authenticated as user A."""
    token = _register_and_login(anon_client, "userA@example.com")
    anon_client.headers.update({"Authorization": f"Bearer {token}"})
    return anon_client


@pytest.fixture()
def second_user_token(anon_client):
    """A Bearer token for a distinct user B (userB@example.com)."""
    return _register_and_login(anon_client, "userB@example.com")
