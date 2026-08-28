# Task Tracker REST API

A production-ready, lightweight REST API built with FastAPI, Pydantic v2, and SQLite for managing task lifecycles with optimistic concurrency control, filtering, sorting, automated testing, and baseline load-testing results.

---

## Features

- **Full Task Lifecycle (5 REST Endpoints):** `POST`, `GET` (list), `GET` (single), `PUT` (partial update), `DELETE`.
- **Optimistic Concurrency Control (OCC):** Prevents lost updates using mandatory versioning (`version: int`). Returns `409 Conflict` on version mismatches.
- **Dynamic Filtering & Sorting:** Filter by `status`, `due_before`, and `due_after`. Sort safely by `created_at`, `due_date`, or `title` using column whitelisting (SQL injection safe).
- **Validation-First:** Pydantic v2 enforces schema validation for all requests (`422 Unprocessable Entity`).
- **Comprehensive Automated Tests:** 28 unit and integration tests using `pytest` and `httpx`.
- **Benchmarked Scalability:** Empirical load-testing baseline via `Locust` with documented concurrency bounds.

---

## Tech Stack & Architecture

- **Language:** Python 3.11+
- **Framework:** FastAPI + Uvicorn ASGI server
- **Validation:** Pydantic v2
- **Database:** SQLite (`sqlite3` stdlib with parameterized queries)
- **Testing:** `pytest` + FastAPI `TestClient`
- **Load Testing:** Locust

---

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `PORT` | Port number Uvicorn binds to | `8000` |
| `DATABASE_PATH` | File path to SQLite database file | `./tasks.db` |

---

## Setup & Running Locally

### 1. Local Environment (Virtual Environment)

```bash
# Clone repository
git clone https://github.com/froov30/Task-Tracker-REST-API.git
cd Task-Tracker-REST-API

# Create and activate virtual environment
python -m venv venv
# On Windows PowerShell:
.\venv\Scripts\Activate.ps1
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run server
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Once running, interactive Swagger API documentation is available at:
- **Swagger UI:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc:** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

---

### 2. Docker Container (Local Parity)

```bash
# Build Docker image
docker build -t task-tracker-api .

# Run container
docker run -p 8000:8000 -e PORT=8000 task-tracker-api
```

---

## API Reference & `curl` Examples

### 1. Create Task (`POST /tasks`)

Creates a new task. The newly created task starts with `version: 1` and `status: "pending"`.

```bash
curl -X POST "http://127.0.0.1:8000/tasks" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Complete Phase 8 documentation",
    "description": "Write comprehensive README with curl examples",
    "due_date": "2026-08-30"
  }'
```

**Response (`201 Created`):**
```json
{
  "id": 1,
  "title": "Complete Phase 8 documentation",
  "description": "Write comprehensive README with curl examples",
  "status": "pending",
  "due_date": "2026-08-30",
  "created_at": "2026-08-28T07:30:00+00:00",
  "updated_at": "2026-08-28T07:30:00+00:00",
  "version": 1
}
```

---

### 2. List Tasks (`GET /tasks`)

Fetch tasks with combinable query parameters:
- `status`: `pending` | `in_progress` | `completed` | `cancelled`
- `due_before`: YYYY-MM-DD
- `due_after`: YYYY-MM-DD
- `sort_by`: `created_at` (default) | `due_date` | `title`
- `sort_order`: `desc` (default) | `asc`

```bash
curl -X GET "http://127.0.0.1:8000/tasks?status=pending&sort_by=due_date&sort_order=asc"
```

**Response (`200 OK`):**
```json
[
  {
    "id": 1,
    "title": "Complete Phase 8 documentation",
    "description": "Write comprehensive README with curl examples",
    "status": "pending",
    "due_date": "2026-08-30",
    "created_at": "2026-08-28T07:30:00+00:00",
    "updated_at": "2026-08-28T07:30:00+00:00",
    "version": 1
  }
]
```

---

### 3. Get Single Task (`GET /tasks/{id}`)

```bash
curl -X GET "http://127.0.0.1:8000/tasks/1"
```

**Response (`200 OK`):**
```json
{
  "id": 1,
  "title": "Complete Phase 8 documentation",
  "description": "Write comprehensive README with curl examples",
  "status": "pending",
  "due_date": "2026-08-30",
  "created_at": "2026-08-28T07:30:00+00:00",
  "updated_at": "2026-08-28T07:30:00+00:00",
  "version": 1
}
```

---

### 4. Update Task with OCC (`PUT /tasks/{id}`)

Partial updates are supported. **`version` is a required field** to enforce Optimistic Concurrency Control.

#### Successful Update (`200 OK`)

```bash
curl -X PUT "http://127.0.0.1:8000/tasks/1" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "in_progress",
    "version": 1
  }'
```

**Response (`200 OK`):**
```json
{
  "id": 1,
  "title": "Complete Phase 8 documentation",
  "description": "Write comprehensive README with curl examples",
  "status": "in_progress",
  "due_date": "2026-08-30",
  "created_at": "2026-08-28T07:30:00+00:00",
  "updated_at": "2026-08-28T07:35:00+00:00",
  "version": 2
}
```

#### Optimistic Concurrency Conflict Example (`409 Conflict`)

If a second client attempts to update task #1 using stale `version: 1` after version was incremented to `2`:

```bash
curl -X PUT "http://127.0.0.1:8000/tasks/1" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Conflicting change",
    "version": 1
  }'
```

**Response (`409 Conflict`):**
```json
{
  "detail": "version mismatch, re-fetch and retry"
}
```

---

### 5. Delete Task (`DELETE /tasks/{id}`)

```bash
curl -X DELETE "http://127.0.0.1:8000/tasks/1"
```

**Response (`204 No Content`)**

---

## Running Automated Tests

Run the full pytest suite (covers CRUD, filtering, sorting, OCC 409 conflicts, and validation 422s):

```bash
pytest tests/ -v
```

---

## Load Testing & Performance Baseline

Empirical load testing was executed using Locust across concurrent write contention and mixed read/write scenarios. For full benchmark data, latency percentiles, and SQLite lock contention behavior, see [`docs/LOAD_TESTING.md`](docs/LOAD_TESTING.md).

### Benchmark Summary

- **Safe Operational Ceiling:** ~30 concurrent users (0% errors, p50 < 20 ms).
- **Contention Handling:** 93.08% of requests under heavy write contention to a single resource were cleanly handled via `409 Conflict` responses.
- **Lock Contention:** SQLite file-level write locking begins causing `500` lock timeouts at ~50 concurrent users under continuous write load.

---

## Live Cloud Deployment (Azure)

- **Live Service URL:** *(To be updated after Phase 10 deployment)*
- **Swagger Documentation:** `https://<azure-app-name>.azurewebsites.net/docs`

---

## Known Limitations

- **SQLite Ephemerality:** SQLite stores data in a local file (`tasks.db`). Without a persistent volume mounted in container environments (e.g. Docker / Azure App Service), database state is ephemeral per container instance restart. For higher write concurrency or persistent multi-container scaling, PostgreSQL migration is recommended (documented in `DECISIONS.md` #19).
