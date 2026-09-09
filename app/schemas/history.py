"""
Pydantic schemas for task audit history.
"""

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator


class HistoryOut(BaseModel):
    id: int
    task_id: int
    user_id: int
    action: str
    changed_fields: dict[str, Any] | None = None
    snapshot: dict[str, Any] | None = None
    created_at: datetime

    @field_validator("changed_fields", "snapshot", mode="before")
    @classmethod
    def _parse_json(cls, value):
        """Decode JSON strings stored in TEXT columns back into dicts."""
        if value is None or isinstance(value, dict):
            return value
        if isinstance(value, str):
            return json.loads(value)
        return value
