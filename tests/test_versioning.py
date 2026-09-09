"""
API versioning tests (Phase 7, Task 17).

Uses a *raw* (non-shimmed) TestClient so we can assert the real /api/v1 paths
and the legacy → /api/v1 redirects.
"""

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


@pytest.fixture()
def raw_client(db_session):
    """A plain TestClient with the DB override but NO path shimming."""
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestVersionedPaths:
    def test_v1_auth_register_works(self, raw_client):
        resp = raw_client.post(
            "/api/v1/auth/register",
            json={"email": "v1@example.com", "password": "password123"},
        )
        assert resp.status_code == 201

    def test_v1_tasks_requires_auth(self, raw_client):
        resp = raw_client.get("/api/v1/tasks")
        assert resp.status_code == 401

    def test_unversioned_tasks_not_directly_served(self, raw_client):
        # /tasks is not a real API route anymore; only a redirect exists (GET).
        # A POST to /tasks should NOT create a task (405 or 404, never 201).
        resp = raw_client.post(
            "/tasks", json={"title": "x"}, follow_redirects=False
        )
        assert resp.status_code != 201


class TestHealthUnversioned:
    def test_health_stays_unversioned(self, raw_client):
        assert raw_client.get("/health").status_code == 200

    def test_ready_stays_unversioned(self, raw_client):
        assert raw_client.get("/ready").status_code == 200

    def test_health_not_under_v1(self, raw_client):
        # /api/v1/health should not exist
        assert raw_client.get("/api/v1/health").status_code == 404


class TestLegacyRedirect:
    def test_legacy_tasks_get_redirects_301(self, raw_client):
        resp = raw_client.get("/tasks", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers["location"] == "/api/v1/tasks"

    def test_legacy_users_me_redirects_301(self, raw_client):
        resp = raw_client.get("/users/me", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers["location"] == "/api/v1/users/me"
