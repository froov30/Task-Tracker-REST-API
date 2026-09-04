"""
Shared fixtures for the Task Tracker test suite.

Test isolation strategy
-----------------------
Each test gets a fresh, isolated in-memory SQLite database via aiosqlite.
This is fast (no Postgres required in CI) and fully isolated between tests.

We override the `get_db` FastAPI dependency so every request made through
TestClient uses the same test session, which is rolled back after each test.

Design notes
------------
- DATABASE_URL is set to an in-memory SQLite URL before any app module is
  imported, by patching os.environ at the top of this module.
- `pytest-asyncio` with `asyncio_mode = "auto"` (set in pyproject.toml)
  is required for async fixtures.
- `anyio_backend` is pinned to "asyncio" to avoid trio dependency.
"""

import os

# ---------------------------------------------------------------------------
# Set the test DATABASE_URL *before* any app module is imported.
# Each test gets a unique file-based SQLite DB via a tmp_path fixture below,
# but we provide a default here so the Settings object can initialise.
# ---------------------------------------------------------------------------
os.environ.setdefault(
    "DATABASE_URL", "sqlite+aiosqlite:///./test_default.db"
)

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base, get_db


# ---------------------------------------------------------------------------
# Per-test async engine + session (file-based SQLite for isolation)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def db_session(tmp_path):
    """
    Yield an AsyncSession backed by a fresh, isolated SQLite DB.

    Creates all tables via Base.metadata.create_all, yields the session,
    then drops everything on teardown. Using a file-based path (tmp_path)
    ensures no cross-test leakage even when tests run in parallel.
    """
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
# HTTP test client — overrides get_db with the isolated test session
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(db_session):
    """
    Return a synchronous TestClient whose requests use the isolated db_session.

    We use httpx.AsyncClient under the hood via ASGITransport, wrapped in a
    sync interface via pytest-asyncio event loop bridging — but FastAPI's
    TestClient (sync) also works because we override the dependency.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
