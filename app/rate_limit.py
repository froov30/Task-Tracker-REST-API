"""
Rate limiting via slowapi.

Strategy:
  - Authenticated requests are keyed and limited per user id.
  - Unauthenticated requests are keyed and limited per client IP.

Both the key function and the limit string are derived from the request's
authentication state, so a single `@limiter.limit(dynamic_limit)` decorator
applies the correct ceiling and bucket.

Rate limiting can be disabled via settings.RATE_LIMIT_ENABLED=False.
"""

from contextvars import ContextVar

from fastapi import Request
from fastapi import status as http_status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings
from app.schemas.errors import ErrorCode
from app.security import decode_access_token

# Populated by the key function (slowapi always calls key_func first with the
# request) so the no-arg dynamic_limit() can see the current request.
_current_request: ContextVar[Request | None] = ContextVar(
    "_current_request", default=None
)


def _extract_user_id(request: Request) -> int | None:
    """Return the user id from a valid Bearer token, or None."""
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    return decode_access_token(token)


def rate_limit_key(request: Request) -> str:
    """Key requests by user id when authenticated, else by client IP."""
    user_id = _extract_user_id(request)
    if user_id is not None:
        return f"user:{user_id}"
    return f"ip:{get_remote_address(request)}"


def dynamic_limit() -> str:
    """
    Per-request ceiling provider for slowapi's default_limits.

    slowapi invokes this with NO arguments while it holds the current request
    in its context, then applies the returned limit string against the bucket
    produced by rate_limit_key. We read the active request from the limiter's
    request context to decide auth vs unauth ceiling.
    """
    request = _current_request.get()
    if request is not None and _extract_user_id(request) is not None:
        return settings.RATE_LIMIT_AUTHENTICATED
    return settings.RATE_LIMIT_UNAUTHENTICATED


def rate_limit_key_with_context(request: Request) -> str:
    """key_func that also stashes the request for dynamic_limit()."""
    _current_request.set(request)
    return rate_limit_key(request)


limiter = Limiter(
    key_func=rate_limit_key_with_context,
    enabled=settings.RATE_LIMIT_ENABLED,
    default_limits=[dynamic_limit],
)


def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Return the 429 in the standard ErrorResponse envelope."""
    return JSONResponse(
        status_code=http_status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": {
                "code": ErrorCode.RATE_LIMIT_EXCEEDED,
                "message": "Rate limit exceeded. Please slow down.",
                "resource": None,
                "resource_id": None,
            }
        },
    )
