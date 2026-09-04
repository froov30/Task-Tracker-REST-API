from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import task as task_model
from app.schemas.task import (
    SortBy,
    SortOrder,
    TaskCreate,
    TaskOut,
    TaskStatus,
    TaskUpdate,
)

router = APIRouter()


def _task_not_found(task_id: int) -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_404_NOT_FOUND,
        detail=f"Task with id {task_id} not found",
    )


@router.post("", status_code=http_status.HTTP_201_CREATED, response_model=TaskOut)
async def create_task(
    payload: TaskCreate,
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    row = await task_model.create_task(db, payload.model_dump())
    return TaskOut.model_validate(row)


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    status: TaskStatus | None = Query(default=None),
    due_before: date | None = Query(default=None),
    due_after: date | None = Query(default=None),
    sort_by: SortBy = Query(default="created_at"),
    sort_order: SortOrder = Query(default="desc"),
    db: AsyncSession = Depends(get_db),
) -> list[TaskOut]:
    rows = await task_model.get_all_tasks(
        db,
        status=status,
        due_before=due_before,
        due_after=due_after,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return [TaskOut.model_validate(row) for row in rows]


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    row = await task_model.get_task_by_id(db, task_id)
    if row is None:
        raise _task_not_found(task_id)
    return TaskOut.model_validate(row)


@router.put("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: int,
    payload: TaskUpdate,
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    result = await task_model.update_task(
        db,
        task_id,
        payload.model_dump(exclude_unset=True),
        payload.version,
    )
    if result == task_model.NOT_FOUND:
        raise _task_not_found(task_id)
    if result == task_model.VERSION_CONFLICT:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="version mismatch, re-fetch and retry",
        )
    return TaskOut.model_validate(result)


@router.delete("/{task_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = await task_model.get_task_by_id(db, task_id)
    if row is None:
        raise _task_not_found(task_id)
    await task_model.delete_task(db, task_id)
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)
