"""
Task router — HTTP concerns only.

Each handler:
  1. Requires an authenticated user (get_current_user dependency).
  2. Receives validated input from FastAPI (Pydantic schemas, query params).
  3. Calls the TaskService method, scoped to current_user.id.
  4. Returns the response model.

No SQL, no sentinel inspection, no business logic lives here.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from fastapi import status as http_status

from app.dependencies import get_current_user, get_task_service
from app.models.orm import User
from app.schemas.history import HistoryOut
from app.schemas.task import (
    PaginatedResponse,
    SortBy,
    SortOrder,
    TaskCreate,
    TaskOut,
    TaskStatus,
    TaskUpdate,
)
from app.services.task_service import TaskService

router = APIRouter()


@router.post("", status_code=http_status.HTTP_201_CREATED, response_model=TaskOut)
async def create_task(
    payload: TaskCreate,
    svc: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_user),
) -> TaskOut:
    row = await svc.create_task(payload.model_dump(), user_id=current_user.id)
    return TaskOut.model_validate(row)


@router.get("", response_model=PaginatedResponse[TaskOut])
async def list_tasks(
    status: TaskStatus | None = Query(default=None),
    due_before: date | None = Query(default=None),
    due_after: date | None = Query(default=None),
    sort_by: SortBy = Query(default="created_at"),
    sort_order: SortOrder = Query(default="desc"),
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(
        default=20, ge=1, le=100, description="Items per page (max 100)"
    ),
    include_deleted: bool = Query(
        default=False, description="Include soft-deleted tasks"
    ),
    svc: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[TaskOut]:
    return await svc.list_tasks_paginated(
        user_id=current_user.id,
        status=status,
        due_before=due_before,
        due_after=due_after,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
        include_deleted=include_deleted,
    )


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: int,
    svc: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_user),
) -> TaskOut:
    row = await svc.get_task(task_id, user_id=current_user.id)
    return TaskOut.model_validate(row)


@router.get("/{task_id}/history", response_model=list[HistoryOut])
async def get_task_history(
    task_id: int,
    svc: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_user),
) -> list[HistoryOut]:
    rows = await svc.get_history(task_id, user_id=current_user.id)
    return [HistoryOut.model_validate(row) for row in rows]


@router.put("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: int,
    payload: TaskUpdate,
    svc: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_user),
) -> TaskOut:
    row = await svc.update_task(
        task_id,
        payload.model_dump(exclude_unset=True),
        payload.version,
        user_id=current_user.id,
    )
    return TaskOut.model_validate(row)


@router.post("/{task_id}/restore", response_model=TaskOut)
async def restore_task(
    task_id: int,
    svc: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_user),
) -> TaskOut:
    row = await svc.restore_task(task_id, user_id=current_user.id)
    return TaskOut.model_validate(row)


@router.delete("/{task_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    version: int | None = Query(
        default=None,
        ge=1,
        description="If provided, delete is version-guarded (OCC); 409 on stale version",
    ),
    svc: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_user),
) -> Response:
    await svc.delete_task(task_id, user_id=current_user.id, version=version)
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)
