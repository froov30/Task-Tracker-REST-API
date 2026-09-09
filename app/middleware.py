"""
Request context middleware.

For every request:
  - assign/propagate a request_id (UUID; honors inbound X-Request-ID)
  - bind request_id + user_id into structlog contextvars so all log lines
    emitted during the request carry them
  - measure latency and emit a `request.completed` log event
  - set the X-Request-ID response header so clients can correlate
"""

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.logging_config import get_logger
from app.security import decode_access_token

_logger = get_logger("request")


def _user_id_from_request(request: Request) -> int | None:
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    return decode_access_token(auth[7:].strip())


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        user_id = _user_id_from_request(request)

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            user_id=user_id,
        )
        # Expose on request.state for downstream handlers.
        request.state.request_id = request_id

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            _logger.error(
                "request.failed",
                method=request.method,
                path=request.url.path,
                latency_ms=latency_ms,
            )
            structlog.contextvars.clear_contextvars()
            raise

        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        _logger.info(
            "request.completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
        response.headers["X-Request-ID"] = request_id
        structlog.contextvars.clear_contextvars()
        return response
