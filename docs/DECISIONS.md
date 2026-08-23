# DECISIONS.md

Living log of every meaningful decision made while designing/building this project,
and the reasoning behind it. Newest entries at the top. Every entry that later gets
reversed should be marked **[SUPERSEDED by #N]** rather than deleted, so the history of
reasoning stays intact.

Format for each entry:
```
## #N — <short title>
Date/Phase:
Decision:
Reasoning:
Alternatives considered:
Trade-off accepted:
```

**Note on what's coming (not yet decided):** Phase 7 (Load Testing) will produce a
new entry — either "SQLite retained, documented ceiling at N concurrent writes" or
"Migrated to PostgreSQL following load-test findings" — logged with the actual
numbers from `docs/LOAD_TESTING.md`, not written in advance. That entry will be
numbered after whatever has already been logged by then (currently #17).

---

## #17 — Title `min_length=1` with whitespace stripped; `version >= 1`
Date/Phase: Phase 2 (Schemas)
Decision: `title` on create (and on update when present) is
`StringConstraints(strip_whitespace=True, min_length=1)`. `TaskUpdate.version` is
required `int` with `Field(ge=1)`. Sort types are `Literal`s with no defaults on
the schema objects themselves — defaults stay on the FastAPI `Query()` params in
Phase 4.
Reasoning: IMPLEMENTATION_PLAN.md says "Add field validation (title min length,
etc.)" but TRD never names the number. Without `min_length=1`, `title: ""` would
be a valid `str` and we'd persist empty tasks; the 422-on-missing-title test in
Phase 6 wouldn't catch that. I tried a plain `min_length=1` first in a scratch
check — `"   "` has length 3, so it would sneak through. Strip-then-min-length
is the actual rule I wanted. `ge=1` on version is because stored versions start
at 1 (DECISIONS.md #9); `version: 0` can't be a last-read value, so fail at
validation instead of looking like a 409. I did not put `sort_by`/`sort_order`
defaults on the Literal aliases — those aren't fields on a body model, and
duplicating defaults here plus on `Query()` is how they drift.
Alternatives considered: Leave title as unconstrained `str` (what TRD's field
list literally shows). Rejected — empty titles are junk data. A max-length cap
— not in the spec, so I didn't invent one.
Trade-off accepted: Whitespace-only titles 422, which is slightly stricter than
"missing title" in the TRD examples. Fine.

---

## #16 — `sqlite3.Row` on every connection from `get_connection()`
Date/Phase: Phase 1 (Database Layer)
Decision: `get_connection()` sets `conn.row_factory = sqlite3.Row` before returning
the connection. `init_db()` goes through that helper rather than calling
`sqlite3.connect` a second way.
Reasoning: FLOW.md already says the model layer returns `dict`s to the router.
`sqlite3.Row` is the stdlib way to get named columns (`row["version"]`) instead of
tuple indexes, which would be a mess the first time we add/reorder a column. I
almost left the default tuple factory "until Phase 3 needs it," then realized
`init_db()` verification (`PRAGMA table_info`) is nicer with named fields too, and
one connection helper means Phase 3 can't accidentally open a tuple-mode connection
and break `dict(row)`. No WAL, no `check_same_thread=False` — those would change
locking behavior that Phase 7 is supposed to measure.
Alternatives considered: Keep the default tuple row factory and index columns by
position in `models/task.py`. Workable, worse to read. A custom dict factory —
unnecessary, `sqlite3.Row` already maps to `dict(row)`.
Trade-off accepted: Callers must treat rows as `Row`/`dict`, not tuples. That's
the point.

---

## #15 — Point origin at the existing empty GitHub repo, don't create a second one
Date/Phase: Phase 0 (Project Setup)
Decision: `git init` locally and set `origin` to
`https://github.com/froov30/Task-Tracker-REST-API.git` (already existed, empty,
private). Do not run `gh repo create` for a new name like `task-tracker-api`.
Reasoning: IMPLEMENTATION_PLAN.md Phase 0 says "create repo on GitHub, connect
remote." I listed the account first and found `froov30/Task-Tracker-REST-API`
created yesterday, `isEmpty: true`. Creating a second repo would split the
project across two remotes for no reason — the work is already named. I did not
change visibility (left it private); the plan doesn't require public until
there's something to deploy.
Alternatives considered: `gh repo create task-tracker-api --public` matching
ARCHITECTURE.md's `task-tracker-api/` folder name. Didn't, because the empty
repo already matches this workspace's name.
Trade-off accepted: Remote is private for now. Fine for Phase 0; can flip later
if the Azure/GitHub-Actions story wants a public URL.

---

## #14 — Local venv uses Python 3.12; Docker stays on 3.11-slim
Date/Phase: Phase 0 (Project Setup)
Decision: Create the local `venv` with the Python already on this machine (3.12.0).
Leave the planned Docker base image as `python:3.11-slim` (ARCHITECTURE.md §6 /
IMPLEMENTATION_PLAN.md Phase 9) — do not retarget Docker to 3.12 just because
that's what's installed locally.
Reasoning: TRD.md §1 says "Python 3.11+", so 3.12 is in-range. I checked for 3.11
via `py -3.11` and it isn't installed; installing a second interpreter just to
match the container patch-for-patch would have delayed scaffold for no Phase 0
payoff. FastAPI/Pydantic/Uvicorn all support 3.12. The container image is still
the source of truth for production, so the local version being one minor newer is
fine as long as we don't start using 3.12-only syntax.
Alternatives considered: Install CPython 3.11 locally to match Docker exactly
(`py -3.11` failed, would need a manual install). Didn't do it — not worth
blocking Phase 0.
Trade-off accepted: Local-vs-container Python minor versions differ. If something
only fails in one of those two places later, that's the first thing to check.

---

## #13 — Azure App Service over Render as the deployment target
Date/Phase: Phase 9 (Cloud Deployment)
Decision: Deploy the containerized app to Azure App Service for Containers instead of
Render (the original plan's target).
Reasoning: The project's real purpose has shifted from "a deployable demo" to "evidence
of cloud-native skills for a specific job target" — the JDs this project supports name
Azure explicitly as the preferred cloud platform. Deploying to Azure turns a generic
"deployed live" claim into a claim that matches a named requirement.
Alternatives considered: Keep Render (simpler free-tier setup, zero-config auto-deploy
on push); AWS/GCP (not named as preferred by the target JDs, so lower payoff for the
same effort).
Trade-off accepted: Azure App Service setup (registry push, App Service configuration)
has more moving parts than Render's git-push-to-deploy flow — more surface area to get
right, but it's the surface area that's actually relevant to defend in an interview.

## #12 — Docker for containerization, chosen deliberately over a direct-process deploy
Date/Phase: Phase 8 (Containerization)
Decision: Package the app as a Docker image (`python:3.11-slim` base) rather than
deploying the bare Python process directly to a host.
Reasoning: Containerization is both a genuinely good practice (environment parity,
reproducible builds) and a named, load-bearing keyword for the target roles. Building
it in from the start — rather than as an afterthought — means the Dockerfile reflects
the actual final app (with filtering/sorting/concurrency already in place), not a
stale earlier version that needs rebuilding.
Alternatives considered: Direct deploy (`uvicorn` running straight on the host/Render's
process model, no container layer).
Trade-off accepted: One more file and one more moving part (image build/push step)
than a direct deploy — accepted because the skill being demonstrated is the container
step itself, not just "the API runs somewhere."

## #11 — Automated tests made mandatory, not optional
Date/Phase: Phase 6 (Automated Tests)
Decision: `tests/test_tasks.py` is a required gate — no later phase proceeds until it
passes — reversing the original plan's "(Optional) Automated Tests" framing.
Reasoning: Filtering/sorting and optimistic concurrency introduce real edge cases that
fail silently if untested (a broken whitelist lookup, an off-by-one in a date filter, a
version check that doesn't actually block a stale write). These are also exactly the
kind of bug a technical interviewer probes for verbally, tests or not — so untested
"depth" features are a liability, not just an incomplete nice-to-have. Separately, the
project's CI pipeline (see #12/#13 context) would otherwise be running lint against an
empty test suite, which makes the "automated testing" claim technically true but
practically hollow.
Alternatives considered: Keep tests optional/stretch, as in the original plan; test
manually via `/docs` only (as the original TRD's testing section allowed).
Trade-off accepted: More upfront time before deployment/docs phases can start —
accepted because it's the difference between a CI pipeline that's real versus one
that's decorative.

## #10 — `TaskUpdate.version` as an intentional required-field exception to #6
Date/Phase: Phase 2 (Schemas) / Phase 3 (Models)
Decision: `version: int` is added to `TaskUpdate` as a **required** field, while every
other field on `TaskUpdate` remains optional per Decision #6.
Reasoning: Optimistic concurrency control only works if the client is forced to state
which version of the row they last read — making it optional would defeat the purpose
(a client could omit it and silently skip the safety check). This is a deliberate,
narrow exception to #6's "everything optional" pattern, not a silent contradiction of
it — logged explicitly here so the two decisions read as consistent with each other
rather than conflicting.
Alternatives considered: Pass `version` as a header (e.g., `If-Match`) instead of a
body field, mimicking HTTP ETags more closely; make `version` optional and skip the
check when absent.
Trade-off accepted: `TaskUpdate` is no longer "every field optional," which is a minor
API-shape inconsistency — accepted because the alternative (an optional safety check)
isn't actually safe.

## #9 — Optimistic concurrency control over pessimistic locking
Date/Phase: Phase 3 (Models) / Phase 4 (Routers)
Decision: Add a `version` column; `PUT /tasks/{id}` requires the client's last-known
`version` and performs `UPDATE ... WHERE id = ? AND version = ?`. A 0-row update
(version mismatch) returns `409 Conflict` instead of applying the write or silently
succeeding.
Reasoning: This is the standard, low-overhead answer to "how do you prevent two
clients from silently overwriting each other's changes?" — a question likely to come
up directly given the target JDs' emphasis on reliability and distributed systems.
Alternatives considered: Pessimistic locking (`SELECT ... FOR UPDATE`) — not
meaningfully supported by SQLite's locking model, and overkill for expected traffic;
no concurrency handling at all — the honest baseline, but leaves silent data loss on
concurrent writes, which is the exact failure mode this decision exists to prevent.
Trade-off accepted: Clients must track and resend `version`, adding a small burden to
API consumers — accepted because the alternative is silent, undetected data loss.

## #8 — Whitelist map for dynamic sort columns, not raw string interpolation
Date/Phase: Phase 3 (Models)
Decision: `sort_by` (already constrained to a `Literal` by Pydantic/FastAPI) is mapped
through a fixed `SORT_COLUMNS` dict to a real column name before being used in
`ORDER BY`. It is never concatenated directly into the SQL string, even though FastAPI
validation already restricts its possible values.
Reasoning: Defense in depth — relying solely on the `Literal` type to prevent SQL
injection is correct today but fragile if the type constraint is ever loosened or
bypassed upstream. A whitelist lookup makes the safety property local to the query-
building code itself, not dependent on a separate layer staying correct forever. This
is also a strong, concrete interview talking point distinct from ordinary parameterized
`WHERE` clauses (which handle the filter side safely by default).
Alternatives considered: Trust the `Literal` type alone and interpolate directly;
allow-list validation via a regex/`if` check instead of a dict lookup.
Trade-off accepted: One extra small data structure (`SORT_COLUMNS`) to maintain in
sync with the `SortBy` literal — negligible cost for a meaningfully stronger guarantee.

---

## #7 — Table creation on app startup, not a separate migration script
Date/Phase: Phase 1 (Database Layer)
Decision: `init_db()` runs inside a FastAPI `startup` event in `main.py`, executing
`CREATE TABLE IF NOT EXISTS tasks (...)` — now including the `version` column from the
start (see #9), rather than as a later migration.
Reasoning: Render deploys should work with zero manual steps. A separate migration
command (e.g., Alembic) would require an extra deploy-time step or shell access, which
adds friction for a single-table project. This reasoning holds unchanged under the
Docker/Azure deployment target (#12, #13) — a fresh container instance still needs to
boot with zero manual DB steps.
Alternatives considered: Alembic migrations; a standalone `init_db.py` run manually
before first launch.
Trade-off accepted: No formal migration history if the schema changes later — acceptable
because the project has one table and low schema-churn risk. If the schema grows
complex, this should be revisited.

## #6 — `PUT` behaves like a partial update instead of adding a separate `PATCH`
Date/Phase: Phase 2 (Schemas)
Decision: `TaskUpdate` makes every field `Optional` **except `version`, which is
required — see #10 for why that's a deliberate exception, not a reversal of this
decision**; the `PUT /tasks/{id}` handler only applies fields the client actually sent
(`model_dump(exclude_unset=True)`).
Reasoning: The brief specifies exactly 5 endpoints covering the full lifecycle. Adding a
6th (`PATCH`) endpoint purely to support partial updates would break that constraint
without real benefit — REST purists would prefer `PATCH`, but a permissive `PUT` gets
the same practical behavior with one less endpoint.
Alternatives considered: Strict `PUT` (requires full object every time); adding
`PATCH` as a 6th endpoint.
Trade-off accepted: Slight deviation from strict REST semantics (`PUT` is technically
supposed to be a full replace). Documented explicitly in the README so it's not a
surprise to API consumers.

## #5 — Status is a closed enum, not a free-text string
Date/Phase: Phase 2 (Schemas)
Decision: `TaskStatus` is a Pydantic/Python `Enum` (`pending`, `in_progress`,
`completed`, `cancelled`), used in both `TaskUpdate` and the DB layer.
Reasoning: Prevents invalid states (`"Done"`, `"dun"`, typos) from ever reaching
storage. Validation failure happens at the schema layer and returns a clean `422`
automatically — no manual `if status not in [...]` checks needed in route code.
Alternatives considered: Free-text `str` column with manual validation in the route.
Trade-off accepted: Adding a new status later requires a code change (enum edit) rather
than being data-driven — acceptable since lifecycle states are a fixed, small set by
design (see PRD §8).

## #4 — No re-opening completed/cancelled tasks (terminal states)
Date/Phase: Phase 2 (Schemas) / PRD definition
Decision: `completed` and `cancelled` are treated as terminal states in v1; the API does
not block transitioning out of them at the code level, but the product design assumes
one-way flow.
Reasoning: Keeps the state model simple for a demo project without an explicit
state-machine/transition-guard layer. Enforcing hard transition rules would need
extra logic disproportionate to project scope.
Alternatives considered: A full state-machine layer validating allowed transitions.
Trade-off accepted: A client *could* technically PUT a completed task back to
`pending` — accepted as a known simplification, called out in PRD Non-Goals.

## #3 — Raw `sqlite3` (stdlib) instead of an ORM (SQLAlchemy)
Date/Phase: Phase 1 (Database Layer)
Decision: Data-access functions in `app/models/task.py` use Python's built-in `sqlite3`
module directly with parameterized SQL, wrapped in small CRUD functions — including the
whitelisted sort/filter logic added in #8, which stays consistent with this approach
rather than motivating a switch to an ORM.
Reasoning: The project brief explicitly calls out "SQLite for persistent storage" with
a single table and no relations. An ORM (SQLAlchemy/SQLModel) adds a real learning/setup
cost (engine, session management, declarative models) with no payoff at this scale, and
would blur the "models vs schemas" separation the brief wants demonstrated
(Pydantic already owns validation; adding ORM models would create two competing
"model" concepts).
Alternatives considered: SQLAlchemy Core; SQLAlchemy ORM; SQLModel (Pydantic+SQLAlchemy
hybrid).
Trade-off accepted: If the project later needs joins/relations or a DB swap
(e.g., Postgres), migrating off raw `sqlite3` will take more effort than if an ORM had
been used from the start. Acceptable given current fixed scope (PRD Non-Goals).

## #2 — Layered folder structure: routers / schemas / models / database
Date/Phase: Phase 0 (Setup) / Architecture design
Decision: Split code into `routers/`, `schemas/`, `models/`, and a top-level
`database.py`, rather than a single `main.py` with everything inline.
Reasoning: The brief explicitly requires "clean separation of routes, models, and
schemas." Separation also makes each layer independently testable and keeps SQL out of
HTTP-facing code.
Alternatives considered: Single-file FastAPI app (fastest to write, common for tiny
demos); feature-based folders (`tasks/` module containing everything) — reasonable for
larger apps but overkill for one resource.
Trade-off accepted: Slightly more boilerplate (multiple `__init__.py`/imports) than a
single-file app, for a maintainability payoff that's worth it given the brief's
explicit ask.

## #1 — FastAPI over Flask/Django REST Framework
Date/Phase: Phase 0 (Setup)
Decision: Use FastAPI as the web framework.
Reasoning: Project brief specifies FastAPI directly. Independently justified anyway:
native Pydantic integration gives request/response validation "for free," automatic
OpenAPI/Swagger docs satisfy the documentation requirement with near-zero extra work,
and async support is a forward-looking skill signal.
Alternatives considered: Flask + Marshmallow (more manual validation wiring); Django
REST Framework (heavier than needed for a 5-endpoint, single-resource API).
Trade-off accepted: None significant — FastAPI is a strict improvement for this
project's shape and was already the specified constraint.

---

## Template for new entries (copy this when a new decision is made)
```
## #N — <short title>
Date/Phase:
Decision:
Reasoning:
Alternatives considered:
Trade-off accepted:
```
