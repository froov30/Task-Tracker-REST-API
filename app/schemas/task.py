import math
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, StringConstraints

TitleStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class TaskStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class TaskPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


SortBy = Literal["created_at", "due_date", "title", "priority"]
SortOrder = Literal["asc", "desc"]


class TaskCreate(BaseModel):
    title: TitleStr
    description: str | None = None
    due_date: date | None = None
    priority: TaskPriority = TaskPriority.medium


class TaskUpdate(BaseModel):
    title: TitleStr | None = None
    description: str | None = None
    status: TaskStatus | None = None
    due_date: date | None = None
    priority: TaskPriority | None = None
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
    priority: TaskPriority
    user_id: int


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated envelope used by list endpoints."""

    items: list[T]
    total: int = Field(description="Total number of matching records")
    page: int = Field(description="Current page number (1-indexed)")
    page_size: int = Field(description="Number of items per page")
    pages: int = Field(description="Total number of pages")

    @classmethod
    def build(
        cls,
        items: list[T],
        total: int,
        page: int,
        page_size: int,
    ) -> "PaginatedResponse[T]":
        pages = math.ceil(total / page_size) if page_size > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )
