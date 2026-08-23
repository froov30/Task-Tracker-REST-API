from contextlib import contextmanager
from datetime import date, datetime, timezone
from enum import Enum

from app.database import get_connection

NOT_FOUND = "NOT_FOUND"
VERSION_CONFLICT = "VERSION_CONFLICT"

SORT_COLUMNS = {
    "created_at": "created_at",
    "due_date": "due_date",
    "title": "title",
}
SORT_ORDERS = {
    "asc": "ASC",
    "desc": "DESC",
}
_UPDATABLE_COLUMNS = ("title", "description", "status", "due_date")


@contextmanager
def _connection():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_sql(value):
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _row_to_dict(row) -> dict:
    return dict(row)


def create_task(data: dict) -> dict:
    now = _now_iso()
    with _connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tasks (title, description, status, due_date, created_at, updated_at, version)
            VALUES (?, ?, 'pending', ?, ?, ?, 1)
            """,
            (
                _to_sql(data["title"]),
                _to_sql(data.get("description")),
                _to_sql(data.get("due_date")),
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return _row_to_dict(row)


def get_all_tasks(
    status=None,
    due_before=None,
    due_after=None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> list[dict]:
    column = SORT_COLUMNS.get(sort_by)
    if column is None:
        raise ValueError(f"invalid sort_by: {sort_by!r}")
    direction = SORT_ORDERS.get(sort_order)
    if direction is None:
        raise ValueError(f"invalid sort_order: {sort_order!r}")

    clauses: list[str] = []
    params: list = []
    if status is not None:
        clauses.append("status = ?")
        params.append(_to_sql(status))
    if due_before is not None:
        clauses.append("due_date <= ?")
        params.append(_to_sql(due_before))
    if due_after is not None:
        clauses.append("due_date >= ?")
        params.append(_to_sql(due_after))

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM tasks {where} ORDER BY {column} {direction}"

    with _connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_task_by_id(task_id: int) -> dict | None:
    with _connection() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def update_task(task_id: int, data: dict, version: int):
    now = _now_iso()
    assignments = ["updated_at = ?", "version = version + 1"]
    params: list = [now]
    for column in _UPDATABLE_COLUMNS:
        if column in data:
            assignments.append(f"{column} = ?")
            params.append(_to_sql(data[column]))
    params.extend([task_id, version])

    sql = (
        f"UPDATE tasks SET {', '.join(assignments)} "
        "WHERE id = ? AND version = ?"
    )

    with _connection() as conn:
        cursor = conn.execute(sql, params)
        if cursor.rowcount == 1:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            return _row_to_dict(row)

        existing = conn.execute(
            "SELECT id FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()

    if existing is None:
        return NOT_FOUND
    return VERSION_CONFLICT


def delete_task(task_id: int) -> bool:
    with _connection() as conn:
        cursor = conn.execute(
            "DELETE FROM tasks WHERE id = ?",
            (task_id,),
        )
        return cursor.rowcount > 0
