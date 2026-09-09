from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.error_handlers import register_exception_handlers
from app.logging_config import configure_logging
from app.middleware import RequestContextMiddleware
from app.rate_limit import limiter, rate_limit_exceeded_handler
from app.routers.auth import router as auth_router
from app.routers.health import router as health_router
from app.routers.legacy_redirects import router as legacy_router
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


API_V1_PREFIX = "/api/v1"

configure_logging()

app = FastAPI(
    title=settings.APP_TITLE,
    lifespan=lifespan,
    # Advertise the versioned base path to Swagger clients
    servers=[{"url": "/", "description": "Default"}],
)

register_exception_handlers(app)

# Request-context logging (request_id, latency, user_id) + X-Request-ID header.
app.add_middleware(RequestContextMiddleware)

# Rate limiting: attach the limiter, its 429 handler, and the middleware.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Infrastructure endpoints — unversioned (used by health probes)
app.include_router(health_router, tags=["health"])

# Versioned API surface
app.include_router(auth_router, prefix=f"{API_V1_PREFIX}/auth", tags=["auth"])
app.include_router(users_router, prefix=f"{API_V1_PREFIX}/users", tags=["users"])
app.include_router(tasks_router, prefix=f"{API_V1_PREFIX}/tasks", tags=["tasks"])

# Legacy → /api/v1 redirects (transitional backward-compat)
app.include_router(legacy_router, include_in_schema=False)
