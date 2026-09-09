"""
Audit history tests (Phase 6, Task 15).

Every mutating operation records an entry:
  create → deleted → restored → updated ...
GET /tasks/{id}/history returns them oldest-first.
"""


def _create(client, title="hist task"):
    resp = client.post("/tasks", json={"title": title})
    assert resp.status_code == 201
    return resp.json()


def _history(client, task_id):
    resp = client.get(f"/tasks/{task_id}/history")
    assert resp.status_code == 200
    return resp.json()


class TestAuditHistory:
    def test_create_records_one_entry(self, client):
        task = _create(client)
        hist = _history(client, task["id"])
        assert len(hist) == 1
        assert hist[0]["action"] == "created"

    def test_update_adds_entry(self, client):
        task = _create(client)
        client.put(f"/tasks/{task['id']}", json={"title": "renamed", "version": 1})
        hist = _history(client, task["id"])
        assert len(hist) == 2
        assert hist[0]["action"] == "created"
        assert hist[1]["action"] == "updated"

    def test_full_lifecycle_four_entries(self, client):
        task = _create(client)
        tid = task["id"]
        client.put(f"/tasks/{tid}", json={"title": "renamed", "version": 1})  # updated
        client.delete(f"/tasks/{tid}")                                        # deleted
        client.post(f"/tasks/{tid}/restore")                                  # restored

        hist = _history(client, tid)
        actions = [h["action"] for h in hist]
        assert actions == ["created", "updated", "deleted", "restored"]

    def test_history_ordered_oldest_first(self, client):
        task = _create(client)
        tid = task["id"]
        client.put(f"/tasks/{tid}", json={"title": "a", "version": 1})
        client.put(f"/tasks/{tid}", json={"title": "b", "version": 2})
        hist = _history(client, tid)
        ids = [h["id"] for h in hist]
        assert ids == sorted(ids)

    def test_update_changed_fields_recorded(self, client):
        task = _create(client)
        client.put(
            f"/tasks/{task['id']}",
            json={"title": "new title", "version": 1},
        )
        hist = _history(client, task["id"])
        updated = hist[-1]
        assert updated["action"] == "updated"
        assert updated["changed_fields"]["title"] == "new title"

    def test_snapshot_recorded_on_create(self, client):
        task = _create(client, "snap")
        hist = _history(client, task["id"])
        snap = hist[0]["snapshot"]
        assert snap["title"] == "snap"
        assert snap["status"] == "pending"

    def test_history_available_for_deleted_task(self, client):
        task = _create(client)
        client.delete(f"/tasks/{task['id']}")
        # history still accessible even though task is soft-deleted
        hist = _history(client, task["id"])
        assert [h["action"] for h in hist] == ["created", "deleted"]

    def test_history_nonexistent_task_404(self, client):
        resp = client.get("/tasks/99999/history")
        assert resp.status_code == 404

    def test_history_other_users_task_403(self, anon_client):
        anon_client.post(
            "/auth/register", json={"email": "ha@example.com", "password": "password123"}
        )
        token_a = anon_client.post(
            "/auth/login", data={"username": "ha@example.com", "password": "password123"}
        ).json()["access_token"]
        anon_client.post(
            "/auth/register", json={"email": "hb@example.com", "password": "password123"}
        )
        token_b = anon_client.post(
            "/auth/login", data={"username": "hb@example.com", "password": "password123"}
        ).json()["access_token"]

        task = anon_client.post(
            "/tasks", json={"title": "A's"}, headers={"Authorization": f"Bearer {token_a}"}
        ).json()

        resp = anon_client.get(
            f"/tasks/{task['id']}/history",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp.status_code == 403
