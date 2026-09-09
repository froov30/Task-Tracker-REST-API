"""
locustfile.py — v2 load test harness for the Task Tracker REST API.

Updated for the v2 API:
  - All routes are under /api/v1
  - Every request requires a JWT Bearer token (obtained per simulated user via
    register + login in on_start, then cached and sent on all requests)

Two scenarios:

  1. ConcurrentWriteUser — Concurrent writes to the same task ID.
     Many users PUT the *same* task simultaneously to exercise optimistic
     concurrency control: a healthy run produces 409 responses under
     contention, never lost updates or 5xx errors.

  2. MixedLoadUser — Realistic mix of POST, GET, PUT at increasing concurrency.
     Run with --users 10 / 50 / 100 / 200 to build the latency/throughput table
     in docs/LOAD_TESTING.md.

Usage
-----
Start the server (with Postgres up) in a separate terminal:
    docker compose up            # brings up Postgres + app on :8000
    # or, locally against Postgres:
    alembic upgrade head && uvicorn app.main:app --host 127.0.0.1 --port 8000

Then run a scenario headlessly:

  locust -f locustfile.py MixedLoadUser \\
      --headless --host http://127.0.0.1:8000 \\
      --users 50 --spawn-rate 10 --run-time 60s \\
      --csv results/mixed_50

Repeat with --users 10 / 100 / 200 for the full ramp.
"""

import random
import uuid

from locust import HttpUser, between, task

API = "/api/v1"


# ---------------------------------------------------------------------------
# Auth helper — each simulated user registers + logs in once
# ---------------------------------------------------------------------------

def _authenticate(client) -> dict:
    """
    Register a unique user and log in. Returns an Authorization header dict,
    or {} if auth failed (requests will then surface as failures in Locust).
    """
    email = f"load-{uuid.uuid4().hex[:12]}@example.com"
    password = "loadtest-password-123"

    client.post(
        f"{API}/auth/register",
        json={"email": email, "password": password},
        name="/api/v1/auth/register [POST]",
    )
    resp = client.post(
        f"{API}/auth/login",
        data={"username": email, "password": password},
        name="/api/v1/auth/login [POST]",
    )
    if resp.status_code == 200:
        token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    return {}


def _create_task(client, headers: dict, title: str) -> int | None:
    """POST a task and return its id, or None on failure."""
    resp = client.post(
        f"{API}/tasks",
        json={"title": title, "description": "load test"},
        headers=headers,
        name="/api/v1/tasks [POST]",
    )
    if resp.status_code == 201:
        return resp.json()["id"]
    return None


# ---------------------------------------------------------------------------
# Scenario 1 — Concurrent writes to the same shared task
# ---------------------------------------------------------------------------

class ConcurrentWriteUser(HttpUser):
    """All users race to PUT the same task; healthy runs show 409s, no 5xx."""

    wait_time = between(0.05, 0.2)

    _shared_task_id: int | None = None

    def on_start(self) -> None:
        self._headers = _authenticate(self.client)

        # The first authenticated user seeds the shared contention target.
        if ConcurrentWriteUser._shared_task_id is None and self._headers:
            ConcurrentWriteUser._shared_task_id = _create_task(
                self.client, self._headers, "shared-contention-target"
            )
        self._refresh_version()

    def _refresh_version(self) -> None:
        task_id = ConcurrentWriteUser._shared_task_id
        if task_id is None:
            self._current_version = None
            return
        resp = self.client.get(
            f"{API}/tasks/{task_id}",
            headers=self._headers,
            name="/api/v1/tasks/{id} [GET refresh]",
        )
        self._current_version = (
            resp.json()["version"] if resp.status_code == 200 else None
        )

    @task
    def write_shared_task(self) -> None:
        task_id = ConcurrentWriteUser._shared_task_id
        if task_id is None or self._current_version is None:
            self._refresh_version()
            return

        resp = self.client.put(
            f"{API}/tasks/{task_id}",
            json={
                "title": f"contention-update-v{self._current_version}",
                "version": self._current_version,
            },
            headers=self._headers,
            name="/api/v1/tasks/{id} [PUT contention]",
        )

        if resp.status_code == 200:
            self._current_version = resp.json()["version"]
        elif resp.status_code == 409:
            self._refresh_version()


# ---------------------------------------------------------------------------
# Scenario 2 — Mixed read/write load
# ---------------------------------------------------------------------------

class MixedLoadUser(HttpUser):
    """A realistic API consumer: creates, lists (paginated), and updates."""

    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        self._headers = _authenticate(self.client)
        self._owned_tasks: list[dict] = []
        task_id = _create_task(
            self.client, self._headers, f"seed-task-{random.randint(1000, 9999)}"
        )
        if task_id is not None:
            self._owned_tasks.append({"id": task_id, "version": 1})

    @task(3)
    def list_tasks(self) -> None:
        self.client.get(
            f"{API}/tasks",
            params={"page": 1, "page_size": 20},
            headers=self._headers,
            name="/api/v1/tasks [GET list]",
        )

    @task(1)
    def create_task(self) -> None:
        task_id = _create_task(
            self.client, self._headers, f"mixed-task-{random.randint(10000, 99999)}"
        )
        if task_id is not None:
            self._owned_tasks.append({"id": task_id, "version": 1})
            if len(self._owned_tasks) > 20:
                self._owned_tasks.pop(0)

    @task(1)
    def update_own_task(self) -> None:
        if not self._owned_tasks:
            return

        entry = random.choice(self._owned_tasks)
        resp = self.client.put(
            f"{API}/tasks/{entry['id']}",
            json={
                "title": f"updated-{random.randint(1, 9999)}",
                "version": entry["version"],
            },
            headers=self._headers,
            name="/api/v1/tasks/{id} [PUT mixed]",
        )

        if resp.status_code == 200:
            entry["version"] = resp.json()["version"]
        elif resp.status_code == 409:
            sync = self.client.get(
                f"{API}/tasks/{entry['id']}",
                headers=self._headers,
                name="/api/v1/tasks/{id} [GET sync]",
            )
            if sync.status_code == 200:
                entry["version"] = sync.json()["version"]
