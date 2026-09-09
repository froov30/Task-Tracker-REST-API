"""
FastAPI dependency factories.

Centralises dependency wiring so routers stay free of construction logic.
Each factory is a single function that FastAPI resolves via Depends().
"""

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.orm import User
from app.repositories.history_repository import HistoryRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.task_service import TaskService

# tokenUrl is the login endpoint; used by Swagger's "Authorize" button
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def get_task_service(db: AsyncSession = Depends(get_db)) -> TaskService:  # noqa: B008
    """Wire db → TaskRepository (+ HistoryRepository) → TaskService."""
    return TaskService(TaskRepository(db), HistoryRepository(db))


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:  # noqa: B008
    """Wire db → UserRepository → AuthService for injection into routers."""
    return AuthService(UserRepository(db))


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    auth_svc: AuthService = Depends(get_auth_service),  # noqa: B008
) -> User:
    """
    Resolve the authenticated User from the Bearer token.

    Raises 401 if the token is missing/invalid/expired, 403 if the user is
    inactive. Inject into any endpoint that requires authentication.
    """
    return await auth_svc.get_current_user(token)
