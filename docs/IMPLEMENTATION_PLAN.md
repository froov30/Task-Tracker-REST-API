# Implementation Plan — Task Tracker REST API

Each phase below maps to one or more **incremental Git commits**, so the history tells
the story of the build (satisfies the "version-controlled through incremental commits"
requirement). Depth features (filtering/sorting, optimistic concurrency, mandatory
tests) and infrastructure (Docker, Azure, CI) are merged directly into the phases below
— built once, correctly, rather than as a bare CRUD pass followed by a rework pass.

## Phase 0 — Project Setup
- [ ] `git init`, create repo on GitHub, connect remote
- [ ] Create folder structure (see ARCHITECTURE.md)
- [ ] `python -m venv venv`, activate
- [ ] `requirements.txt`: `fastapi`, `uvicorn[standard]`, `pydantic`
- [ ] `.gitignore`: `venv/`, `__pycache__/`, `tasks.db`, `.env`
- **Commit 1:** `chore: initial project scaffold + dependencies`

## Phase 1 — Database Layer
- [ ] `app/database.py`: connection helper (`get_connection()`), `init_db()` that
      creates the `tasks` table if it doesn't exist — **including the `version`
      column from the start** (`INTEGER NOT NULL DEFAULT 1`)
- [ ] Manually verify table creation with a throwaway script
- **Commit 2:** `feat: add SQLite connection and schema initialization with version column`

## Phase 2 — Schemas (Pydantic)
- [ ] `app/schemas/task.py`: `TaskStatus` enum, `SortBy` / `SortOrder` literals,
      `TaskCreate`, `TaskUpdate` (all fields optional **except `version: int`,
      required**), `TaskOut` (includes `version`)
- [ ] Add field validation (title min length, etc.)
- **Commit 3:** `feat: define Pydantic schemas including sort literals and required version field`

## Phase 3 — Data-Access Layer (Models)
- [ ] `app/models/task.py`:
  - `create_task` — inserts with `version=1`
  - `get_all_tasks(status, due_before, due_after, sort_by, sort_order)` — builds a
    dynamic `WHERE` clause from whichever filters are non-`None` (parameterized), plus
    an `ORDER BY` built from a **whitelist map** (`SORT_COLUMNS`), never from raw
    string interpolation
  - `get_task_by_id`
  - `update_task(task_id, data, version)` — runs
    `UPDATE tasks SET ..., version = version + 1 WHERE id = ? AND version = ?`;
    inspects affected row count and returns one of three outcomes: not-found sentinel,
    version-conflict sentinel, or the updated row
  - `delete_task`
- [ ] Each function opens its own connection, commits, closes (or uses a context manager)
- **Commit 4:** `feat: implement CRUD, whitelisted filtering/sorting, and version-checked update`

## Phase 4 — Routers (API Layer)
- [ ] `app/routers/tasks.py`: wire all 5 endpoints to model functions
- [ ] `GET /tasks`: new `Query()` params for `status`, `due_before`, `due_after`,
      `sort_by`, `sort_order` — all optional, all FastAPI-validated (so an invalid
      `sort_by` value 422s before ever reaching `models/task.py`)
- [ ] `PUT /tasks/{id}`: explicit three-way branch on the model layer's return value —
      `404` (no such id), `409` (version mismatch), `200` (success) — written out
      explicitly, not collapsed into a single condition
- [ ] Correct status codes throughout (`201`, `200`, `204`, `404`, `409`, `422`)
- [ ] `app/main.py`: instantiate `FastAPI()`, register router, `@app.on_event("startup")`
      → `init_db()`
- [ ] Manually test every endpoint, including a deliberate version-conflict case, via
      `/docs`
- **Commit 5:** `feat: implement 5 REST endpoints with filtering, sorting, and optimistic concurrency`

## Phase 5 — Error Handling & Edge Cases
- [ ] 404 handling on GET/PUT/DELETE for missing IDs
- [ ] Reject invalid `status`/`sort_by`/`sort_order` values (enum/literal handles this
      automatically — verify)
- [ ] Confirm empty-body `PUT` (aside from required `version`) doesn't wipe existing
      fields (partial update check)
- [ ] Confirm a stale-version `PUT` returns `409` and leaves the row unmodified
- [ ] Confirm `sort_by` cannot be used to inject arbitrary SQL — manually attempt an
      invalid value and confirm it 422s before reaching the model layer
- **Commit 6:** `fix: harden error handling for not-found, version conflict, and invalid input`

## Phase 6 — Automated Tests (Mandatory Gate)
No phase after this one proceeds until this suite passes — see TRD.md §7.
- [ ] `requirements.txt`: add `pytest`, `httpx`
- [ ] `tests/test_tasks.py` (pytest + FastAPI `TestClient`) covering:
  - CRUD happy path: create → get → update → delete → 404-after-delete
  - Filtering + sorting: combined filters return correct subset; sort order verified
  - Concurrency conflict: stale-version update returns 409
  - Validation edge cases: missing `title`, invalid `status`, invalid `sort_by`,
    missing `version` on `PUT` — all 422
- **Commit 7:** `test: add mandatory coverage for CRUD, filtering, sorting, and concurrency`

## Phase 7 — Load Testing & Scalability Baseline
Run only after Phase 6 is green. Full requirements in TRD.md §7.5 — this phase
measures real behavior, it doesn't replace correctness testing.
- [ ] `requirements.txt` (or a separate `requirements-dev.txt`): add `locust`
- [ ] `locustfile.py`: define the two required scenarios — concurrent writes to the
      same task (exercises DECISIONS.md #9's 409 handling under real contention), and
      mixed read/write load ramping from 10 → 50 → 200 concurrent users
- [ ] Run locally against SQLite; capture requests/sec, latency (p50/p95/p99), and
      error rate at each concurrency level
- [ ] Identify the actual point where errors or SQLite locking first appears — this is
      the number that matters, not a vague "it handled load fine"
- [ ] Write `docs/LOAD_TESTING.md` documenting the real results
- [ ] **Decision gate:** based on the results, either (a) proceed with SQLite and log
      the documented ceiling as the honest finding, or (b) migrate to PostgreSQL before
      Phase 9 — see PRD.md §5 and TRD.md §7.5. Log whichever happens as a new
      DECISIONS.md entry with the actual numbers behind it, not a generic justification.
- **Commit 8:** `test: add Locust load test harness and document baseline scalability results`
  (plus, if migration happens: `feat: migrate from SQLite to PostgreSQL based on load-test findings`)

## Phase 8 — Documentation
- [ ] `README.md`:
  - Project description
  - Setup instructions (local venv **and** Docker, plus Postgres via
    `docker-compose.yml` if Phase 7 triggered migration)
  - Environment variables
  - Endpoint reference with `curl` examples for all 5 endpoints, including a worked
    `409` conflict example
  - Link to live Azure deployment + `/docs`
  - Summary of load-testing results with a link to `docs/LOAD_TESTING.md`
  - Known limitation: SQLite is ephemeral per container instance unless a persistent
    volume is mounted (drop this note if Phase 7 triggered a Postgres migration)
- **Commit 9:** `docs: add README with setup, endpoint reference, and load-test summary`

## Phase 9 — Containerization (Docker)
- [ ] `Dockerfile`: `python:3.11-slim` base, copy `app/` + `requirements.txt`,
      `pip install`, `CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- [ ] `.dockerignore`: `venv/`, `__pycache__/`, `tasks.db`, `.env`, `tests/`
- [ ] If Phase 7 triggered a PostgreSQL migration: `docker-compose.yml` with an `app`
      service and a `postgres` service, for local dev parity with the deployed target
- [ ] Build locally (`docker build`), run locally (`docker run` or `docker compose up`),
      verify all 5 endpoints via `/docs` inside the container
- **Commit 10:** `chore: add Dockerfile and containerize the application`

## Phase 10 — Cloud Deployment (Azure App Service for Containers)
- [ ] Push built image to a container registry (Azure Container Registry or Docker Hub)
- [ ] Configure Azure App Service for Containers to pull and run the image
- [ ] Set `PORT` and `DATABASE_PATH`/`DATABASE_URL` as App Service environment variables
- [ ] If migrated: provision Azure Database for PostgreSQL (Flexible Server), connect
      App Service to it
- [ ] Deploy, verify live `/docs` and all 5 endpoints via the public Azure URL
- [ ] **Re-run the Phase 7 load test against the live Azure URL**, not just locally —
      capture a second set of numbers reflecting real network/infra conditions; add
      this second data set to `docs/LOAD_TESTING.md`
- [ ] Update README with the live URL
- **Commit 11:** `chore: add Azure App Service deployment config` → **Commit 12:** `docs: add live deployment URL and Azure load-test results`

## Phase 11 — CI Pipeline (GitHub Actions)
- [ ] `.github/workflows/ci.yml`: on every push — install dependencies, run lint, run
      the full pytest suite from Phase 6
- [ ] If migrated to PostgreSQL: workflow spins up a Postgres service container so
      tests run against the same engine as production, not SQLite standing in for it
- [ ] Confirm a deliberately broken test fails the pipeline (sanity check that CI is
      actually gating, not just running)
- **Commit 13:** `ci: add GitHub Actions pipeline for lint and test on push`

## Phase 12 — Doc Sync
- [ ] Confirm TRD.md, ARCHITECTURE.md, and README.md all reflect the final database
      choice (SQLite or PostgreSQL), deployment reality (Docker + Azure + CI), and
      load-testing results (no stale references to Render or to unvalidated
      scalability claims)
- [ ] Confirm DECISIONS.md and FLOW.md are up to date (see those files)
- **Commit 14:** `docs: final sync of TRD, architecture, and README with deployment and load-test reality`

## Definition of Done
- All 5 endpoints live and documented, both locally and on Azure.
- Clean separation maintained: no SQL in routers, no HTTP in models, no raw string
  interpolation in `ORDER BY`.
- Filtering, sorting, and optimistic concurrency all functioning and tested.
- Mandatory test suite passes locally and in CI.
- Load testing has produced real, documented numbers — locally and against the live
  Azure deployment — with an explicit, evidence-based decision on SQLite vs. PostgreSQL.
- Git log shows ≥13 meaningful, scoped commits (not one squash).
- DECISIONS.md and FLOW.md kept up to date as changes are made (see those files).
