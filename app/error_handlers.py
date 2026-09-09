"""
Global exception handlers that render every error in the ErrorResponse shape:

    {"error": {"code": ..., "message": ..., "resource": ..., "resource_id": ...}}

Registered on the FastAPI app in main.py via register_exception_handlers().

Handles:
  - HTTPException whose detail is a structured dict (from our services)
  - HTTPException whose detail is a plain string (FastAPI internals, OAuth2)
  - RequestValidationError (422 body validation) → VALIDATION_ERROR
"""

from fastapi import FastAPI, Request
from fastapi import status as http_status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.errors import ErrorCode

# Map bare HTTP status codes to default error codes when the detail is a
# plain string (i.e. not raised by our service layer).
_STATUS_TO_CODE = {
    http_status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHORIZED,
    http_status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
    http_status.HTTP_404_NOT_FOUND: ErrorCode.TASK_NOT_FOUND,
    http_status.HTTP_409_CONFLICT: ErrorCode.VERSION_CONFLICT,
    http_status.HTTP_422_UNPROCESSABLE_ENTITY: ErrorCode.VALIDATION_ERROR,
}


def _error_body(
    code: str,
    message: str,
    resource: str | None = None,
    resource_id: int | None = None,
) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "resource": resource,
            "resource_id": resource_id,
        }
    }


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    detail = exc.detail

    if isinstance(detail, dict) and "code" in detail:
        # Structured detail produced by our service layer via error_detail()
        body = {
            "error": {
                "code": detail.get("code", ErrorCode.HTTP_ERROR),
                "message": detail.get("message", ""),
                "resource": detail.get("resource"),
                "resource_id": detail.get("resource_id"),
            }
        }
    else:
        # Plain-string detail (FastAPI internals, OAuth2, 405, etc.)
        code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.HTTP_ERROR)
        body = _error_body(code, str(detail))

    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Summarise the first error for the message; full list omitted to keep the
    # envelope clean (clients can rely on the code for programmatic handling).
    errors = exc.errors()
    message = "Request validation failed"
    if errors:
        first = errors[0]
        loc = ".".join(str(p) for p in first.get("loc", []))
        message = f"{first.get('msg', 'invalid')} (at {loc})" if loc else first.get("msg", message)

    return JSONResponse(
        status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_error_body(ErrorCode.VALIDATION_ERROR, message),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Wire the handlers onto the FastAPI application."""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
