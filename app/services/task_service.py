"""
TaskService — business logic layer for tasks.

Rules for this layer:
  - No SQL / SQLAlchemy imports — all DB work goes through TaskRepository.
  - Translates repository sentinels into HTTPExceptions so the router stays
    thin (HTTP status codes only, zero business logic).
  - Every operation is scoped to a user_id: users can only see and mutate
    their own tasks. A task belonging to another user is indistinguishable
    from a nonexistent one at this layer (returns 404), which avoids leaking
    the existence of other users' tasks.
  - Accepts a TaskRepository instance (constructor injection) so unit tests
    can swap in a mock without touching the DB.
"""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from fastapi import status as http_status

from app.repositories.task_repository import (
    NOT_FOUND,
    VERSION_CONFLICT,
    TaskRepository,
)
from app.schemas.errors import ErrorCode, error_detail
from app.schemas.task import PaginatedResponse, TaskOut

# ---------------------------------------------------------------------------
# Status transition state machine
# ---------------------------------------------------------------------------
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"in_progress", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),   # terminal
    "cancelled": set(),   # terminal
}


class TaskService:
    def __init__(self, repo: TaskRepository) -> None:
        self._repo = repo

    # ------------------------------------------------------------------
    # Ownership helper
    # ------------------------------------------------------------------

    async def _raise_for_access(self, task_id: int, *, user_id: int) -> None:
        """
        Raise the correct error when a task is not accessible to user_id.

        - 404 if the task doesn't exist at all
        - 403 if it exists but is owned by another user
        """
        owner_id = await self._repo.get_owner_id(task_id)
        if owner_id is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=error_detail(
                    ErrorCode.TASK_NOT_FOUND,
                    f"Task with id {task_id} not found",
                    resource="task",
                    resource_id=task_id,
                ),
            )
        if owner_id != user_id:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail=error_detail(
                    ErrorCode.FORBIDDEN,
                    "You do not have permission to access this task",
                    resource="task",
                    resource_id=task_id,
                ),
            )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def get_task(self, task_id: int, *, user_id: int) -> dict:
        """Return one of user_id's tasks. 404 if missing, 403 if owned by another."""
        row = await self._repo.get_by_id(task_id, user_id=user_id)
        if row is None:
            await self._raise_for_access(task_id, user_id=user_id)
        return row  # type: ignore[return-value]

    async def list_tasks(
        self,
        *,
        user_id: int,
        status: str | None = None,
        due_before: date | None = None,
        due_after: date | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> list[dict]:
        """Return all of user_id's matching tasks (unpaginated)."""
        try:
            return await self._repo.get_all(
                user_id=user_id,
                status=status,
                due_before=due_before,
                due_after=due_after,
                sort_by=sort_by,
                sort_order=sort_order,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_detail(ErrorCode.VALIDATION_ERROR, str(exc)),
            ) from exc

    async def list_tasks_paginated(
        self,
        *,
        user_id: int,
        status: str | None = None,
        due_before: date | None = None,
        due_after: date | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 20,
    ) -> PaginatedResponse[TaskOut]:
        """Return a paginated envelope of user_id's matching tasks."""
        filter_kwargs: dict = {
            "user_id": user_id,
            "status": status,
            "due_before": due_before,
            "due_after": due_after,
        }
        try:
            total = await self._repo.count_all(**filter_kwargs)
            rows = await self._repo.get_all_paginated(
                **filter_kwargs,
                sort_by=sort_by,
                sort_order=sort_order,
                page=page,
                page_size=page_size,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_detail(ErrorCode.VALIDATION_ERROR, str(exc)),
            ) from exc

        items = [TaskOut.model_validate(row) for row in rows]
        return PaginatedResponse.build(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def create_task(self, data: dict, *, user_id: int) -> dict:
        """Create and return a new task owned by user_id."""
        return await self._repo.create(data, user_id=user_id)

    def _validate_transition(self, current: str, target: str) -> None:
        """
        Raise 422 INVALID_TRANSITION if `current → target` is not allowed.

        A no-op transition (current == target) is always permitted.
        """
        if target == current:
            return
        allowed = VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_detail(
                    ErrorCode.INVALID_TRANSITION,
                    f"Cannot transition task from '{current}' to '{target}'",
                    resource="task",
                ),
            )

    async def update_task(
        self,
        task_id: int,
        data: dict,
        version: int,
        *,
        user_id: int,
    ) -> dict:
        """
        Apply an optimistic-locking update to one of user_id's tasks.

        If the payload changes status, the transition is validated against
        VALID_TRANSITIONS before any write occurs.

        Raises:
          - 404 if the task doesn't exist for this user
          - 403 if the task belongs to another user
          - 422 INVALID_TRANSITION on a disallowed status change
          - 409 on version conflict
        """
        # Validate a status change against the state machine first.
        if "status" in data:
            current = await self._repo.get_by_id(task_id, user_id=user_id)
            if current is None:
                # 404 or 403 depending on ownership
                await self._raise_for_access(task_id, user_id=user_id)
            target = data["status"]
            target = target.value if hasattr(target, "value") else target
            self._validate_transition(current["status"], target)  # type: ignore[index]

        result = await self._repo.update_raw(
            task_id, data, version, user_id=user_id
        )

        if result == NOT_FOUND:
            # Not in this user's scope — distinguish 404 (no such task) from
            # 403 (task owned by another user).
            await self._raise_for_access(task_id, user_id=user_id)
        if result == VERSION_CONFLICT:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=error_detail(
                    ErrorCode.VERSION_CONFLICT,
                    "version mismatch, re-fetch and retry",
                    resource="task",
                    resource_id=task_id,
                ),
            )
        return result  # type: ignore[return-value]  # dict at this point

    async def delete_task(self, task_id: int, *, user_id: int) -> None:
        """Delete one of user_id's tasks. 404 if missing, 403 if owned by another."""
        row = await self._repo.get_by_id(task_id, user_id=user_id)
        if row is None:
            await self._raise_for_access(task_id, user_id=user_id)
        await self._repo.delete(task_id, user_id=user_id)
