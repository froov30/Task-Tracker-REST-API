"""
Shared fixtures for the Task Tracker test suite.

Each test gets a fresh, isolated SQLite database (tempfile) so tests
never interfere with each other or with the production database.
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path):
    """Point the app at a per-test temp database, create the schema, and
    clean up afterwards."""
    db_file = tmp_path / "test_tasks.db"

    # Patch the module-level DATABASE_PATH *before* init_db runs
    import app.database as db_mod

    db_mod.DATABASE_PATH = str(db_file)
    db_mod.init_db()

    yield

    # Cleanup is automatic — tmp_path is removed by pytest


@pytest.fixture()
def client():
    """Return a fresh TestClient bound to the app."""
    from app.main import app

    return TestClient(app)
