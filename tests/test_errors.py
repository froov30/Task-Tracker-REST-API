"""
Structured error response tests (Phase 5, Task 11).

Every error is wrapped as:
    {"error": {"code": str, "message": str, "resource": ..., "resource_id": ...}}
"""


def _create(client, title="err task"):
    resp = client.post("/tasks", json={"title": title})
    assert resp.status_code == 201
    return resp.json()


def _assert_error_shape(body):
    assert "error" in body
    err = body["error"]
    assert "code" in err
    assert "message" in err
    assert "resource" in err
    assert "resource_id" in err


class TestErrorEnvelope:
    def test_404_has_task_not_found_code(self, client):
        resp = client.get("/tasks/99999")
        assert resp.status_code == 404
        body = resp.json()
        _assert_error_shape(body)
        assert body["error"]["code"] == "TASK_NOT_FOUND"
        assert body["error"]["resource"] == "task"
        assert body["error"]["resource_id"] == 99999

    def test_409_has_version_conflict_code(self, client):
        task = _create(client)
        # bump version to 2
        client.put(
            f"/tasks/{task['id']}", json={"title": "v2", "version": 1}
        )
        # stale version → 409
        resp = client.put(
            f"/tasks/{task['id']}", json={"title": "stale", "version": 1}
        )
        assert resp.status_code == 409
        body = resp.json()
        _assert_error_shape(body)
        assert body["error"]["code"] == "VERSION_CONFLICT"

    def test_422_invalid_transition_code(self, client):
        task = _create(client)
        resp = client.put(
            f"/tasks/{task['id']}",
            json={"status": "completed", "version": 1},
        )
        assert resp.status_code == 422
        body = resp.json()
        _assert_error_shape(body)
        assert body["error"]["code"] == "INVALID_TRANSITION"

    def test_422_body_validation_code(self, client):
        # Missing required title
        resp = client.post("/tasks", json={"description": "no title"})
        assert resp.status_code == 422
        body = resp.json()
        _assert_error_shape(body)
        assert body["error"]["code"] == "VALIDATION_ERROR"

    def test_401_unauthorized_code(self, anon_client):
        resp = anon_client.get("/tasks")
        assert resp.status_code == 401
        body = resp.json()
        _assert_error_shape(body)
        assert body["error"]["code"] == "UNAUTHORIZED"

    def test_403_forbidden_code(self, anon_client):
        # user A creates a task; user B tries to read it
        anon_client.post(
            "/auth/register", json={"email": "ea@example.com", "password": "password123"}
        )
        token_a = anon_client.post(
            "/auth/login", data={"username": "ea@example.com", "password": "password123"}
        ).json()["access_token"]
        anon_client.post(
            "/auth/register", json={"email": "eb@example.com", "password": "password123"}
        )
        token_b = anon_client.post(
            "/auth/login", data={"username": "eb@example.com", "password": "password123"}
        ).json()["access_token"]

        task = anon_client.post(
            "/tasks", json={"title": "A's"}, headers={"Authorization": f"Bearer {token_a}"}
        ).json()

        resp = anon_client.get(
            f"/tasks/{task['id']}", headers={"Authorization": f"Bearer {token_b}"}
        )
        assert resp.status_code == 403
        body = resp.json()
        _assert_error_shape(body)
        assert body["error"]["code"] == "FORBIDDEN"

    def test_400_duplicate_email_code(self, anon_client):
        anon_client.post(
            "/auth/register", json={"email": "dup2@example.com", "password": "password123"}
        )
        resp = anon_client.post(
            "/auth/register", json={"email": "dup2@example.com", "password": "password123"}
        )
        assert resp.status_code == 400
        body = resp.json()
        _assert_error_shape(body)
        assert body["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


class TestHealthEndpoints:
    def test_health_returns_ok(self, anon_client):
        resp = anon_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["database"] == "connected"

    def test_ready_returns_ok(self, anon_client):
        resp = anon_client.get("/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_health_requires_no_auth(self, anon_client):
        # No Authorization header at all → still 200
        resp = anon_client.get("/health")
        assert resp.status_code == 200
