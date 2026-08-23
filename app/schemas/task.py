from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

TitleStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class TaskStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


SortBy = Literal["created_at", "due_date", "title"]
SortOrder = Literal["asc", "desc"]


class TaskCreate(BaseModel):
    title: TitleStr
    description: str | None = None
    due_date: date | None = None


class TaskUpdate(BaseModel):
    title: TitleStr | None = None
    description: str | None = None
    status: TaskStatus | None = None
    due_date: date | None = None
    version: int = Field(ge=1)


class TaskOut(BaseModel):
    id: int
    title: str
    description: str | None
    status: TaskStatus
    due_date: date | None
    created_at: datetime
    updated_at: datetime
    version: int
