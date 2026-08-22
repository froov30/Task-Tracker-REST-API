# Architecture Plan — Task Tracker REST API

## 1. Guiding Principle
Strict layering: **routes never touch SQL, and the DB layer never sees HTTP concepts.**
Each layer has exactly one job, so a change in one (e.g., swapping SQLite for Postgres
later) touches only one file. This holds even with filtering/sorting and concurrency
control added — the whitelist map and version-check logic both live in `models/task.py`,
never in `routers/tasks.py`.

**This claim gets a real test, not just a theoretical one.** If Phase 7's load testing
shows SQLite's single-writer lock is a genuine bottleneck and warrants a PostgreSQL
migration, the layering above predicts that migration touches `database.py` and the
connection-handling parts of `models/task.py` — and nothing in `schemas/` or
`routers/`. Whether that prediction actually holds up in practice is worth noting
honestly in DECISIONS.md when (if) it happens, rather than assumed.

```
Client (curl / Postman / Swagger UI)
        │  HTTP request
        ▼
┌───────────────────────┐
│  routers/tasks.py      │  ← FastAPI path operations, HTTP concerns only
└───────────┬───────────┘
            │ validated Pydantic objects
            ▼
┌───────────────────────┐
│  schemas/task.py       │  ← Pydantic models: request/response shape + validation
└───────────┬───────────┘
            │ plain dict / typed args
            ▼
┌───────────────────────┐
│  models/task.py        │  ← data-access functions (CRUD + filtering/sorting +
│                         │    version-checked updates against SQLite)
└───────────┬───────────┘
            │ SQL
            ▼
┌───────────────────────┐
│  database.py           │  ← connection management, table creation
└───────────┬───────────┘
            ▼
        tasks.db (SQLite file)
```

## 2. Folder Structure

```
task-tracker-api/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app instance, startup hook, router registration
│   ├── database.py          # SQLite connection + init_db()
│   ├── models/
│   │   ├── __init__.py
│   │   └── task.py          # CRUD + filter/sort + version-checked update functions
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── task.py          # TaskCreate, TaskUpdate, TaskOut, TaskStatus, SortBy, SortOrder
│   └── routers/
│       ├── __init__.py
│       └── tasks.py         # 5 path operations, wire schemas <-> models
├── tests/
│   └── test_tasks.py        # mandatory pytest suite (CRUD, filter/sort, concurrency, validation)
├── .dockerignore
├── .gitignore                # excludes tasks.db, __pycache__, .env, venv/
├── Dockerfile
├── requirements.txt
├── .github/
│   └── workflows/
│       └── ci.yml            # lint + pytest on every push
└── README.md
```

## 3. Component Responsibilities

| Component | Responsibility | Must NOT do |
|-----------|-----------------|-------------|
| `main.py` | Create FastAPI app, include router, run `init_db()` on startup | Contain business logic or SQL |
| `database.py` | Open/close SQLite connections, create table (incl. `version` column) if missing | Know about Pydantic or HTTP |
| `models/task.py` | Raw CRUD against `tasks` table; builds whitelisted `ORDER BY` + parameterized `WHERE`; version-checked `UPDATE`, returns a sentinel on 0-row update so the router can distinguish 404 from 409 | Import FastAPI or Pydantic |
| `schemas/task.py` | Define & validate request/response shapes, including `SortBy`/`SortOrder` literals and required `version` on `TaskUpdate` | Touch the database |
| `routers/tasks.py` | Map HTTP verbs/paths to model calls, translate to `TaskOut`, raise `HTTPException` on 404/409 | Contain raw SQL or a hand-rolled whitelist (that logic lives in `models/task.py`) |

## 4. Request Lifecycle (example: `PUT /tasks/3`, now version-aware)
1. Uvicorn receives the HTTP request → hands to FastAPI's ASGI app.
2. FastAPI matches route in `routers/tasks.py: update_task(task_id, payload: TaskUpdate)`.
3. FastAPI parses body against `TaskUpdate` schema — missing `version` or invalid
   `status` → automatic `422`; valid → proceeds.
4. Route handler calls `models.task.update_task(task_id, payload)`, which runs
   `UPDATE tasks SET ..., version = version + 1 WHERE id = ? AND version = ?`.
5. `models/task.py` inspects the affected row count:
   - `0` rows and no task with that `id` exists → sentinel `NOT_FOUND`
   - `0` rows but the task *does* exist → sentinel `VERSION_CONFLICT`
   - `1` row → returns the updated row
6. Route handler branches explicitly on the three outcomes: `404`, `409`, or `200` with
   the row wrapped in `TaskOut`.
7. FastAPI serializes `TaskOut` → JSON → HTTP response.

## 5. Design Decisions Baked Into the Architecture
(Full reasoning in DECISIONS.md — this is the summary.)
- **No ORM** (raw `sqlite3` + small helper functions) — the schema is a single table;
  an ORM would add abstraction without payoff at this scale. (#3)
- **Enum-based status field** — prevents invalid status strings at the validation layer
  instead of relying on DB constraints alone. (#5)
- **Partial updates via `TaskUpdate`** — all fields `Optional` *except* `version`, so
  `PUT` behaves like a practical `PATCH` without adding a 6th endpoint, while still
  requiring the version the client last read. (#6, #10)
- **Startup-time table creation** — `init_db()` runs on FastAPI startup event so
  container instances need zero manual migration step. (#7)
- **Whitelisted sort columns** — `sort_by` is mapped through a fixed dict before
  reaching `ORDER BY`, never string-interpolated. (#8)
- **Optimistic concurrency over pessimistic locking** — a `version` column and `409`
  response, chosen over `SELECT ... FOR UPDATE` (not meaningfully supported by SQLite)
  or ignoring the problem entirely. (#9)
- **Automated tests are mandatory**, gating every phase after Phase 6. (#11)
- **Docker for containerization, Azure App Service for deployment** — chosen over a
  direct-process deploy target (e.g. Render) to align with the target job's cloud-native
  stack. (#12, #13)

## 6. Deployment Architecture (Docker + Azure App Service)
```
GitHub repo (main branch)
        │  push triggers CI
        ▼
GitHub Actions (.github/workflows/ci.yml)
  - install dependencies
  - run lint
  - run full pytest suite (mandatory — blocks on failure)
        │  on green, image build/deploy is a manual/triggered step
        ▼
Docker build
  - base: python:3.11-slim
  - COPY app/, requirements.txt
  - RUN pip install -r requirements.txt
  - CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
        │  push image to container registry (ACR or Docker Hub)
        ▼
Azure App Service for Containers
  - pulls image, runs container
  - env vars: PORT, DATABASE_PATH
  - disk: ephemeral per instance unless a persistent mount is configured
    (documented limitation — see PRD.md Risks)
        │
        ▼
Public URL: https://task-tracker-api-xxxx.azurewebsites.net
  /docs   → Swagger UI
  /tasks  → API root
```
