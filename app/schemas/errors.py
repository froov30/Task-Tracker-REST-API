"""
Structured error response schemas and error code constants.

Every error the API returns is wrapped in an ErrorResponse envelope:

    {
      "error": {
        "code": "TASK_NOT_FOUND",
        "message": "Task with id 5 not found",
        "resource": "task",
        "resource_id": 5
      }
    }

Handlers in main.py convert HTTPException and RequestValidationError into
this shape. Services raise HTTPException with a `detail` dict built by
`error_detail(...)` so the code/resource travel with the exception.
"""

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

class ErrorCode:
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    EMAIL_ALREADY_REGISTERED = "EMAIL_ALREADY_REGISTERED"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    HTTP_ERROR = "HTTP_ERROR"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ErrorDetail(BaseModel):
    code: str
    message: str
    resource: str | None = None
    resource_id: int | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ---------------------------------------------------------------------------
# Helper for building the `detail` payload attached to HTTPException
# ---------------------------------------------------------------------------

def error_detail(
    code: str,
    message: str,
    *,
    resource: str | None = None,
    resource_id: int | None = None,
) -> dict:
    """Build the structured detail dict carried by an HTTPException."""
    return {
        "code": code,
        "message": message,
        "resource": resource,
        "resource_id": resource_id,
    }
