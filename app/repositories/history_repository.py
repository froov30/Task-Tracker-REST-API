"""
HistoryRepository — writes and reads audit entries for tasks.

changed_fields and snapshot are stored as JSON strings (TEXT column) so the
schema is portable between SQLite (tests) and PostgreSQL (production).
"""

import json
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import TaskHistory


def _json_default(value):
    """Serialise datetime/date to ISO strings for JSON storage."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


class HistoryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def record(
        self,
        *,
        task_id: int,
        user_id: int,
        action: str,
        changed_fields: dict | None = None,
        snapshot: dict | None = None,
    ) -> dict:
        """Insert an audit entry and return it as a dict."""
        entry = TaskHistory(
            task_id=task_id,
            user_id=user_id,
            action=action,
            changed_fields=(
                json.dumps(changed_fields, default=_json_default)
                if changed_fields is not None
                else None
            ),
            snapshot=(
                json.dumps(snapshot, default=_json_default)
                if snapshot is not None
                else None
            ),
        )
        self._db.add(entry)
        await self._db.flush()
        await self._db.refresh(entry)
        return entry.to_dict()

    async def list_for_task(self, task_id: int) -> list[dict]:
        """Return all audit entries for a task, oldest first."""
        result = await self._db.execute(
            select(TaskHistory)
            .where(TaskHistory.task_id == task_id)
            .order_by(TaskHistory.id.asc())
        )
        return [row.to_dict() for row in result.scalars().all()]
