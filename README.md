# Task Tracker REST API

![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)
![CI Status](https://img.shields.io/badge/build-passing-brightgreen.svg)
![Tests](https://img.shields.io/badge/tests-28%2F28%20passing-success.svg)
![Docker](https://img.shields.io/badge/docker-ready-2496ED.svg)
![Azure Deployment](https://img.shields.io/badge/azure-live-0089D6.svg)

A production-ready, lightweight REST API built with **FastAPI**, **Pydantic v2**, and **SQLite** for managing task lifecycles with Optimistic Concurrency Control (OCC), combinable filtering, column-whitelisted sorting, comprehensive test suite, and empirical load-testing baseline.

---

## ⚡ 1-Minute System Architecture & Data Flow

GitHub renders the diagram below natively. It outlines how a client request travels through our strict architectural layers, performs Optimistic Concurrency Control (OCC), and deploys to the cloud:

```mermaid
flowchart TD
    subgraph Client [" Client Layer "]
        C[HTTP Client / Curl / Swagger UI / Locust]
    end

    subgraph Infrastructure [" Cloud & CI/CD Infrastructure "]
        GA["GitHub Actions CI<br/>(Ruff Lint + 28 Pytest Suite)"]
        AZ["Azure App Service for Containers<br/>(Central India Region / F1 Tier)"]
        DK["Docker Hub Image<br/>(da99war/task-tracker-api)"]
    end

    subgraph API [" FastAPI Application Layer "]
        R["routers/tasks.py<br/>(FastAPI Path Operations)"]
        S["schemas/task.py<br/>(Pydantic v2 Request/Response Validation)"]
        M["models/task.py<br/>(Data Access Layer & Query Builder)"]
        DB[("database.py<br/>tasks.db (SQLite)")]
    end

    %% Flow connections
    C -->|HTTP Request| R
    R -->|Validate Request| S
    S -->|Validated Object| R
    
    R -->|Call Data Model| M
    
    M -->|Parameterized SQL + Whitelisted ORDER BY| DB
    DB -->|Raw Sqlite Row / Affected Count| M

    %% Concurrency logic
    M -->|Check Affected Rows| Decision{Row Count & State}
    Decision -->|1 Row Affected| OK["HTTP 200/201 Success (Version + 1)"]
    Decision -->|0 Rows (Not Found)| N404["HTTP 404 Not Found"]
    Decision -->|0 Rows (Version Mismatch)| C409["HTTP 409 Conflict (OCC Triggered)"]

    OK --> C
    N404 --> C
    C409 --> C

    %% Infra ties
    GA -.->|Gates Build| DK
    DK -.->|Deploys to| AZ
    AZ -.->|Hosts| R
```

---

## Key Highlights

- **Full Task Lifecycle (5 REST Endpoints):** `POST`, `GET` (list), `GET` (single), `PUT` (partial update), `DELETE`.
- **Optimistic Concurrency Control (OCC):** Prevents lost updates using mandatory versioning (`version: int`). Returns `409 Conflict` on version mismatches under concurrent writes (tested with Locust).
- **Dynamic Filtering & Sorting:** Filter by `status`, `due_before`, and `due_after`. Sort safely by `created_at`, `due_date`, or `title` using column whitelisting (SQL injection safe).
- **Validation-First:** Pydantic v2 enforces schema validation for all requests (`422 Unprocessable Entity`).
- **Comprehensive Automated Tests:** 28 unit and integration tests using `pytest` and `httpx` with per-test isolated SQLite databases.
- **Benchmarked Scalability:** Empirical load-testing baseline via `Locust` with documented concurrency bounds (0% errors at 10 users; ~50 writer ceiling).
- **Production CI/CD & Deployment:** GitHub Actions CI pipeline running Ruff + Pytest, Dockerized with `python:3.11-slim`, and deployed live on Azure App Service.

---

## Tech Stack & Architecture

- **Language:** Python 3.11+
- **Framework:** FastAPI + Uvicorn ASGI server
- **Validation:** Pydantic v2
- **Database:** SQLite (`sqlite3` stdlib with parameterized queries)
- **Testing:** `pytest` + FastAPI `TestClient`
- **Load Testing:** Locust
- **CI/CD & Cloud:** GitHub Actions, Docker, Azure App Service

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

- **Live Service URL:** [https://task-tracker-api-dhruv.azurewebsites.net](https://task-tracker-api-dhruv.azurewebsites.net)
- **Interactive Swagger Docs:** [https://task-tracker-api-dhruv.azurewebsites.net/docs](https://task-tracker-api-dhruv.azurewebsites.net/docs)
- **ReDoc Documentation:** [https://task-tracker-api-dhruv.azurewebsites.net/redoc](https://task-tracker-api-dhruv.azurewebsites.net/redoc)

---

## Known Limitations

- **SQLite Ephemerality:** SQLite stores data in a local file (`tasks.db`). Without a persistent volume mounted in container environments (e.g. Docker / Azure App Service), database state is ephemeral per container instance restart. For higher write concurrency or persistent multi-container scaling, PostgreSQL migration is recommended (documented in `DECISIONS.md` #19).
