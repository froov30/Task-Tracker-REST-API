"""
Automated test suite for the Task Tracker REST API — Phase 6 mandatory gate.

Coverage areas (per TRD §7 and IMPLEMENTATION_PLAN Phase 6):
  1. CRUD happy path: create → get → update → delete → 404-after-delete
  2. Filtering + sorting: combined filters return correct subset; sort order verified
  3. Concurrency conflict: stale-version update returns 409
  4. Validation edge cases: missing title, invalid status, invalid sort_by,
     missing version on PUT — all 422
"""

from datetime import UTC, datetime, timedelta


def _today():
    """Timezone-aware today's date (avoids ruff DTZ011)."""
    return datetime.now(tz=UTC).date()


# ---------------------------------------------------------------------------
# 1. CRUD Happy Path
# ---------------------------------------------------------------------------


class TestCRUDHappyPath:
    """create → get → update → delete → 404-after-delete"""

    def test_full_lifecycle(self, client):
        # --- CREATE ---
        create_resp = client.post(
            "/tasks",
            json={"title": "Write tests", "description": "Phase 6"},
        )
        assert create_resp.status_code == 201
        task = create_resp.json()
        task_id = task["id"]
        assert task["title"] == "Write tests"
        assert task["description"] == "Phase 6"
        assert task["status"] == "pending"
        assert task["version"] == 1

        # --- GET single ---
        get_resp = client.get(f"/tasks/{task_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == task_id
        assert get_resp.json()["title"] == "Write tests"

        # --- GET list (contains our task) ---
        list_resp = client.get("/tasks")
        assert list_resp.status_code == 200
        ids = [t["id"] for t in list_resp.json()]
        assert task_id in ids

        # --- UPDATE ---
        update_resp = client.put(
            f"/tasks/{task_id}",
            json={
                "title": "Write tests (updated)",
                "status": "in_progress",
                "version": 1,
            },
        )
        assert update_resp.status_code == 200
        updated = update_resp.json()
        assert updated["title"] == "Write tests (updated)"
        assert updated["status"] == "in_progress"
        assert updated["version"] == 2  # incremented
        assert updated["description"] == "Phase 6"  # untouched field preserved

        # --- DELETE ---
        delete_resp = client.delete(f"/tasks/{task_id}")
        assert delete_resp.status_code == 204

        # --- 404 after delete ---
        gone_resp = client.get(f"/tasks/{task_id}")
        assert gone_resp.status_code == 404

    def test_create_with_due_date(self, client):
        """Ensure due_date is stored and returned correctly."""
        due = (_today() + timedelta(days=7)).isoformat()
        resp = client.post(
            "/tasks",
            json={"title": "Future task", "due_date": due},
        )
        assert resp.status_code == 201
        assert resp.json()["due_date"] == due

    def test_create_minimal(self, client):
        """Only the required `title` field — everything else defaults."""
        resp = client.post("/tasks", json={"title": "Bare minimum"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["title"] == "Bare minimum"
        assert body["description"] is None
        assert body["due_date"] is None
        assert body["status"] == "pending"
        assert body["version"] == 1

    def test_partial_update_preserves_fields(self, client):
        """PUT with only `version` (and nothing else) must NOT wipe fields."""
        resp = client.post(
            "/tasks",
            json={"title": "Keep me", "description": "Don't erase"},
        )
        task_id = resp.json()["id"]

        update_resp = client.put(
            f"/tasks/{task_id}",
            json={"version": 1},
        )
        assert update_resp.status_code == 200
        body = update_resp.json()
        assert body["title"] == "Keep me"
        assert body["description"] == "Don't erase"
        assert body["version"] == 2

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/tasks/99999")
        assert resp.status_code == 404

    def test_get_nonexistent_returns_404(self, client):
        resp = client.get("/tasks/99999")
        assert resp.status_code == 404

    def test_update_nonexistent_returns_404(self, client):
        resp = client.put("/tasks/99999", json={"version": 1})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2. Filtering + Sorting
# ---------------------------------------------------------------------------


class TestFilteringAndSorting:
    """Create tasks with different statuses and due_dates, then verify
    combined filters and sort orders."""

    def _seed_tasks(self, client):
        """Insert a known set of tasks for filter/sort testing."""
        today = _today()
        tasks = [
            {
                "title": "Alpha",
                "due_date": (today + timedelta(days=1)).isoformat(),
            },
            {
                "title": "Beta",
                "due_date": (today + timedelta(days=5)).isoformat(),
            },
            {
                "title": "Gamma",
                "due_date": (today + timedelta(days=10)).isoformat(),
            },
        ]
        created = []
        for t in tasks:
            resp = client.post("/tasks", json=t)
            assert resp.status_code == 201
            created.append(resp.json())

        # Mark Beta as completed, Gamma as in_progress
        client.put(
            f"/tasks/{created[1]['id']}",
            json={"status": "completed", "version": 1},
        )
        client.put(
            f"/tasks/{created[2]['id']}",
            json={"status": "in_progress", "version": 1},
        )
        return created

    def test_filter_by_status(self, client):
        self._seed_tasks(client)

        resp = client.get("/tasks", params={"status": "completed"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["title"] == "Beta"

    def test_filter_by_status_pending(self, client):
        self._seed_tasks(client)

        resp = client.get("/tasks", params={"status": "pending"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["title"] == "Alpha"

    def test_filter_by_due_before(self, client):
        self._seed_tasks(client)
        today = _today()
        cutoff = (today + timedelta(days=3)).isoformat()

        resp = client.get("/tasks", params={"due_before": cutoff})
        assert resp.status_code == 200
        results = resp.json()
        titles = [t["title"] for t in results]
        assert "Alpha" in titles
        assert "Gamma" not in titles

    def test_filter_by_due_after(self, client):
        self._seed_tasks(client)
        today = _today()
        cutoff = (today + timedelta(days=6)).isoformat()

        resp = client.get("/tasks", params={"due_after": cutoff})
        assert resp.status_code == 200
        results = resp.json()
        titles = [t["title"] for t in results]
        assert "Gamma" in titles
        assert "Alpha" not in titles

    def test_combined_filter_status_and_due_before(self, client):
        """status + due_before together should return the intersection."""
        self._seed_tasks(client)
        today = _today()
        cutoff = (today + timedelta(days=15)).isoformat()

        resp = client.get(
            "/tasks",
            params={"status": "completed", "due_before": cutoff},
        )
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 1
        assert results[0]["title"] == "Beta"

    def test_sort_by_due_date_asc(self, client):
        self._seed_tasks(client)

        resp = client.get(
            "/tasks",
            params={"sort_by": "due_date", "sort_order": "asc"},
        )
        assert resp.status_code == 200
        results = resp.json()
        due_dates = [t["due_date"] for t in results]
        assert due_dates == sorted(due_dates)

    def test_sort_by_due_date_desc(self, client):
        self._seed_tasks(client)

        resp = client.get(
            "/tasks",
            params={"sort_by": "due_date", "sort_order": "desc"},
        )
        assert resp.status_code == 200
        results = resp.json()
        due_dates = [t["due_date"] for t in results]
        assert due_dates == sorted(due_dates, reverse=True)

    def test_sort_by_title_asc(self, client):
        self._seed_tasks(client)

        resp = client.get(
            "/tasks",
            params={"sort_by": "title", "sort_order": "asc"},
        )
        assert resp.status_code == 200
        results = resp.json()
        titles = [t["title"] for t in results]
        assert titles == sorted(titles)

    def test_empty_result_on_no_match(self, client):
        self._seed_tasks(client)

        resp = client.get("/tasks", params={"status": "cancelled"})
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# 3. Concurrency Conflict (Optimistic Locking)
# ---------------------------------------------------------------------------


class TestConcurrencyConflict:
    """Stale-version update must return 409 and leave the row unmodified."""

    def test_stale_version_returns_409(self, client):
        # Create task (version=1)
        resp = client.post("/tasks", json={"title": "Concurrent target"})
        task_id = resp.json()["id"]
        assert resp.json()["version"] == 1

        # First update succeeds (version 1 → 2)
        update1 = client.put(
            f"/tasks/{task_id}",
            json={"title": "Updated once", "version": 1},
        )
        assert update1.status_code == 200
        assert update1.json()["version"] == 2

        # Second update with stale version=1 → 409
        update2 = client.put(
            f"/tasks/{task_id}",
            json={"title": "Should fail", "version": 1},
        )
        assert update2.status_code == 409

        # Verify the row was NOT modified by the rejected update
        check = client.get(f"/tasks/{task_id}")
        assert check.json()["title"] == "Updated once"  # unchanged
        assert check.json()["version"] == 2  # unchanged

    def test_correct_version_still_succeeds_after_conflict(self, client):
        """After a 409, sending the current version should succeed."""
        resp = client.post("/tasks", json={"title": "Retry target"})
        task_id = resp.json()["id"]

        # v1 → v2
        client.put(
            f"/tasks/{task_id}",
            json={"title": "First update", "version": 1},
        )

        # stale → 409
        stale = client.put(
            f"/tasks/{task_id}",
            json={"title": "Stale", "version": 1},
        )
        assert stale.status_code == 409

        # correct version → 200
        retry = client.put(
            f"/tasks/{task_id}",
            json={"title": "Correct retry", "version": 2},
        )
        assert retry.status_code == 200
        assert retry.json()["title"] == "Correct retry"
        assert retry.json()["version"] == 3


# ---------------------------------------------------------------------------
# 4. Validation Edge Cases (all expect 422)
# ---------------------------------------------------------------------------


class TestValidationEdgeCases:
    """Invalid inputs should be rejected with 422 before reaching the DB."""

    def test_missing_title_on_create(self, client):
        resp = client.post("/tasks", json={"description": "No title"})
        assert resp.status_code == 422

    def test_empty_title_on_create(self, client):
        resp = client.post("/tasks", json={"title": ""})
        assert resp.status_code == 422

    def test_whitespace_only_title_on_create(self, client):
        resp = client.post("/tasks", json={"title": "   "})
        assert resp.status_code == 422

    def test_invalid_status_value_on_update(self, client):
        resp = client.post("/tasks", json={"title": "Valid"})
        task_id = resp.json()["id"]

        update = client.put(
            f"/tasks/{task_id}",
            json={"status": "INVALID_STATUS", "version": 1},
        )
        assert update.status_code == 422

    def test_invalid_sort_by_on_list(self, client):
        resp = client.get("/tasks", params={"sort_by": "nonexistent_column"})
        assert resp.status_code == 422

    def test_invalid_sort_order_on_list(self, client):
        resp = client.get("/tasks", params={"sort_order": "sideways"})
        assert resp.status_code == 422

    def test_missing_version_on_update(self, client):
        resp = client.post("/tasks", json={"title": "Need version"})
        task_id = resp.json()["id"]

        update = client.put(
            f"/tasks/{task_id}",
            json={"title": "Forgot version"},
        )
        assert update.status_code == 422

    def test_version_zero_rejected(self, client):
        resp = client.post("/tasks", json={"title": "Version zero"})
        task_id = resp.json()["id"]

        update = client.put(
            f"/tasks/{task_id}",
            json={"title": "Zero", "version": 0},
        )
        assert update.status_code == 422

    def test_invalid_status_on_filter(self, client):
        resp = client.get("/tasks", params={"status": "bogus"})
        assert resp.status_code == 422

    def test_sql_injection_via_sort_by(self, client):
        """sort_by is Literal-guarded — arbitrary SQL should 422."""
        resp = client.get(
            "/tasks",
            params={"sort_by": "title; DROP TABLE tasks;--"},
        )
        assert resp.status_code == 422
