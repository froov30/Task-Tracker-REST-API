"""
Async data-access functions for the tasks table.

Replaces the old sqlite3-based implementation with SQLAlchemy 2.0 async.
Public API is intentionally identical to the previous module so the router
needs only minimal changes (add `db` argument, await calls).

Sentinels NOT_FOUND and VERSION_CONFLICT are preserved for backward compat
with the router's error-handling logic.
"""

from datetime import date, datetime, timezone

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Task

# ---------------------------------------------------------------------------
# Sentinels — same values as the old module
# ---------------------------------------------------------------------------
NOT_FOUND = "NOT_FOUND"
VERSION_CONFLICT = "VERSION_CONFLICT"

# ---------------------------------------------------------------------------
# Whitelist maps (preserved from original)
# ---------------------------------------------------------------------------
SORT_COLUMNS: dict[str, str] = {
    "created_at": "created_at",
    "due_date": "due_date",
    "title": "title",
}
SORT_ORDERS: dict[str, str] = {
    "asc": "asc",
    "desc": "desc",
}
_UPDATABLE_COLUMNS = frozenset(("title", "description", "status", "due_date"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_str(value) -> str | None:
    """Coerce date / Enum values to their string representation for storage."""
    if value is None:
        return None
    if hasattr(value, "value"):       # Enum
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

async def create_task(db: AsyncSession, data: dict) -> dict:
    now = _utcnow()
    task = Task(
        title=data["title"],
        description=data.get("description"),
        status="pending",
        due_date=_to_str(data.get("due_date")),
        created_at=now,
        updated_at=now,
        version=1,
    )
    db.add(task)
    await db.flush()        # get the auto-generated id
    await db.refresh(task)  # reload all columns from DB
    return task.to_dict()


async def get_task_by_id(db: AsyncSession, task_id: int) -> dict | None:
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        return None
    return task.to_dict()


async def get_all_tasks(
    db: AsyncSession,
    status: str | None = None,
    due_before: date | None = None,
    due_after: date | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> list[dict]:
    column_name = SORT_COLUMNS.get(sort_by)
    if column_name is None:
        raise ValueError(f"invalid sort_by: {sort_by!r}")
    if sort_order not in SORT_ORDERS:
        raise ValueError(f"invalid sort_order: {sort_order!r}")

    stmt = select(Task)

    if status is not None:
        stmt = stmt.where(Task.status == _to_str(status))
    if due_before is not None:
        # due_date stored as TEXT "YYYY-MM-DD" — lexicographic compare works
        stmt = stmt.where(Task.due_date <= due_before.isoformat())
    if due_after is not None:
        stmt = stmt.where(Task.due_date >= due_after.isoformat())

    col = getattr(Task, column_name)
    stmt = stmt.order_by(col.asc() if sort_order == "asc" else col.desc())

    result = await db.execute(stmt)
    return [row.to_dict() for row in result.scalars().all()]


async def update_task(
    db: AsyncSession,
    task_id: int,
    data: dict,
    version: int,
) -> dict | str:
    """
    Optimistic-locking update.

    Returns:
      - updated task dict on success
      - NOT_FOUND sentinel if no row with that id exists
      - VERSION_CONFLICT sentinel if the row exists but version doesn't match
    """
    now = _utcnow()

    # Build the SET clause from whitelisted updatable columns present in data
    values: dict = {"updated_at": now, "version": Task.version + 1}
    for col in _UPDATABLE_COLUMNS:
        if col in data:
            values[col] = _to_str(data[col])

    stmt = (
        update(Task)
        .where(Task.id == task_id, Task.version == version)
        .values(**values)
        .returning(Task)
    )
    result = await db.execute(stmt)
    updated = result.scalar_one_or_none()

    if updated is not None:
        return updated.to_dict()

    # rowcount == 0: distinguish 404 vs 409
    exists_result = await db.execute(
        select(func.count()).where(Task.id == task_id)
    )
    exists = exists_result.scalar_one() > 0
    return VERSION_CONFLICT if exists else NOT_FOUND


async def delete_task(db: AsyncSession, task_id: int) -> bool:
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        return False
    await db.delete(task)
    return True
