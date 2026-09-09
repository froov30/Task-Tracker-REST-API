"""
Soft delete, version-guarded delete, and restore tests (Phase 6, Tasks 13 & 14).
"""


def _create(client, title="sd task"):
    resp = client.post("/tasks", json={"title": title})
    assert resp.status_code == 201
    return resp.json()


class TestVersionGuardedDelete:
    def test_delete_with_correct_version_204(self, client):
        task = _create(client)
        resp = client.delete(f"/tasks/{task['id']}", params={"version": 1})
        assert resp.status_code == 204

    def test_delete_with_stale_version_409(self, client):
        task = _create(client)
        # bump version to 2
        client.put(f"/tasks/{task['id']}", json={"title": "v2", "version": 1})
        # delete with stale version 1 → 409
        resp = client.delete(f"/tasks/{task['id']}", params={"version": 1})
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "VERSION_CONFLICT"

    def test_delete_without_version_204_backward_compat(self, client):
        task = _create(client)
        resp = client.delete(f"/tasks/{task['id']}")
        assert resp.status_code == 204

    def test_stale_delete_does_not_remove_task(self, client):
        task = _create(client)
        client.put(f"/tasks/{task['id']}", json={"title": "v2", "version": 1})
        client.delete(f"/tasks/{task['id']}", params={"version": 1})  # 409
        # task still retrievable
        assert client.get(f"/tasks/{task['id']}").status_code == 200


class TestSoftDelete:
    def test_deleted_task_returns_404_on_get(self, client):
        task = _create(client)
        client.delete(f"/tasks/{task['id']}")
        assert client.get(f"/tasks/{task['id']}").status_code == 404

    def test_deleted_task_excluded_from_list(self, client):
        _create(client, "keep")
        t2 = _create(client, "remove")
        client.delete(f"/tasks/{t2['id']}")
        body = client.get("/tasks").json()
        titles = [t["title"] for t in body["items"]]
        assert "keep" in titles
        assert "remove" not in titles
        assert body["total"] == 1

    def test_include_deleted_shows_deleted(self, client):
        _create(client, "keep")
        t2 = _create(client, "remove")
        client.delete(f"/tasks/{t2['id']}")
        body = client.get("/tasks", params={"include_deleted": True}).json()
        titles = [t["title"] for t in body["items"]]
        assert "keep" in titles
        assert "remove" in titles
        assert body["total"] == 2


class TestRestore:
    def test_restore_brings_task_back(self, client):
        task = _create(client)
        client.delete(f"/tasks/{task['id']}")
        assert client.get(f"/tasks/{task['id']}").status_code == 404

        resp = client.post(f"/tasks/{task['id']}/restore")
        assert resp.status_code == 200
        assert resp.json()["id"] == task["id"]

        # now retrievable again
        assert client.get(f"/tasks/{task['id']}").status_code == 200

    def test_restore_nonexistent_returns_404(self, client):
        resp = client.post("/tasks/99999/restore")
        assert resp.status_code == 404

    def test_restore_active_task_returns_409(self, client):
        task = _create(client)  # not deleted
        resp = client.post(f"/tasks/{task['id']}/restore")
        assert resp.status_code == 409

    def test_restored_task_appears_in_list(self, client):
        task = _create(client, "phoenix")
        client.delete(f"/tasks/{task['id']}")
        client.post(f"/tasks/{task['id']}/restore")
        body = client.get("/tasks").json()
        assert "phoenix" in [t["title"] for t in body["items"]]
