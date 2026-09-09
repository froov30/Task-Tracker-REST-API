"""
Rate limiting tests (Phase 7, Task 18).

The app-wide limiter is created at import time from settings, and the rest of
the suite runs with RATE_LIMIT_ENABLED=false. To test limiting in isolation we
build a dedicated FastAPI app here with a fresh Limiter set to a very low limit,
mount a trivial route, and fire N+1 requests.
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.rate_limit import rate_limit_exceeded_handler


@pytest.fixture()
def limited_app():
    """A minimal app with a 3/minute per-IP limit and the structured handler."""
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["3/minute"],
        enabled=True,
    )
    application = FastAPI()
    application.state.limiter = limiter
    application.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    application.add_middleware(SlowAPIMiddleware)

    @application.get("/ping")
    async def ping(request: Request):
        return {"pong": True}

    return application


class TestRateLimiting:
    def test_within_limit_ok(self, limited_app):
        client = TestClient(limited_app)
        for _ in range(3):
            assert client.get("/ping").status_code == 200

    def test_over_limit_returns_429(self, limited_app):
        client = TestClient(limited_app)
        for _ in range(3):
            client.get("/ping")
        resp = client.get("/ping")  # the 4th request
        assert resp.status_code == 429

    def test_429_has_structured_body(self, limited_app):
        client = TestClient(limited_app)
        for _ in range(3):
            client.get("/ping")
        resp = client.get("/ping")
        assert resp.status_code == 429
        body = resp.json()
        assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert "message" in body["error"]


class TestKeyFunction:
    def test_user_bucket_vs_ip_bucket(self):
        """rate_limit_key uses user id when a valid Bearer token is present."""
        from types import SimpleNamespace

        from app.rate_limit import rate_limit_key
        from app.security import create_access_token

        token = create_access_token(subject=42)
        req_auth = SimpleNamespace(
            headers={"Authorization": f"Bearer {token}"},
            client=SimpleNamespace(host="1.2.3.4"),
        )
        assert rate_limit_key(req_auth) == "user:42"

        req_anon = SimpleNamespace(
            headers={},
            client=SimpleNamespace(host="1.2.3.4"),
        )
        assert rate_limit_key(req_anon).startswith("ip:")
