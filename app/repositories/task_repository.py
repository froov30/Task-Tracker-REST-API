"""
TaskRepository — thin async wrappers around SQLAlchemy queries.

Rules for this layer:
  - No business logic, no HTTP concerns, no FastAPI imports.
  - Every method accepts an AsyncSession injected by the caller.
  - All queries are scoped to a user_id so users only ever see/modify
    their own tasks (ownership isolation at the data layer).
  - Sentinel values NOT_FOUND / VERSION_CONFLICT signal DB-level outcomes
    (row missing vs version mismatch) back to the service layer.
  - Filter / sort params are validated against whitelists before touching SQL
    so injection is impossible even if callers pass user-supplied strings.
"""

from datetime import date, datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Task

# ---------------------------------------------------------------------------
# Sentinel return values
# ---------------------------------------------------------------------------
NOT_FOUND = "NOT_FOUND"
VERSION_CONFLICT = "VERSION_CONFLICT"
ALREADY_ACTIVE = "ALREADY_ACTIVE"   # restore attempted on a non-deleted task

# ---------------------------------------------------------------------------
# Safe allowlists for dynamic ORDER BY (SQL injection guard)
# ---------------------------------------------------------------------------
SORT_COLUMNS: dict[str, str] = {
    "created_at": "created_at",
    "due_date": "due_date",
    "title": "title",
    "priority": "priority",
}
SORT_ORDERS: dict[str, str] = {
    "asc": "asc",
    "desc": "desc",
}

# Columns that may appear in an UPDATE payload
_UPDATABLE_COLUMNS = frozenset(
    {"title", "description", "status", "due_date", "priority"}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_str(value) -> str | None:
    """Coerce date / Enum values to their plain string form for storage."""
    if value is None:
        return None
    if hasattr(value, "value"):               # str-Enum (.value is already str)
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


# ---------------------------------------------------------------------------
# TaskRepository
# ---------------------------------------------------------------------------

class TaskRepository:
    """
    All database interactions for the tasks table, scoped by user_id.

    Instantiate with an AsyncSession; the session lifecycle (commit / rollback)
    is managed by the ``get_db`` dependency in database.py — the repository
    never commits or rolls back directly.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_by_id(
        self, task_id: int, *, user_id: int, include_deleted: bool = False
    ) -> dict | None:
        """
        Return the task as a dict if it belongs to user_id, else None.

        By default soft-deleted tasks are excluded; pass include_deleted=True
        to also return a soft-deleted row (used by the restore flow).
        """
        stmt = select(Task).where(Task.id == task_id, Task.user_id == user_id)
        if not include_deleted:
            stmt = stmt.where(Task.deleted_at.is_(None))
        result = await self._db.execute(stmt)
        task = result.scalar_one_or_none()
        return task.to_dict() if task is not None else None

    async def get_owner_id(self, task_id: int) -> int | None:
        """
        Return the user_id that owns task_id, regardless of scope or soft-delete.

        Used by the service layer to distinguish 404 (no such task anywhere)
        from 403 (task exists but belongs to another user).
        """
        result = await self._db.execute(
            select(Task.user_id).where(Task.id == task_id)
        )
        return result.scalar_one_or_none()

    def _apply_filters(
        self,
        stmt,
        *,
        user_id: int,
        status: str | None,
        due_before: date | None,
        due_after: date | None,
        priority: str | None = None,
        include_deleted: bool = False,
    ):
        """Apply the ownership scope + soft-delete filter + shared WHERE clauses."""
        stmt = stmt.where(Task.user_id == user_id)
        if not include_deleted:
            stmt = stmt.where(Task.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(Task.status == _to_str(status))
        if priority is not None:
            stmt = stmt.where(Task.priority == _to_str(priority))
        if due_before is not None:
            stmt = stmt.where(Task.due_date <= due_before.isoformat())
        if due_after is not None:
            stmt = stmt.where(Task.due_date >= due_after.isoformat())
        return stmt

    async def get_all(
        self,
        *,
        user_id: int,
        status: str | None = None,
        due_before: date | None = None,
        due_after: date | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        include_deleted: bool = False,
    ) -> list[dict]:
        """Return all of user_id's tasks matching filters, in requested order."""
        column_name = SORT_COLUMNS.get(sort_by)
        if column_name is None:
            raise ValueError(f"invalid sort_by: {sort_by!r}")
        if sort_order not in SORT_ORDERS:
            raise ValueError(f"invalid sort_order: {sort_order!r}")

        stmt = select(Task)
        stmt = self._apply_filters(
            stmt,
            user_id=user_id,
            status=status,
            due_before=due_before,
            due_after=due_after,
            include_deleted=include_deleted,
        )

        col = getattr(Task, column_name)
        stmt = stmt.order_by(col.asc() if sort_order == "asc" else col.desc())

        result = await self._db.execute(stmt)
        return [row.to_dict() for row in result.scalars().all()]

    async def count_all(
        self,
        *,
        user_id: int,
        status: str | None = None,
        due_before: date | None = None,
        due_after: date | None = None,
        priority: str | None = None,
        include_deleted: bool = False,
    ) -> int:
        """Count user_id's tasks matching the given filters."""
        stmt = select(func.count()).select_from(Task)
        stmt = self._apply_filters(
            stmt,
            user_id=user_id,
            status=status,
            due_before=due_before,
            due_after=due_after,
            priority=priority,
            include_deleted=include_deleted,
        )
        result = await self._db.execute(stmt)
        return result.scalar_one()

    async def get_all_paginated(
        self,
        *,
        user_id: int,
        status: str | None = None,
        due_before: date | None = None,
        due_after: date | None = None,
        priority: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 20,
        include_deleted: bool = False,
    ) -> list[dict]:
        """Return one page of user_id's tasks matching the given filters."""
        column_name = SORT_COLUMNS.get(sort_by)
        if column_name is None:
            raise ValueError(f"invalid sort_by: {sort_by!r}")
        if sort_order not in SORT_ORDERS:
            raise ValueError(f"invalid sort_order: {sort_order!r}")

        stmt = select(Task)
        stmt = self._apply_filters(
            stmt,
            user_id=user_id,
            status=status,
            due_before=due_before,
            due_after=due_after,
            priority=priority,
            include_deleted=include_deleted,
        )

        col = getattr(Task, column_name)
        stmt = stmt.order_by(col.asc() if sort_order == "asc" else col.desc())

        offset = (page - 1) * page_size
        stmt = stmt.limit(page_size).offset(offset)

        result = await self._db.execute(stmt)
        return [row.to_dict() for row in result.scalars().all()]

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def create(self, data: dict, *, user_id: int) -> dict:
        """Insert a new task owned by user_id and return the persisted row."""
        now = _utcnow()
        task = Task(
            title=data["title"],
            description=data.get("description"),
            status="pending",
            due_date=_to_str(data.get("due_date")),
            priority=_to_str(data.get("priority")) or "medium",
            created_at=now,
            updated_at=now,
            version=1,
            user_id=user_id,
        )
        self._db.add(task)
        await self._db.flush()
        await self._db.refresh(task)
        return task.to_dict()

    async def update_raw(
        self,
        task_id: int,
        data: dict,
        version: int,
        *,
        user_id: int,
    ) -> dict | str:
        """
        Optimistic-locking UPDATE, scoped to user_id.

        Returns:
          - updated task dict on success
          - NOT_FOUND  if no row with task_id belongs to user_id
          - VERSION_CONFLICT if the row exists (for this user) but version != *version*
        """
        now = _utcnow()

        values: dict = {
            "updated_at": now,
            "version": Task.version + 1,
        }
        for col in _UPDATABLE_COLUMNS:
            if col in data:
                values[col] = _to_str(data[col])

        stmt = (
            update(Task)
            .where(
                Task.id == task_id,
                Task.user_id == user_id,
                Task.deleted_at.is_(None),
                Task.version == version,
            )
            .values(**values)
            .returning(Task)
        )
        result = await self._db.execute(stmt)
        updated = result.scalar_one_or_none()

        if updated is not None:
            return updated.to_dict()

        # rowcount == 0: distinguish 404 from 409 (within this user's active scope)
        exists_result = await self._db.execute(
            select(func.count()).where(
                Task.id == task_id,
                Task.user_id == user_id,
                Task.deleted_at.is_(None),
            )
        )
        exists = exists_result.scalar_one() > 0
        return VERSION_CONFLICT if exists else NOT_FOUND

    async def delete(
        self, task_id: int, *, user_id: int, version: int | None = None
    ) -> dict | str:
        """
        Soft-delete user_id's task by setting deleted_at = now().

        If *version* is provided, the delete is version-guarded (OCC):
          - matches only when the row's version equals *version*
          - 0 rows affected → distinguish NOT_FOUND vs VERSION_CONFLICT

        Returns:
          - the soft-deleted task dict on success
          - NOT_FOUND if no active row with task_id belongs to user_id
          - VERSION_CONFLICT if a version was given and it didn't match
        """
        now = _utcnow()

        stmt = (
            update(Task)
            .where(
                Task.id == task_id,
                Task.user_id == user_id,
                Task.deleted_at.is_(None),
            )
        )
        if version is not None:
            stmt = stmt.where(Task.version == version)

        stmt = stmt.values(deleted_at=now).returning(Task)
        result = await self._db.execute(stmt)
        deleted = result.scalar_one_or_none()

        if deleted is not None:
            return deleted.to_dict()

        # Nothing updated — figure out why (within active scope).
        exists_result = await self._db.execute(
            select(func.count()).where(
                Task.id == task_id,
                Task.user_id == user_id,
                Task.deleted_at.is_(None),
            )
        )
        exists = exists_result.scalar_one() > 0
        # If the active row exists but wasn't matched, it was a version mismatch.
        if exists and version is not None:
            return VERSION_CONFLICT
        return NOT_FOUND

    async def restore(self, task_id: int, *, user_id: int) -> dict | str:
        """
        Restore a soft-deleted task by clearing deleted_at.

        Returns:
          - the restored task dict on success
          - NOT_FOUND if no soft-deleted row with task_id belongs to user_id
          - ALREADY_ACTIVE if the row exists but isn't soft-deleted
        """
        stmt = (
            update(Task)
            .where(
                Task.id == task_id,
                Task.user_id == user_id,
                Task.deleted_at.is_not(None),
            )
            .values(deleted_at=None)
            .returning(Task)
        )
        result = await self._db.execute(stmt)
        restored = result.scalar_one_or_none()

        if restored is not None:
            return restored.to_dict()

        # Not soft-deleted — is it active, or does it not exist at all?
        active_result = await self._db.execute(
            select(func.count()).where(
                Task.id == task_id,
                Task.user_id == user_id,
                Task.deleted_at.is_(None),
            )
        )
        is_active = active_result.scalar_one() > 0
        return ALREADY_ACTIVE if is_active else NOT_FOUND
