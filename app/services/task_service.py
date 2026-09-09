"""
TaskService — business logic layer for tasks.

Rules for this layer:
  - No SQL / SQLAlchemy imports — all DB work goes through repositories.
  - Translates repository sentinels into HTTPExceptions so the router stays
    thin (HTTP status codes only, zero business logic).
  - Every operation is scoped to a user_id: users can only see and mutate
    their own tasks. 404 vs 403 disambiguation avoids leaking other users'
    task existence.
  - Dispatches an audit entry (via HistoryRepository) at the end of every
    mutating operation: create, update, delete, restore.
"""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from fastapi import status as http_status

from app.repositories.history_repository import HistoryRepository
from app.repositories.task_repository import (
    ALREADY_ACTIVE,
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

# Audit action constants
ACTION_CREATED = "created"
ACTION_UPDATED = "updated"
ACTION_DELETED = "deleted"
ACTION_RESTORED = "restored"


class TaskService:
    def __init__(
        self,
        repo: TaskRepository,
        history: HistoryRepository | None = None,
    ) -> None:
        self._repo = repo
        self._history = history

    # ------------------------------------------------------------------
    # Audit dispatch (no-op if no history repository was injected)
    # ------------------------------------------------------------------

    async def _record(
        self,
        *,
        task_id: int,
        user_id: int,
        action: str,
        changed_fields: dict | None = None,
        snapshot: dict | None = None,
    ) -> None:
        if self._history is None:
            return
        await self._history.record(
            task_id=task_id,
            user_id=user_id,
            action=action,
            changed_fields=changed_fields,
            snapshot=snapshot,
        )

    # ------------------------------------------------------------------
    # Ownership helper
    # ------------------------------------------------------------------

    async def _raise_for_access(self, task_id: int, *, user_id: int) -> None:
        """
        Raise the correct error when a task is not accessible to user_id.

        - 403 if it exists but is owned by another user
        - 404 if it doesn't exist, or exists for this user but is soft-deleted
          (from the user's perspective a soft-deleted task is gone)

        Always raises; callers rely on this to short-circuit.
        """
        owner_id = await self._repo.get_owner_id(task_id)
        if owner_id is not None and owner_id != user_id:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail=error_detail(
                    ErrorCode.FORBIDDEN,
                    "You do not have permission to access this task",
                    resource="task",
                    resource_id=task_id,
                ),
            )
        # owner_id is None (never existed) OR owner_id == user_id but the
        # active-scope lookup missed it (soft-deleted) → 404 either way.
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                ErrorCode.TASK_NOT_FOUND,
                f"Task with id {task_id} not found",
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
        include_deleted: bool = False,
    ) -> PaginatedResponse[TaskOut]:
        """Return a paginated envelope of user_id's matching tasks."""
        filter_kwargs: dict = {
            "user_id": user_id,
            "status": status,
            "due_before": due_before,
            "due_after": due_after,
            "include_deleted": include_deleted,
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

    async def get_history(self, task_id: int, *, user_id: int) -> list[dict]:
        """Return the audit history for one of user_id's tasks (incl. deleted)."""
        # Ownership check — allow history even for soft-deleted tasks.
        row = await self._repo.get_by_id(
            task_id, user_id=user_id, include_deleted=True
        )
        if row is None:
            await self._raise_for_access(task_id, user_id=user_id)
        if self._history is None:
            return []
        return await self._history.list_for_task(task_id)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def create_task(self, data: dict, *, user_id: int) -> dict:
        """Create a task owned by user_id and record a 'created' audit entry."""
        row = await self._repo.create(data, user_id=user_id)
        await self._record(
            task_id=row["id"],
            user_id=user_id,
            action=ACTION_CREATED,
            snapshot=row,
        )
        return row

    def _validate_transition(self, current: str, target: str) -> None:
        """Raise 422 INVALID_TRANSITION if `current → target` is not allowed."""
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

        Validates status transitions, records an 'updated' audit entry on success.

        Raises 404 (missing), 403 (not owned), 422 (invalid transition),
        409 (version conflict).
        """
        if "status" in data:
            current = await self._repo.get_by_id(task_id, user_id=user_id)
            if current is None:
                await self._raise_for_access(task_id, user_id=user_id)
            target = data["status"]
            target = target.value if hasattr(target, "value") else target
            self._validate_transition(current["status"], target)  # type: ignore[index]

        result = await self._repo.update_raw(
            task_id, data, version, user_id=user_id
        )

        if result == NOT_FOUND:
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

        # changed_fields = the columns the caller actually submitted
        changed = {k: v for k, v in data.items()}
        await self._record(
            task_id=task_id,
            user_id=user_id,
            action=ACTION_UPDATED,
            changed_fields=changed,
            snapshot=result,  # type: ignore[arg-type]
        )
        return result  # type: ignore[return-value]

    async def delete_task(
        self, task_id: int, *, user_id: int, version: int | None = None
    ) -> None:
        """
        Soft-delete one of user_id's tasks and record a 'deleted' audit entry.

        If *version* is provided, the delete is OCC-guarded:
          - 409 VERSION_CONFLICT on stale version
        Without a version, the delete is unconditional (backward-compatible).

        Raises 404 (missing), 403 (not owned), 409 (stale version).
        """
        result = await self._repo.delete(task_id, user_id=user_id, version=version)

        if result == NOT_FOUND:
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

        await self._record(
            task_id=task_id,
            user_id=user_id,
            action=ACTION_DELETED,
            snapshot=result,  # type: ignore[arg-type]
        )

    async def restore_task(self, task_id: int, *, user_id: int) -> dict:
        """
        Restore a soft-deleted task and record a 'restored' audit entry.

        Raises 404 (missing), 403 (not owned), 409 if the task isn't deleted.
        """
        result = await self._repo.restore(task_id, user_id=user_id)

        if result == NOT_FOUND:
            await self._raise_for_access(task_id, user_id=user_id)
        if result == ALREADY_ACTIVE:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=error_detail(
                    ErrorCode.VERSION_CONFLICT,
                    "Task is not deleted; nothing to restore",
                    resource="task",
                    resource_id=task_id,
                ),
            )

        await self._record(
            task_id=task_id,
            user_id=user_id,
            action=ACTION_RESTORED,
            snapshot=result,  # type: ignore[arg-type]
        )
        return result  # type: ignore[return-value]
