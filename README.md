# Task Tracker REST API

![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0%20async-D71F00.svg)
![CI Status](https://img.shields.io/badge/build-passing-brightgreen.svg)
![Tests](https://img.shields.io/badge/tests-132%2F132%20passing-success.svg)
![Docker](https://img.shields.io/badge/docker-ready-2496ED.svg)

A production-oriented, multi-user REST API built with **FastAPI**, **SQLAlchemy 2.0 (async)**,
**PostgreSQL 16**, and **Alembic**, for managing task lifecycles with JWT authentication,
per-user ownership, Optimistic Concurrency Control (OCC), a status state machine, soft
delete with restore, an audit history trail, pagination, filtering, whitelisted sorting,
rate limiting, structured logging, and a comprehensive automated test suite.

> **v2 note:** This project evolved from a single-user SQLite CRUD service (v1) into a
> multi-user, layered backend. The term *production-oriented* is deliberate — it
> demonstrates production patterns (migrations, auth, clean layering, observability)
> without claiming to be a fully hardened production deployment. See **Known Limitations**.

---

## 1-Minute System Architecture & Data Flow

```mermaid
graph TD
    Client[HTTP Client / Swagger UI / Locust]

    subgraph API [" FastAPI /api/v1 "]
        RL[Rate Limiter - slowapi]
        MW[Request-ID + Logging Middleware]
        Auth[JWT Auth - get_current_user]
        Router[Routers - HTTP only]
    end

    subgraph Service [" Service Layer "]
        TaskSvc[TaskService - OCC, state machine, audit dispatch]
        AuthSvc[AuthService - register, login, token validation]
    end

    subgraph Repo [" Repository Layer "]
        TaskRepo[TaskRepository]
        UserRepo[UserRepository]
        HistRepo[HistoryRepository]
    end

    DB[(PostgreSQL 16 - users, tasks, task_history)]

    Client --> RL --> MW --> Auth --> Router
    Router --> TaskSvc --> TaskRepo --> DB
    Router --> AuthSvc --> UserRepo --> DB
    TaskSvc --> HistRepo --> DB

    Router --> Decision{Result}
    Decision -->|success| OK[2xx]
    Decision -->|version mismatch| E409[409 VERSION_CONFLICT]
    Decision -->|invalid transition| E422[422 INVALID_TRANSITION]
    Decision -->|not owner| E403[403 FORBIDDEN]
    Decision -->|no token| E401[401 UNAUTHORIZED]
```

---

## Key Highlights

- **Multi-user with JWT auth:** Register/login, bcrypt-hashed passwords, stateless JWT
  bearer tokens. Every task is owned by a user; users only see and mutate their own tasks
  (`403` on cross-user access, `404` on nonexistent).
- **Optimistic Concurrency Control (OCC):** Mandatory `version` on updates → `409 Conflict`
  on stale writes. DELETE can be version-guarded too (`?version=N`).
- **Status state machine:** Enforces valid transitions
  (`pending→{in_progress,cancelled}`, `in_progress→{completed,cancelled}`; `completed`/
  `cancelled` terminal). Invalid transitions → `422 INVALID_TRANSITION`.
- **Soft delete + restore + audit history:** Deletes set `deleted_at`; `POST
  /tasks/{id}/restore` brings tasks back; every create/update/delete/restore is recorded
  and queryable via `GET /tasks/{id}/history`.
- **Pagination, filtering, sorting:** Paginated envelope (`items/total/page/page_size/
  pages`); filter by `status`, `priority`, `due_before`, `due_after`; whitelisted sort by
  `created_at`, `due_date`, `title`, `priority`.
- **Priority field:** `low | medium | high | critical` (default `medium`).
- **Structured errors:** Every error is `{"error": {code, message, resource, resource_id}}`.
- **Rate limiting:** slowapi — 100/min per IP (unauthenticated), 300/min per user id.
- **Observability:** JSON structured logs with request_id, latency, user_id; `X-Request-ID`
  response header; `GET /health` + `GET /ready` probes.
- **Migrations:** Alembic manages all schema changes (four migrations to date).
- **Comprehensive tests:** 132 tests via `pytest` + `httpx` with per-test isolated DBs.

---

## Tech Stack & Architecture

- **Language:** Python 3.11+
- **Framework:** FastAPI + Uvicorn (ASGI)
- **Validation:** Pydantic v2 / pydantic-settings
- **Database:** PostgreSQL 16 via SQLAlchemy 2.0 async (asyncpg driver)
- **Migrations:** Alembic (psycopg2 sync driver for the migration runner)
- **Auth:** python-jose (JWT), bcrypt (password hashing)
- **Rate limiting:** slowapi
- **Logging:** structlog (JSON)
- **Testing:** pytest, pytest-asyncio, httpx, aiosqlite (fast in-test DB)
- **Load testing:** Locust
- **CI/CD:** GitHub Actions (Postgres service container), Docker

**Layering:** `routers` (HTTP only) → `services` (business logic) → `repositories`
(SQLAlchemy queries) → `models/orm.py` (mapped classes) → PostgreSQL. No SQL in routers;
no HTTP concerns in repositories.

```
app/
  main.py              lifespan, middleware, router + handler registration
  config.py            pydantic-settings (DATABASE_URL, JWT, rate limits)
  database.py          async engine, AsyncSessionLocal, get_db, Base
  dependencies.py      get_current_user, get_task_service, get_auth_service
  security.py          bcrypt hashing + JWT encode/decode
  rate_limit.py        slowapi limiter + 429 handler
  logging_config.py    structlog JSON setup
  middleware.py        request-id + request logging
  error_handlers.py    HTTPException / validation → ErrorResponse envelope
  models/orm.py        User, Task, TaskHistory
  schemas/             task.py, auth.py, errors.py, history.py
  repositories/        task_repository, user_repository, history_repository
  services/            task_service, auth_service
  routers/             auth, users, tasks, health, legacy_redirects
alembic/versions/      001 initial · 002 users+user_id · 003 deleted_at+history · 004 priority
```

---

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `DATABASE_URL` | Async SQLAlchemy URL | `postgresql+asyncpg://taskuser:taskpass@localhost:5432/taskdb` |
| `SECRET_KEY` | JWT signing secret (**set in production**) | dev placeholder |
| `ALGORITHM` | JWT algorithm | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token TTL | `30` |
| `RATE_LIMIT_ENABLED` | Toggle rate limiting | `true` |
| `RATE_LIMIT_UNAUTHENTICATED` | Per-IP limit | `100/minute` |
| `RATE_LIMIT_AUTHENTICATED` | Per-user limit | `300/minute` |
| `PORT` | Uvicorn bind port | `8000` |

Copy `.env.example` to `.env` and fill in real values. Generate a secret with:
`python -c "import secrets; print(secrets.token_hex(32))"`.

---

## Setup & Running Locally

### Option A — Docker Compose (recommended: Postgres + app together)

```bash
git clone https://github.com/froov30/Task-Tracker-REST-API.git
cd Task-Tracker-REST-API

# Brings up PostgreSQL 16 + the API (runs `alembic upgrade head` then uvicorn)
docker compose up --build
```

The API is then live at `http://127.0.0.1:8000`.

### Option B — Local virtualenv against your own Postgres

```bash
python -m venv venv
source venv/bin/activate            # Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt

cp .env.example .env                # set DATABASE_URL + SECRET_KEY

# Apply migrations, then run the server
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Interactive docs:
- **Swagger UI:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc:** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

### Database migrations (Alembic)

```bash
alembic upgrade head          # apply all migrations
alembic current               # show current revision
alembic downgrade -1          # roll back one migration
alembic revision --autogenerate -m "message"   # after ORM changes
```

---

## API Reference & `curl` Examples

All feature endpoints live under **`/api/v1`** and require a **Bearer token** (except
`/auth/register` and `/auth/login`). Health probes (`/health`, `/ready`) are unversioned
and unauthenticated.

### 0. Register & Login

```bash
# Register
curl -X POST "http://127.0.0.1:8000/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email": "dev@example.com", "password": "supersecret123"}'

# Login (OAuth2 password form — note -F, username carries the email)
curl -X POST "http://127.0.0.1:8000/api/v1/auth/login" \
  -F "username=dev@example.com" \
  -F "password=supersecret123"
# → {"access_token": "eyJhbGci...", "token_type": "bearer"}

# Save the token for reuse
TOKEN="eyJhbGci..."
```

Fetch the current user:

```bash
curl "http://127.0.0.1:8000/api/v1/users/me" \
  -H "Authorization: Bearer $TOKEN"
```

### 1. Create Task (`POST /api/v1/tasks`)

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/tasks" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Ship v2 docs",
    "description": "Refresh README for the v2 API",
    "due_date": "2026-09-30",
    "priority": "high"
  }'
```

**Response (`201 Created`):**
```json
{
  "id": 1,
  "title": "Ship v2 docs",
  "description": "Refresh README for the v2 API",
  "status": "pending",
  "due_date": "2026-09-30",
  "created_at": "2026-09-09T07:30:00+00:00",
  "updated_at": "2026-09-09T07:30:00+00:00",
  "version": 1,
  "priority": "high",
  "user_id": 1
}
```

### 2. List Tasks — paginated (`GET /api/v1/tasks`)

Query params: `status`, `priority`, `due_before`, `due_after`,
`sort_by` (`created_at`|`due_date`|`title`|`priority`), `sort_order` (`asc`|`desc`),
`page` (≥1), `page_size` (1–100), `include_deleted` (bool).

```bash
curl "http://127.0.0.1:8000/api/v1/tasks?priority=high&sort_by=due_date&sort_order=asc&page=1&page_size=20" \
  -H "Authorization: Bearer $TOKEN"
```

**Response (`200 OK`):**
```json
{
  "items": [ { "id": 1, "title": "Ship v2 docs", "priority": "high", "...": "..." } ],
  "total": 1,
  "page": 1,
  "page_size": 20,
  "pages": 1
}
```

### 3. Get Single Task (`GET /api/v1/tasks/{id}`)

```bash
curl "http://127.0.0.1:8000/api/v1/tasks/1" -H "Authorization: Bearer $TOKEN"
```

### 4. Update Task with OCC + state machine (`PUT /api/v1/tasks/{id}`)

`version` is required. Status changes are validated against the state machine.

```bash
curl -X PUT "http://127.0.0.1:8000/api/v1/tasks/1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "in_progress", "version": 1}'
```

**Stale version → `409 Conflict`:**
```json
{ "error": { "code": "VERSION_CONFLICT", "message": "version mismatch, re-fetch and retry", "resource": "task", "resource_id": 1 } }
```

**Invalid transition (e.g. pending → completed) → `422`:**
```json
{ "error": { "code": "INVALID_TRANSITION", "message": "Cannot transition task from 'pending' to 'completed'", "resource": "task", "resource_id": null } }
```

### 5. Delete Task (`DELETE /api/v1/tasks/{id}`)

Soft delete. Optionally version-guarded with `?version=N` (→ `409` on stale version).

```bash
# Unconditional soft delete
curl -X DELETE "http://127.0.0.1:8000/api/v1/tasks/1" -H "Authorization: Bearer $TOKEN"

# Version-guarded soft delete
curl -X DELETE "http://127.0.0.1:8000/api/v1/tasks/1?version=2" -H "Authorization: Bearer $TOKEN"
```

**Response (`204 No Content`)**

### 6. Restore a soft-deleted task (`POST /api/v1/tasks/{id}/restore`)

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/tasks/1/restore" -H "Authorization: Bearer $TOKEN"
```

### 7. Task audit history (`GET /api/v1/tasks/{id}/history`)

```bash
curl "http://127.0.0.1:8000/api/v1/tasks/1/history" -H "Authorization: Bearer $TOKEN"
# → [ {action: "created", ...}, {action: "updated", ...}, {action: "deleted", ...}, {action: "restored", ...} ]
```

### Health & readiness (unversioned, no auth)

```bash
curl "http://127.0.0.1:8000/health"   # {"status":"ok","database":"connected"}
curl "http://127.0.0.1:8000/ready"
```

---

## Running Automated Tests

```bash
pytest tests/ -v
```

Covers CRUD, pagination, filtering/sorting, OCC 409s, validation 422s, auth flow,
ownership isolation, the status state machine, structured errors, soft delete + restore,
audit history, priority, API versioning + legacy redirects, rate limiting, and structured
logging. Tests run against an isolated per-test SQLite database (via `aiosqlite`) for
speed; CI additionally applies all Alembic migrations against a real PostgreSQL 16 service
container.

---

## Load Testing & Performance

Two Locust scenarios (`locustfile.py`) — concurrent-write contention (OCC) and mixed
read/write ramp — both authenticate per simulated user and hit `/api/v1`. See
[`docs/LOAD_TESTING.md`](docs/LOAD_TESTING.md) for the v1 (SQLite) baseline and the v2
(PostgreSQL) methodology and comparison.

```bash
docker compose up -d
locust -f locustfile.py MixedLoadUser --headless --host http://127.0.0.1:8000 \
    --users 50 --spawn-rate 10 --run-time 60s --csv results/pg_mixed_50
```

---

## Known Limitations

- **No RBAC / roles:** All authenticated users have the same capabilities over their own
  tasks. `include_deleted` is available to any authenticated user (would be admin-gated
  under an RBAC model).
- **Rate limiter is per-process:** slowapi's default in-memory store means a multi-worker
  or multi-instance deployment needs a shared backend (e.g. Redis) for a truly global
  limit.
- **JWTs are not revocable before expiry:** No token denylist; logout is client-side.
  Mitigated by a short default TTL (30 min).
- **Single-region, single-instance assumptions:** No horizontal-scaling or read-replica
  configuration is included.
- **History grows unbounded:** `task_history` has no retention/archival policy yet.

Full decision history — including the PostgreSQL migration, JWT choice, service/repository
pattern, soft delete, and audit history — is logged in [`docs/DECISIONS.md`](docs/DECISIONS.md).
