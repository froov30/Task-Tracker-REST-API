from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.error_handlers import register_exception_handlers
from app.routers.auth import router as auth_router
from app.routers.health import router as health_router
from app.routers.tasks import router as tasks_router
from app.routers.users import router as users_router


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

register_exception_handlers(app)

app.include_router(health_router, tags=["health"])
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(users_router, prefix="/users", tags=["users"])
app.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
