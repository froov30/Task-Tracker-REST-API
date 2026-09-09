"""
Backward-compatibility redirects from the unversioned v1 paths to /api/v1/*.

These issue HTTP 308 (Permanent Redirect) which — unlike 301 — preserves the
HTTP method and body, so POST/PUT/DELETE clients keep working. A plain GET to
a legacy path also receives the redirect.

Only the collection/root paths are redirected here; clients should migrate to
the /api/v1 paths. This is a transitional shim, not a permanent alias.
"""

from fastapi import APIRouter
from fastapi import status as http_status
from fastapi.responses import RedirectResponse

router = APIRouter()

_PERMANENT = http_status.HTTP_301_MOVED_PERMANENTLY


@router.get("/tasks", include_in_schema=False)
async def legacy_tasks_redirect() -> RedirectResponse:
    return RedirectResponse(url="/api/v1/tasks", status_code=_PERMANENT)


@router.get("/users/me", include_in_schema=False)
async def legacy_users_me_redirect() -> RedirectResponse:
    return RedirectResponse(url="/api/v1/users/me", status_code=_PERMANENT)
