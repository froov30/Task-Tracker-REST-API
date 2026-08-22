# FLOW.md

Documents how a request actually travels through the codebase — which file calls which
function, in what order — and tracks which part of that path is currently being built or
modified. Update this file every time execution flow changes (new endpoint, new layer,
refactor).

**Status key:** ✅ implemented · 🚧 being modified right now · ⬜ not yet built

---

## 0. Current Build Position
> Update this section every session — it's the single source of truth for "what part
> of the path am I touching right now."

**Currently modifying:** Nothing — Phase 0 scaffold is complete. Next step per
IMPLEMENTATION_PLAN.md is **Phase 1: database layer**.
**Last completed phase:** Phase 0 (project setup).
**Files touched in the most recent change:** `.gitignore`, `requirements.txt`,
`app/__init__.py`, `app/models/__init__.py`, `app/schemas/__init__.py`,
`app/routers/__init__.py`, `tests/.gitkeep`.
**Note:** This revision of FLOW.md merges the filtering/sorting and optimistic
concurrency flows directly into the base diagrams below, adds the deployment flow
(Docker/Azure/CI) that didn't exist in the original plan, and adds a load-testing flow
(new Phase 7, before Docker/Azure) that determines whether the deployment flow targets
SQLite or PostgreSQL. Request-flow status markers stay ⬜ until those layers exist
(Phase 1+); Phase 0 only created packages and tooling.

---

## 1. Startup Flow (app boot)

```
uvicorn app.main:app          (locally, or as the container's CMD)
        │
        ▼
app/main.py
        │  FastAPI() instance created
        │  app.include_router(tasks_router, prefix="/tasks")
        │  @app.on_event("startup") registered
        ▼
  [on startup event fires]
        │
        ▼
app/database.py :: init_db()
        │  opens sqlite3 connection to DATABASE_PATH
        │  executes CREATE TABLE IF NOT EXISTS tasks (..., version INTEGER NOT NULL DEFAULT 1)
        │  commits, closes connection
        ▼
  App ready, listening on $PORT
```
Status: ⬜ not yet built (Phase 0–1)
Note: identical whether run via `uvicorn` directly or inside Docker/Azure — the
container just wraps this same startup sequence, it doesn't change it.

---

## 2. Request Flow — `POST /tasks` (Create)

```
Client
  │  POST /tasks  { "title": "...", "description": "..." }
  ▼
app/main.py                (routes to included router)
  ▼
app/routers/tasks.py :: create_task(payload: TaskCreate)
  │  1. FastAPI parses+validates body against schemas/task.py::TaskCreate
  │     (fails here -> automatic 422, never reaches step 2)
  │  2. calls models/task.py :: create_task(payload.model_dump())
  ▼
app/models/task.py :: create_task(data: dict)
  │  1. opens connection via database.py :: get_connection()
  │  2. INSERT INTO tasks (..., version) VALUES (..., 1)
  │  3. commits
  │  4. SELECT the just-created row by lastrowid
  │  5. returns row as dict (includes version=1)
  ▼
app/routers/tasks.py :: create_task (continued)
  │  wraps dict in schemas/task.py :: TaskOut
  │  returns TaskOut, status_code=201
  ▼
Client receives 201 + JSON body (includes "version": 1)
```
Status: ⬜ not yet built (Phase 3–4)

---

## 3. Request Flow — `GET /tasks` (List, with filtering + sorting)

```
Client
  │  GET /tasks?status=pending&due_before=2026-09-01&sort_by=due_date&sort_order=asc
  ▼
app/routers/tasks.py :: list_tasks(status, due_before, due_after, sort_by, sort_order)
  │  FastAPI validates each param against its enum/Literal type
  │     (invalid sort_by/sort_order/status -> automatic 422, never reaches models/task.py)
  │  calls models/task.py :: get_all_tasks(status, due_before, due_after, sort_by, sort_order)
  ▼
app/models/task.py :: get_all_tasks(...)
  │  1. builds WHERE clause from whichever filters are non-None, using ? placeholders
  │     (parameterized — never string-interpolated)
  │  2. maps sort_by through SORT_COLUMNS whitelist dict -> real column name
  │     (sort_by is already Literal-validated by FastAPI, so this lookup cannot KeyError)
  │  3. SELECT * FROM tasks [WHERE ...] ORDER BY <whitelisted column> <sort_order>
  │  4. returns list[dict]
  ▼
app/routers/tasks.py :: list_tasks (continued)
  │  maps list[dict] -> list[TaskOut]
  ▼
Client receives 200 + JSON array, correctly filtered and ordered
```
Status: ⬜ not yet built (Phase 3–4)

---

## 4. Request Flow — `GET /tasks/{id}` (Read one)

```
Client -> routers/tasks.py :: get_task(task_id)
             -> models/task.py :: get_task_by_id(task_id)
                  -> SELECT * FROM tasks WHERE id = ?
             <- None -> raise HTTPException(404)
             <- dict -> wrap as TaskOut (includes version) -> 200
```
Status: ⬜ not yet built (Phase 3–4)

---

## 5. Request Flow — `PUT /tasks/{id}` (Update, version-checked)

```
Client -> routers/tasks.py :: update_task(task_id, payload: TaskUpdate)
             │  FastAPI validates payload; version is REQUIRED, missing -> 422
             -> models/task.py :: update_task(task_id, payload.model_dump(exclude_unset=True), payload.version)
                  -> UPDATE tasks SET ..., version = version + 1
                     WHERE id = ? AND version = ?
                  -> inspect rows-affected count:
                       0 rows AND no task with this id exists  -> return NOT_FOUND sentinel
                       0 rows BUT task exists (version mismatch) -> return VERSION_CONFLICT sentinel
                       1 row -> re-SELECT updated row, return it
             <- NOT_FOUND         -> raise HTTPException(404)
             <- VERSION_CONFLICT  -> raise HTTPException(409, "version mismatch, re-fetch and retry")
             <- dict              -> wrap as TaskOut (incremented version) -> 200
```
Status: ⬜ not yet built (Phase 3–4)
Note: this is the flow most likely to come up verbally in a technical interview — the
three-way branch (404 / 409 / 200) is intentionally written out explicitly in
`routers/tasks.py` rather than collapsed, so it's easy to point to and explain.

---

## 6. Request Flow — `DELETE /tasks/{id}`

```
Client -> routers/tasks.py :: delete_task(task_id)
             -> models/task.py :: get_task_by_id(task_id)   # existence check
             <- None -> raise HTTPException(404)
             <- exists ->
             -> models/task.py :: delete_task(task_id)
                  -> DELETE FROM tasks WHERE id = ?
             <- 204 No Content
```
Status: ⬜ not yet built (Phase 3–4)
Unchanged from the base plan — delete was never touched by the depth-upgrade features.

---

## 7. Cross-Cutting: Validation Error Path

```
Any endpoint, malformed body or query param
  │
  ▼
FastAPI/Pydantic intercepts BEFORE route function body executes
  │  (routers/tasks.py handler code never runs)
  ▼
Automatic 422 response: { "detail": [ { "loc": [...], "msg": "...", "type": "..." } ] }
```
This path never touches `models/task.py` or `database.py` — validation failures
(including invalid `sort_by`, invalid `status`, missing `version`) are fully contained
in the schema layer, by design (see ARCHITECTURE.md §1, DECISIONS.md #5, #8).

---

## 8. Load Testing Flow (new — Phase 7)

```
locustfile.py, run against a running instance (local first, then live Azure in Phase 10)
        │
        ▼
Scenario A — concurrent writes to the same task
  N simulated users -> PUT /tasks/{same_id} simultaneously, each with the version
  they last read
        │
        ▼
Expected: some requests succeed (200, version incremented), the rest receive 409
  (their version is now stale) — this is the SAME flow as Section 5 above, just
  triggered under real concurrency instead of a single manual test case
        │
        ▼
Scenario B — mixed read/write load, ramping concurrency (10 -> 50 -> 200 users)
  Requests spread across POST /tasks, GET /tasks (with filters/sort), PUT /tasks/{id}
        │
        ▼
Observed at increasing concurrency: requests/sec, latency (p50/p95/p99), error rate
  │  SQLite's single-writer lock is expected to become visible at some concurrency
  │  level (rising latency and/or "database is locked" errors) — the load test's job
  │  is to find that point, not to avoid it
        ▼
Results written to docs/LOAD_TESTING.md; feeds the decision gate in
IMPLEMENTATION_PLAN.md Phase 7 (stay on SQLite with a documented ceiling, or migrate
to PostgreSQL before Phase 9)
```
Status: ⬜ not yet built (Phase 7)
Note: this flow deliberately reuses Scenario A to validate the PUT /tasks/{id} flow
from Section 5 under real concurrency — it's a stress test of an existing flow, not a
new code path.

---

## 9. Deployment Flow (Docker + Azure + CI)

```
git push
  │
  ▼
GitHub Actions (.github/workflows/ci.yml)
  │  install deps -> lint -> run tests/test_tasks.py (Phase 6 suite)
  │  [if migrated to PostgreSQL: spin up a Postgres service container first, so tests
  │   run against the same engine as production]
  │  red suite -> pipeline fails, nothing deploys
  ▼
[on green, manual/triggered step]
  │
  ▼
docker build -> image pushed to registry (ACR / Docker Hub)
  │  [if migrated: docker-compose.yml also defines a postgres service for local dev
  │   parity with the deployed target]
  ▼
Azure App Service for Containers pulls + runs image
  │  same app/main.py startup flow as Section 1 above — containerization changes
  │  how the process is launched, not what it does on boot
  │  [if migrated: connects to Azure Database for PostgreSQL instead of a local
  │   SQLite file]
  ▼
Public Azure URL serving /docs and /tasks
  │
  ▼
Phase 7's load test re-run against this live URL (Section 8 above), second data set
added to docs/LOAD_TESTING.md
```
Status: ⬜ not yet built (Phase 9–11)
Note: this section did not exist in the original FLOW.md — added because Docker/Azure/CI
are now part of the merged plan, not a separate retrofit. The database branch
(SQLite vs. PostgreSQL) is resolved by Phase 7's results before this flow is built, not
guessed at in advance.

---

## 10. Deferred (Not in This Version)
- **Pagination flow** for `GET /tasks` (envelope response, `limit`/`offset`) —
  deferred per PRD.md §5. No diagram here until it's un-deferred.
- **Background job flow** (scheduled overdue-checker running independently of any
  client request) — deferred per PRD.md §5. No diagram here until it's un-deferred.

---

## 11. Change Log (append here every time flow changes)

| Date | Change | Files affected | Reason |
|------|--------|-----------------|--------|
| 2026-08-22 | Phase 0 scaffold: layered `app/` packages and `tests/` exist on disk; no request path yet | `.gitignore`, `requirements.txt`, `app/**/__init__.py`, `tests/.gitkeep` | IMPLEMENTATION_PLAN.md Phase 0 — folder structure and deps before any runtime code |
| — | Initial flow drafted (pre-code) | N/A | Planning stage, mirrors ARCHITECTURE.md + IMPLEMENTATION_PLAN.md |
| — | Merged filtering/sorting, optimistic concurrency, and deployment flow into base diagrams; removed pagination/background-job flows to Deferred section | FLOW.md only | Depth-upgrade plan reviewed and trimmed; Docker/Azure retrofit folded into the same plan-only pass rather than a later rework |
| — | Added Load Testing Flow (§8) between the request flows and the Deployment Flow; marked the deployment flow's database target as conditional on load-test results | FLOW.md only | Load testing was decided to happen mid-build (after Phase 6, before Docker/Azure) so infra isn't built around an unvalidated database choice |

> When actual coding begins, replace the ⬜ statuses above with ✅ as each flow is
> implemented, and add a row here for every meaningful change (new endpoint, refactor,
> bug fix that alters call order, etc.) describing exactly which function/file changed
> and why.
