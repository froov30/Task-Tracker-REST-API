"""
AuthService — registration, login, and current-user resolution.

Rules for this layer:
  - No SQL — all DB access goes through UserRepository.
  - Translates auth failures into HTTPExceptions with structured details.
  - Uses app.security for hashing and JWT (no crypto here directly).
"""

from fastapi import HTTPException
from fastapi import status as http_status

from app.models.orm import User
from app.repositories.user_repository import UserRepository
from app.schemas.errors import ErrorCode, error_detail
from app.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_401_UNAUTHORIZED,
        detail=error_detail(
            ErrorCode.UNAUTHORIZED, "Could not validate credentials"
        ),
        headers={"WWW-Authenticate": "Bearer"},
    )


class AuthService:
    def __init__(self, repo: UserRepository) -> None:
        self._repo = repo

    async def register(self, email: str, password: str) -> User:
        """
        Create a new user with a bcrypt-hashed password.

        Raises 400 if the email is already registered.
        """
        existing = await self._repo.get_by_email(email)
        if existing is not None:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=error_detail(
                    ErrorCode.EMAIL_ALREADY_REGISTERED,
                    "Email already registered",
                    resource="user",
                ),
            )
        hashed = hash_password(password)
        return await self._repo.create(email=email, hashed_password=hashed)

    async def login(self, email: str, password: str) -> str:
        """
        Verify credentials and return a signed JWT access token.

        Raises 401 on unknown email or wrong password (same message for both
        so the endpoint doesn't leak which emails exist).
        """
        user = await self._repo.get_by_email(email)
        if user is None or not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=http_status.HTTP_401_UNAUTHORIZED,
                detail=error_detail(
                    ErrorCode.UNAUTHORIZED, "Incorrect email or password"
                ),
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not user.is_active:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail=error_detail(
                    ErrorCode.FORBIDDEN, "User account is inactive"
                ),
            )
        return create_access_token(subject=user.id)

    async def get_current_user(self, token: str) -> User:
        """
        Resolve the authenticated user from a JWT.

        Raises 401 if the token is invalid/expired or the user no longer
        exists; 403 if the user is inactive.
        """
        user_id = decode_access_token(token)
        if user_id is None:
            raise _credentials_exception()

        user = await self._repo.get_by_id(user_id)
        if user is None:
            raise _credentials_exception()
        if not user.is_active:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail=error_detail(
                    ErrorCode.FORBIDDEN, "User account is inactive"
                ),
            )
        return user
