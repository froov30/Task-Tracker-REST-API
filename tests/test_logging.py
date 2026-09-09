"""
Structured logging / observability tests (Phase 8, Task 20).
"""

import json


class TestRequestIdHeader:
    def test_response_has_request_id_header(self, client):
        resp = client.get("/tasks")
        assert "x-request-id" in {k.lower() for k in resp.headers}

    def test_inbound_request_id_is_echoed(self, client):
        rid = "test-correlation-id-123"
        resp = client.get("/tasks", headers={"X-Request-ID": rid})
        assert resp.headers["X-Request-ID"] == rid

    def test_request_ids_are_unique(self, client):
        r1 = client.get("/tasks")
        r2 = client.get("/tasks")
        assert r1.headers["X-Request-ID"] != r2.headers["X-Request-ID"]


class TestStructuredLogFields:
    def test_request_completed_log_has_fields(self, client, capsys):
        client.get("/tasks")
        out = capsys.readouterr().out

        # Find the JSON line for the request.completed event
        lines = [ln for ln in out.splitlines() if "request.completed" in ln]
        assert lines, "no request.completed log emitted"

        record = json.loads(lines[-1])
        for field in ("request_id", "method", "path", "status_code", "latency_ms"):
            assert field in record, f"missing {field} in log record"
        assert record["method"] == "GET"
        assert record["path"] == "/api/v1/tasks"

    def test_authenticated_request_logs_user_id(self, client, capsys):
        # `client` fixture is authenticated as user A
        client.get("/tasks")
        out = capsys.readouterr().out
        lines = [ln for ln in out.splitlines() if "request.completed" in ln]
        record = json.loads(lines[-1])
        assert record["user_id"] is not None

    def test_occ_conflict_is_logged(self, client, capsys):
        created = client.post("/tasks", json={"title": "occ log"}).json()
        tid = created["id"]
        client.put(f"/tasks/{tid}", json={"title": "v2", "version": 1})
        # stale update triggers occ.conflict
        client.put(f"/tasks/{tid}", json={"title": "stale", "version": 1})

        out = capsys.readouterr().out
        conflict_lines = [ln for ln in out.splitlines() if "occ.conflict" in ln]
        assert conflict_lines, "no occ.conflict log emitted"
        record = json.loads(conflict_lines[-1])
        assert record["task_id"] == tid
        assert record["expected_version"] == 1
