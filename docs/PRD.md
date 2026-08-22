# PRD — Task Tracker REST API

## 1. Summary
A backend-only REST API that lets a client (script, frontend, or API consumer like Postman)
manage the full lifecycle of a "task" — create, read, update, delete, and list — with
persistent storage, safe filtering/sorting, and conflict-safe concurrent updates. Built to
demonstrate clean API design, request/response validation, real-world backend hardening,
and a containerized, cloud-deployed, version-controlled Python service.

## 2. Problem Statement
Individuals and small teams need a lightweight way to track discrete units of work
(tasks) without the overhead of a full project-management tool. There's no need for
multi-user auth, teams, or notifications — just a reliable, well-documented CRUD service
that models a task's lifecycle from creation to completion, handles concurrent edits
safely, and lets clients query the data they need without unsafe query construction.

## 3. Goals
- Provide a complete CRUD REST API for tasks (5 endpoints minimum).
- Enforce input/output validation so bad data never reaches storage.
- Persist data across restarts (SQLite file, not in-memory).
- Support combined filtering (status, due-date range) and sorting on task listings,
  using a safe (whitelisted) query-construction pattern.
- Prevent silent data loss on concurrent updates via optimistic concurrency control.
- Keep the codebase cleanly separated (routes / schemas / models) so it's easy to
  extend or hand off.
- Maintain mandatory automated test coverage for CRUD, filtering/sorting, concurrency
  conflicts, and validation edge cases — not optional, not a stretch goal.
- Validate real concurrent-request behavior via load testing rather than assuming
  correctness from unit tests alone — find the actual point where the system's
  performance degrades or errors appear, and let that evidence (not guesswork)
  determine whether SQLite is sufficient or a database migration is warranted.
- Ship a containerized (Docker), publicly reachable deployment (Azure App Service for
  Containers) with a CI pipeline (GitHub Actions) that lints and runs the test suite on
  every push.
- Demonstrate incremental, meaningful Git history (not one giant commit).

## 4. Non-Goals (Out of Scope)
- User authentication / authorization / multi-tenancy.
- Task assignment to specific users.
- Notifications, reminders, or scheduling.
- A frontend UI (API only; Swagger/OpenAPI docs count as the "UI").
- Horizontal scaling, caching layer, or message-queue-based background processing.
- Pagination of list results (deferred; see "Deferred Features" below).
- Background/scheduled job processing, e.g. auto-flagging overdue tasks (deferred).
- Migrating off SQLite (acceptable for this project's scale).

## 5. Deferred Features (explicitly out of scope for this version, not forgotten)
- **Pagination** (`limit`/`offset` + envelope response) — real value, but additive and
  low-risk to bolt on later; cut to protect time for higher-signal work.
- **Background job (auto-flag overdue tasks)** — demonstrates a real pattern (scheduled
  work outside the request/response cycle) but adds the most surface area to defend
  (scheduler lifecycle, new dependency) relative to what it proves. Revisit if time
  remains after all mandatory work is done.
- **PostgreSQL migration — conditional, not pre-decided.** SQLite is the default for
  this version (see DECISIONS.md #3). Whether this project migrates to PostgreSQL is
  determined by Phase 7's load-test results, not decided in advance: if load testing
  finds SQLite's single-writer lock becomes a real bottleneck at realistic concurrency,
  migration becomes the next priority; if it doesn't, SQLite stays and the finding
  itself becomes the documented evidence. Either outcome is a valid, defensible result
  — the goal is evidence-driven judgment, not "using Postgres" as a checkbox.

## 6. Target User / Use Case
A developer or small-scale user who wants to:
- Programmatically create a task with a title/description.
- Move it through a lifecycle: `pending` → `in_progress` → `completed` (or `cancelled`).
- List, filter (by status, due-date range), and sort tasks safely.
- Update a task without silently clobbering someone else's concurrent change.
- Delete a task as priorities change.

## 7. Core Feature Requirements

| # | Feature | Description |
|---|---------|--------------|
| 1 | Create Task | Client submits title (required), description (optional), due_date (optional). Server assigns id, status=`pending`, version=1, timestamps. |
| 2 | List Tasks | Return all tasks; support combinable filters (`status`, `due_before`, `due_after`) and whitelisted sorting (`sort_by`, `sort_order`). |
| 3 | Get Task by ID | Return a single task or 404. |
| 4 | Update Task | Partial update of title/description/status/due_date; requires the caller's last-known `version`; returns 409 on version mismatch instead of silently overwriting. |
| 5 | Delete Task | Remove a task by ID; 404 if not found. |

This covers the "full task lifecycle across 5 endpoints" requirement — the API surface
stays at exactly 5 routes; all new capability is expressed as query params, request
fields, and response fields, not new endpoints.

## 8. Task Lifecycle (State Model)
```
pending → in_progress → completed
   \-----------> cancelled <----/
```
- New tasks always start as `pending`.
- Any state can transition to `cancelled`.
- `completed` and `cancelled` are terminal in this version (no re-opening — kept simple
  intentionally; see DECISIONS.md #4).

## 9. Success Criteria
- All 5 endpoints functional, validated, and documented.
- Invalid input (e.g., missing title, bad status value, out-of-range query param)
  returns `422` with a clear error body — never a 500.
- Concurrent updates against a stale `version` return `409`, never silently overwrite.
- Sort/filter query params cannot be used to inject arbitrary SQL (whitelist-verified).
- Full automated test suite passes (CRUD, filtering/sorting, concurrency, validation
  edge cases) before deployment.
- Data survives a server restart (SQLite file persists within the container's runtime).
- API is containerized, deployed live on Azure App Service, and reachable via
  curl/Postman.
- CI pipeline (GitHub Actions) runs lint + full test suite on every push.
- Load testing produces real, documented throughput/latency/error-rate numbers at
  increasing concurrency, with the actual bottleneck point identified — not a
  theoretical claim about scalability, a measured one.
- README lets a new developer clone, install, run, and hit every endpoint in under
  5 minutes — locally or via Docker.
- Git log shows a logical, incremental progression (setup → models → schemas → routes →
  hardening → tests → docs → containerize → deploy → CI), not a single squashed commit.

## 10. Constraints
- Language/framework fixed: Python + FastAPI (per project brief).
- Storage fixed: SQLite (per project brief).
- Single deployable service, containerized with Docker, no external infra dependencies
  beyond Azure App Service and GitHub Actions.

## 11. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| SQLite file is ephemeral inside a container/App Service instance unless a persistent volume/mount is configured | Documented explicitly in README as a known limitation; acceptable for a demo project. Revisit with an Azure Files mount only if time allows — not required for the core demonstration. |
| Concurrent write conflicts on SQLite | Data-loss risk mitigated via optimistic concurrency control (`version` field, `409` on mismatch) — see DECISIONS.md #9. Throughput/lock-contention risk is measured directly via Phase 7 load testing rather than assumed; see docs/LOAD_TESTING.md once run. |
| Unsafe dynamic query construction from user-controlled `sort_by`/filter params | Mitigated via a whitelist map from API-facing sort values to real column names; filters use parameterized queries — see DECISIONS.md #8. |
| Scope creep (auth, users, pagination, background jobs, etc.) | Explicitly listed as Non-Goals / Deferred Features above. |
