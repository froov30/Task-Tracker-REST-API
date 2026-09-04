"""
Alembic environment configuration.

* Uses a *synchronous* psycopg2 connection for the migration runner
  (Alembic does not support asyncpg natively).
* Imports Base.metadata so --autogenerate can diff against the ORM models.
* DATABASE_URL is read from the environment (or .env file via python-dotenv);
  the asyncpg scheme is swapped out for psycopg2 automatically.
"""

import os
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from alembic import context

# Load .env so DATABASE_URL is available when running alembic CLI locally
load_dotenv()

# ---------------------------------------------------------------------------
# Alembic Config object
# ---------------------------------------------------------------------------
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Import ORM models so autogenerate can see all tables
# ---------------------------------------------------------------------------
# noqa: E402 — imports must come after load_dotenv() / config setup
from app.models.orm import Base  # noqa: E402  # import triggers Base population

target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# Derive a *synchronous* URL for Alembic's runner
# ---------------------------------------------------------------------------

def _sync_url() -> str:
    """
    Convert the async DATABASE_URL to a sync psycopg2 URL for Alembic.

    postgresql+asyncpg://...  →  postgresql+psycopg2://...
    sqlite+aiosqlite://...    →  sqlite://...   (for test/CI)
    """
    url = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url", ""))
    # Replace async drivers with their sync counterparts
    url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    url = url.replace("sqlite+aiosqlite://", "sqlite://")
    return url


# ---------------------------------------------------------------------------
# Offline migrations (generate SQL without connecting)
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    url = _sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migrations (connect and run)
# ---------------------------------------------------------------------------

def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _sync_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
