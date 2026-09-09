"""
Task priority field tests (Phase 7, Task 16).

priority: low | medium | high | critical, defaults to medium.
Supports create, update, filter, and sort_by=priority.
"""


def _create(client, title, **extra):
    resp = client.post("/tasks", json={"title": title, **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestPriorityCreate:
    def test_default_priority_is_medium(self, client):
        task = _create(client, "default")
        assert task["priority"] == "medium"

    def test_create_with_priority(self, client):
        task = _create(client, "urgent", priority="high")
        assert task["priority"] == "high"

    def test_create_critical(self, client):
        task = _create(client, "fire", priority="critical")
        assert task["priority"] == "critical"

    def test_invalid_priority_rejected_422(self, client):
        resp = client.post("/tasks", json={"title": "bad", "priority": "urgent"})
        assert resp.status_code == 422


class TestPriorityUpdate:
    def test_update_priority(self, client):
        task = _create(client, "bump", priority="low")
        resp = client.put(
            f"/tasks/{task['id']}",
            json={"priority": "high", "version": 1},
        )
        assert resp.status_code == 200
        assert resp.json()["priority"] == "high"


class TestPriorityFilter:
    def test_filter_by_priority(self, client):
        _create(client, "a", priority="high")
        _create(client, "b", priority="low")
        _create(client, "c", priority="high")

        resp = client.get("/tasks", params={"priority": "high"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert all(t["priority"] == "high" for t in body["items"])

    def test_invalid_priority_filter_422(self, client):
        resp = client.get("/tasks", params={"priority": "bogus"})
        assert resp.status_code == 422


class TestPrioritySort:
    def test_sort_by_priority_asc(self, client):
        # alphabetical: critical < high < low < medium
        _create(client, "m", priority="medium")
        _create(client, "c", priority="critical")
        _create(client, "h", priority="high")

        resp = client.get(
            "/tasks", params={"sort_by": "priority", "sort_order": "asc"}
        )
        assert resp.status_code == 200
        priorities = [t["priority"] for t in resp.json()["items"]]
        assert priorities == sorted(priorities)
