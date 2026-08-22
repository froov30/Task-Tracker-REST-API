# TRD — Task Tracker REST API

## 1. Tech Stack

| Layer | Choice | Notes |
|-------|--------|-------|
| Language | Python 3.11+ | |
| Web framework | FastAPI | async, auto OpenAPI/Swagger docs, native Pydantic integration |
| Validation | Pydantic v2 | request/response schema enforcement |
| Server | Uvicorn | ASGI server, used both locally and inside the container |
| Database | SQLite | file-based, zero-infra persistence |
| DB access | `sqlite3` (stdlib) via a small data-access layer | see DECISIONS.md #3 for why not an ORM |
| Testing | pytest + FastAPI `TestClient` | mandatory, not optional — see DECISIONS.md #11 |
| Load testing | Locust | measures real concurrent-request behavior; see §7.5 |
| Database (candidate migration) | PostgreSQL (Azure Database for PostgreSQL, if migration is warranted) | conditional on Phase 7 load-test results — see PRD.md §5 |
| Version control | Git / GitHub | incremental commits |
| Containerization | Docker | see DECISIONS.md #12 |
| Deployment | Azure App Service for Containers | see DECISIONS.md #13 |
| CI/CD | GitHub Actions | lint + full test suite on every push |
| Docs | README.md + auto-generated `/docs` (Swagger UI) | |

## 2. Data Model

### Table: `tasks`

| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| title | TEXT | NOT NULL |
| description | TEXT | NULLABLE |
| status | TEXT | NOT NULL, DEFAULT `'pending'`, one of `pending`/`in_progress`/`completed`/`cancelled` |
| due_date | TEXT (ISO date) | NULLABLE |
| created_at | TEXT (ISO datetime) | NOT NULL, set on insert |
| updated_at | TEXT (ISO datetime) | NOT NULL, set on insert and every update |
| **version** | INTEGER | NOT NULL, DEFAULT `1`, incremented on every successful update |

### Pydantic Schemas

- `TaskCreate` — `title: str`, `description: str | None`, `due_date: date | None`
- `TaskUpdate` — `title`, `description`, `status`, `due_date` all optional (partial
  update); **`version: int` is required** — the one intentional exception to "everything
  optional" (see DECISIONS.md #10 for why this doesn't contradict DECISIONS.md #6)
- `TaskOut` — full representation returned to client: `id`, `title`, `description`,
  `status`, `due_date`, `created_at`, `updated_at`, `version`
- `TaskStatus` — `Enum`: `pending`, `in_progress`, `completed`, `cancelled`
- `SortBy` — `Literal["created_at", "due_date", "title"]`, default `"created_at"`
- `SortOrder` — `Literal["asc", "desc"]`, default `"desc"`

## 3. API Contract (5 Endpoints)

### `POST /tasks`
Create a task.
- Request body: `TaskCreate`
- Response: `201 Created`, body: `TaskOut` (with `version=1`)
- Errors: `422` on missing/invalid `title`

### `GET /tasks`
List tasks, with combinable filtering and sorting.
- Query params:
  - `status: TaskStatus | None`
  - `due_before: date | None`, `due_after: date | None`
  - `sort_by: SortBy = "created_at"`, `sort_order: SortOrder = "desc"`
- Response: `200 OK`, body: `list[TaskOut]`
- Errors: `422` on invalid enum/literal values for any filter or sort param
- **Safety requirement:** `sort_by` is mapped through a whitelist (`SORT_COLUMNS` dict)
  to a real column name before use in `ORDER BY` — never string-interpolated directly.
  Filters use standard parameterized `WHERE` clauses. See DECISIONS.md #8.

### `GET /tasks/{task_id}`
Fetch one task.
- Response: `200 OK`, body: `TaskOut`
- Errors: `404` if not found

### `PUT /tasks/{task_id}`
Update a task (partial update supported), guarded by optimistic concurrency control.
- Request body: `TaskUpdate` (requires `version`)
- Response: `200 OK`, body: `TaskOut` (with incremented `version`)
- Errors:
  - `404` if the task does not exist
  - `409 Conflict` if the supplied `version` does not match the current stored
    version (the update is rejected; client should re-fetch and retry)
  - `422` on invalid `status` value or missing `version`

### `DELETE /tasks/{task_id}`
Delete a task.
- Response: `204 No Content`
- Errors: `404` if not found

## 4. Error Handling Standard

All errors return FastAPI's standard JSON shape:
```json
{ "detail": "Task with id 7 not found" }
```
- `404` → resource not found (custom `HTTPException`)
- `409` → optimistic concurrency conflict (custom `HTTPException`, new in this version)
- `422` → validation failure (handled automatically by Pydantic/FastAPI)
- `500` → unhandled server error (should never occur in normal operation; logged)

## 5. Non-Functional Requirements

- **Validation-first:** no request reaches the database layer without passing Pydantic
  validation.
- **Statelessness:** each request is independent; no server-side session state.
- **Concurrency-safe writes:** `PUT` requires a version check; no request can silently
  overwrite a concurrent change.
- **Query safety:** no user-controlled string is ever interpolated directly into SQL;
  sorting goes through a whitelist, filtering uses parameter binding.
- **Persistence:** SQLite file (`tasks.db`) committed to `.gitignore`, created on first
  run. Ephemeral within a given container instance unless a persistent volume is
  explicitly mounted (documented limitation, see PRD.md Risks).
- **Idempotent reads:** GET requests never mutate state.
- **Documentation:** OpenAPI schema auto-served at `/docs` and `/openapi.json`; README
  documents setup + curl examples for all 5 endpoints, including the `409` conflict
  flow.
- **Portability:** runs identically locally (`uvicorn app.main:app --reload`), inside
  Docker (`docker run`), and on Azure App Service.

## 6. Environment & Config

| Variable | Purpose | Default |
|----------|---------|---------|
| `PORT` | App Service-provided port | `8000` locally |
| `DATABASE_PATH` | path to SQLite file | `./tasks.db` |

## 7. Testing Requirements (Mandatory)

Automated tests are a required gate, not an optional stretch goal — no phase after
Phase 6 proceeds until this suite passes. `tests/test_tasks.py`, pytest + FastAPI
`TestClient`:

- **CRUD happy path:** create → get → update → delete → 404-after-delete.
- **Filtering + sorting:** create tasks with different statuses/due_dates; assert
  combined filters (`status` + `due_before`) return the correct subset; assert
  `sort_by=due_date&sort_order=asc` returns correctly ordered results.
- **Concurrency conflict:** fetch a task (`version=1`), update it once (version becomes
  `2`), then attempt a second update still sending `version=1` → assert `409`.
- **Validation edge cases:** missing required `title` → 422; invalid `status` string →
  422; invalid `sort_by` value → 422; missing `version` on `PUT` → 422.
- CI (GitHub Actions) runs this full suite, plus linting, on every push — a red suite
  blocks merge.

## 7.5 Load Testing Requirements (Phase 7)

Run only after Phase 6's automated test suite is green — load testing measures the
behavior of code already proven correct, it doesn't substitute for correctness testing.

- **Tool:** Locust (`locustfile.py` at repo root), chosen for being Python-native (no
  new language/tooling context switch) and scriptable enough to target specific
  endpoints with specific concurrency patterns.
- **Required scenarios:**
  1. **Concurrent writes to the same resource** — many simulated users issuing
     `PUT /tasks/{id}` against the *same* task ID simultaneously. This directly
     exercises the optimistic concurrency control from DECISIONS.md #9: a successful
     test run should show `409` responses appearing under contention, not silent data
     loss or corrupted state.
  2. **Mixed read/write load at increasing concurrency** — ramp simulated concurrent
     users (e.g., 10 → 50 → 200) issuing a realistic mix of `POST`, `GET /tasks`, and
     `PUT` requests; record requests/sec, latency percentiles (p50/p95/p99), and
     error rate at each level.
- **Required output:** `docs/LOAD_TESTING.md` documenting the actual numbers observed
  — not a summary claim like "the API scales well," but the real data: throughput at
  each concurrency level, the specific concurrency point where errors or SQLite
  locking (`database is locked`) first appear, and latency degradation curve.
- **Run twice:** once locally against SQLite, and again in Phase 10 against the live
  Azure deployment — network and real infrastructure conditions differ from a local
  run, and both data points are more informative than either alone.
- **Decision gate:** the results determine whether PostgreSQL migration (see tech
  stack table above) proceeds before Phase 8, or whether SQLite's documented ceiling
  becomes the final, honest answer for this version. Either outcome is acceptable;
  what's required is that the decision is evidence-based, not assumed.

## 8. Deployment Requirements

- `requirements.txt` pinned, including `pytest`, `httpx` (TestClient dependency).
- `Dockerfile`: slim Python base image, installs `requirements.txt`, runs
  `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- `.dockerignore`: excludes `venv/`, `__pycache__/`, `tasks.db`, `.env`, `tests/`.
- Deployed to **Azure App Service for Containers**: image pushed to a container
  registry (Azure Container Registry or Docker Hub), App Service configured to pull and
  run it, `PORT` and `DATABASE_PATH` (or a `DATABASE_URL` if migrated to PostgreSQL,
  per §7.5's decision gate) set as App Service environment variables.
- **If Phase 7 load testing warrants a PostgreSQL migration:** provision Azure Database
  for PostgreSQL (Flexible Server) alongside App Service; `docker-compose.yml` gains a
  `postgres` service for local development parity; CI's GitHub Actions workflow gains a
  Postgres service container so tests run against the same database engine as
  production, not SQLite standing in for it.
- App must boot cleanly on a fresh container instance with no manual DB seeding step
  (tables auto-created on startup, including the `version` column).
- **CI pipeline (GitHub Actions):** on every push — install dependencies, run lint,
  run the full pytest suite. Deployment to Azure is a separate, manual/triggered step
  in this version (no auto-deploy-on-green required for scope).
