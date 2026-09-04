from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.routers.tasks import router as tasks_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    Startup: nothing to do — schema is managed by Alembic migrations which
             must be run (alembic upgrade head) before starting the server.
    Shutdown: dispose the engine connection pool cleanly.
    """
    yield

    # Dispose the async engine on shutdown to close all pooled connections
    from app.database import engine
    await engine.dispose()


app = FastAPI(title=settings.APP_TITLE, lifespan=lifespan)

app.include_router(tasks_router, prefix="/tasks")
