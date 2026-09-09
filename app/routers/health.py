"""
Health / readiness router — infrastructure endpoints (no auth, no version prefix).

  GET /health → 200 {"status": "ok", "database": "connected"} when the DB
                responds to SELECT 1; 503 otherwise.
  GET /ready  → same shape; used by Azure App Service health probes.
"""

from fastapi import APIRouter, Depends
from fastapi import status as http_status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

router = APIRouter()


async def _check_db(db: AsyncSession) -> bool:
    """Return True if a trivial SELECT 1 succeeds."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 — any DB error means "unhealthy"
        return False
    return True


async def _health_payload(db: AsyncSession) -> JSONResponse:
    ok = await _check_db(db)
    if ok:
        return JSONResponse(
            status_code=http_status.HTTP_200_OK,
            content={"status": "ok", "database": "connected"},
        )
    return JSONResponse(
        status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "error", "database": "unavailable"},
    )


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    return await _health_payload(db)


@router.get("/ready")
async def ready(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    return await _health_payload(db)
