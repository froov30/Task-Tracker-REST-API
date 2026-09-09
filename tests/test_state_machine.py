"""
Status transition state machine tests (Phase 5, Task 10).

VALID_TRANSITIONS:
  pending      → {in_progress, cancelled}
  in_progress  → {completed, cancelled}
  completed    → {}   (terminal)
  cancelled    → {}   (terminal)

Invalid transitions return 422 with code INVALID_TRANSITION.
"""


def _create(client, title="SM task"):
    resp = client.post("/tasks", json={"title": title})
    assert resp.status_code == 201
    return resp.json()


def _set_status(client, task_id, status, version):
    return client.put(
        f"/tasks/{task_id}", json={"status": status, "version": version}
    )


class TestValidTransitions:
    def test_pending_to_in_progress(self, client):
        task = _create(client)
        resp = _set_status(client, task["id"], "in_progress", 1)
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

    def test_pending_to_cancelled(self, client):
        task = _create(client)
        resp = _set_status(client, task["id"], "cancelled", 1)
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_in_progress_to_completed(self, client):
        task = _create(client)
        _set_status(client, task["id"], "in_progress", 1)
        resp = _set_status(client, task["id"], "completed", 2)
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_in_progress_to_cancelled(self, client):
        task = _create(client)
        _set_status(client, task["id"], "in_progress", 1)
        resp = _set_status(client, task["id"], "cancelled", 2)
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_no_op_same_status_allowed(self, client):
        """Updating other fields with the same status must not be blocked."""
        task = _create(client)
        resp = client.put(
            f"/tasks/{task['id']}",
            json={"title": "renamed", "status": "pending", "version": 1},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "renamed"

    def test_update_without_status_change_still_works(self, client):
        task = _create(client)
        resp = client.put(
            f"/tasks/{task['id']}",
            json={"title": "just a rename", "version": 1},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "just a rename"


class TestInvalidTransitions:
    def test_pending_to_completed_rejected(self, client):
        task = _create(client)
        resp = _set_status(client, task["id"], "completed", 1)
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_TRANSITION"

    def test_completed_to_pending_rejected(self, client):
        task = _create(client)
        _set_status(client, task["id"], "in_progress", 1)
        _set_status(client, task["id"], "completed", 2)
        resp = _set_status(client, task["id"], "pending", 3)
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_TRANSITION"

    def test_cancelled_to_in_progress_rejected(self, client):
        task = _create(client)
        _set_status(client, task["id"], "cancelled", 1)
        resp = _set_status(client, task["id"], "in_progress", 2)
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_TRANSITION"

    def test_completed_is_terminal(self, client):
        task = _create(client)
        _set_status(client, task["id"], "in_progress", 1)
        _set_status(client, task["id"], "completed", 2)
        # completed → cancelled is not allowed (terminal)
        resp = _set_status(client, task["id"], "cancelled", 3)
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_TRANSITION"

    def test_invalid_transition_does_not_mutate(self, client):
        task = _create(client)
        _set_status(client, task["id"], "completed", 1)  # rejected 422
        # Task remains pending, version unchanged
        check = client.get(f"/tasks/{task['id']}")
        assert check.json()["status"] == "pending"
        assert check.json()["version"] == 1
