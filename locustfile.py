"""
locustfile.py — Phase 7 load test harness for the Task Tracker REST API.

Two required scenarios (TRD.md §7.5):

  1. ConcurrentWriteUser — Concurrent writes to the same task ID.
     Many simulated users issue PUT /tasks/{id} against the *same* task
     simultaneously. Exercises DECISIONS.md #9's optimistic concurrency control:
     a healthy test run produces 409 responses under contention, NOT silent data
     loss or corrupt state.

  2. MixedLoadUser — Mixed read/write load at increasing concurrency.
     A realistic mix of POST, GET /tasks, and PUT requests. Run with
     --users 10, then 50, then 200 to build the latency/throughput/error-rate
     table documented in docs/LOAD_TESTING.md.

Usage
-----
Make sure the server is running in a separate terminal:
    uvicorn app.main:app --host 127.0.0.1 --port 8000

Then run either scenario headlessly (append --users N --spawn-rate N --run-time 60s):

  # Scenario 1 — concurrent writes (stresses OCC / 409 behaviour)
  .\\venv\\Scripts\\locust.exe -f locustfile.py ConcurrentWriteUser ^
      --headless --host http://127.0.0.1:8000 ^
      --users 50 --spawn-rate 10 --run-time 60s ^
      --csv results/concurrent_writes

  # Scenario 2 — mixed load at 10 users
  .\\venv\\Scripts\\locust.exe -f locustfile.py MixedLoadUser ^
      --headless --host http://127.0.0.1:8000 ^
      --users 10 --spawn-rate 5 --run-time 60s ^
      --csv results/mixed_10

  # Repeat with --users 50 and --users 200 for the full ramp.

Results (CSV) land in results/  — use those numbers to fill docs/LOAD_TESTING.md.
"""

import random

from locust import HttpUser, between, task


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _create_task(client, title: str) -> int | None:
    """POST a task and return its id, or None on failure."""
    resp = client.post(
        "/tasks",
        json={"title": title, "description": "load test"},
        name="/tasks [POST]",
    )
    if resp.status_code == 201:
        return resp.json()["id"]
    return None


# ---------------------------------------------------------------------------
# Scenario 1 — Concurrent writes to the same shared task
# ---------------------------------------------------------------------------

class ConcurrentWriteUser(HttpUser):
    """
    All users race to PUT the same task.

    Setup: one seed task is created per user at start; all users PUT the
    same *shared* task_id (class-level). Since every successful PUT increments
    the version, users with a stale version get a 409 — exactly the behaviour
    DECISIONS.md #9 promises. The test is healthy when you see 409s in the
    output; it would be *broken* if concurrent updates produced lost data or
    5xx errors.

    Because every 409 means the user must re-fetch, on_start also reads the
    current task so the user always has a fresh version to start with.
    """

    wait_time = between(0.05, 0.2)  # tight spacing to maximise contention

    # Shared across all ConcurrentWriteUser instances in the same worker.
    # Populated by the first user to start; others reuse the same id.
    _shared_task_id: int | None = None

    def on_start(self) -> None:
        if ConcurrentWriteUser._shared_task_id is None:
            task_id = _create_task(self.client, "shared-contention-target")
            ConcurrentWriteUser._shared_task_id = task_id

        self._refresh_version()

    def _refresh_version(self) -> None:
        """Re-fetch the shared task so we have the current version."""
        task_id = ConcurrentWriteUser._shared_task_id
        if task_id is None:
            return
        resp = self.client.get(
            f"/tasks/{task_id}",
            name="/tasks/{id} [GET refresh]",
        )
        if resp.status_code == 200:
            self._current_version = resp.json()["version"]
        else:
            self._current_version = None

    @task
    def write_shared_task(self) -> None:
        """Attempt to PUT the shared task with our last-known version."""
        task_id = ConcurrentWriteUser._shared_task_id
        if task_id is None or self._current_version is None:
            self._refresh_version()
            return

        resp = self.client.put(
            f"/tasks/{task_id}",
            json={
                "title": f"contention-update-v{self._current_version}",
                "version": self._current_version,
            },
            name="/tasks/{id} [PUT contention]",
        )

        if resp.status_code == 200:
            # Our write won — bump our local version to match
            self._current_version = resp.json()["version"]
        elif resp.status_code == 409:
            # Expected under contention — re-fetch to get the winning version
            self._refresh_version()
        # Any other status code is a genuine error; Locust records it as a failure.


# ---------------------------------------------------------------------------
# Scenario 2 — Mixed read/write load
# ---------------------------------------------------------------------------

class MixedLoadUser(HttpUser):
    """
    Simulates a realistic API consumer: creates tasks, lists them, and
    occasionally updates one it created earlier.

    Run three times with --users 10 / 50 / 200 to produce the concurrency
    ramp data required by TRD.md §7.5 and docs/LOAD_TESTING.md.
    """

    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        """Seed one task per user so updates have something to work with."""
        self._owned_tasks: list[dict] = []  # [{id, version}, ...]
        task_id = _create_task(self.client, f"seed-task-{random.randint(1000, 9999)}")
        if task_id is not None:
            self._owned_tasks.append({"id": task_id, "version": 1})

    # Weight 1 : read-heavy mix (3 GETs per 1 POST per 1 PUT)
    @task(3)
    def list_tasks(self) -> None:
        self.client.get("/tasks", name="/tasks [GET list]")

    @task(1)
    def create_task(self) -> None:
        task_id = _create_task(
            self.client, f"mixed-task-{random.randint(10000, 99999)}"
        )
        if task_id is not None:
            self._owned_tasks.append({"id": task_id, "version": 1})
            # Cap the list so memory doesn't grow unbounded over long runs
            if len(self._owned_tasks) > 20:
                self._owned_tasks.pop(0)

    @task(1)
    def update_own_task(self) -> None:
        if not self._owned_tasks:
            return

        entry = random.choice(self._owned_tasks)
        resp = self.client.put(
            f"/tasks/{entry['id']}",
            json={
                "title": f"updated-{random.randint(1, 9999)}",
                "version": entry["version"],
            },
            name="/tasks/{id} [PUT mixed]",
        )

        if resp.status_code == 200:
            entry["version"] = resp.json()["version"]
        elif resp.status_code == 409:
            # Re-fetch to sync version
            sync = self.client.get(
                f"/tasks/{entry['id']}",
                name="/tasks/{id} [GET sync]",
            )
            if sync.status_code == 200:
                entry["version"] = sync.json()["version"]
