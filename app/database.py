"""
Async SQLAlchemy engine, session factory, and FastAPI dependency.

The engine is configured from the DATABASE_URL environment variable.
- Production / Docker: postgresql+asyncpg://user:pass@host/db
- Tests / CI:          sqlite+aiosqlite:///./test.db  (in-memory or file)

Table creation is handled by Alembic migrations (alembic upgrade head).
init_db() is kept as a no-op shim so existing call-sites don't break;
it is intentionally a no-op in production — use Alembic instead.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# ---------------------------------------------------------------------------
# Engine & session factory
# ---------------------------------------------------------------------------

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


# ---------------------------------------------------------------------------
# Declarative base — imported by ORM models
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session; roll back on error, close when done."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# init_db — kept as a shim; real schema management lives in Alembic
# ---------------------------------------------------------------------------

async def init_db() -> None:  # noqa: RUF029
    """No-op shim. Schema is managed by Alembic migrations."""
