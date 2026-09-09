"""
Pagination tests for GET /tasks.

Covers:
  - Envelope shape (items, total, page, page_size, pages present)
  - page=1 / page=2 slicing with known data
  - page_size controls item count
  - total reflects actual matching count (not page count)
  - pages computed correctly (ceil division)
  - page beyond last page returns empty items, correct total
  - page_size=200 rejected with 422 (exceeds max of 100)
  - page=0 rejected with 422 (must be ge=1)
  - Pagination composes correctly with status filter
"""


def _create_tasks(client, n: int) -> list[dict]:
    """Create n tasks with sequential titles and return their payloads."""
    created = []
    for i in range(1, n + 1):
        resp = client.post("/tasks", json={"title": f"Task {i:03d}"})
        assert resp.status_code == 201
        created.append(resp.json())
    return created


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------

class TestPaginatedEnvelopeShape:
    """The response always has the five required envelope fields."""

    def test_empty_db_returns_valid_envelope(self, client):
        resp = client.get("/tasks")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "page_size" in body
        assert "pages" in body

    def test_defaults_are_page1_pagesize20(self, client):
        resp = client.get("/tasks")
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 1
        assert body["page_size"] == 20

    def test_envelope_reflects_requested_page_and_page_size(self, client):
        resp = client.get("/tasks", params={"page": 2, "page_size": 5})
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 2
        assert body["page_size"] == 5


# ---------------------------------------------------------------------------
# Slicing correctness
# ---------------------------------------------------------------------------

class TestPaginationSlicing:
    """Items on each page are the correct slice of the full ordered set."""

    def test_page1_returns_first_n_items(self, client):
        _create_tasks(client, 12)
        resp = client.get("/tasks", params={"page": 1, "page_size": 5, "sort_by": "title", "sort_order": "asc"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 5
        assert body["total"] == 12
        # First page ascending by title: Task 001 … Task 005
        assert body["items"][0]["title"] == "Task 001"
        assert body["items"][4]["title"] == "Task 005"

    def test_page2_returns_next_slice(self, client):
        _create_tasks(client, 12)
        resp = client.get("/tasks", params={"page": 2, "page_size": 5, "sort_by": "title", "sort_order": "asc"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 5
        assert body["items"][0]["title"] == "Task 006"
        assert body["items"][4]["title"] == "Task 010"

    def test_last_page_returns_remainder(self, client):
        _create_tasks(client, 12)
        resp = client.get("/tasks", params={"page": 3, "page_size": 5, "sort_by": "title", "sort_order": "asc"})
        assert resp.status_code == 200
        body = resp.json()
        # 12 tasks, page_size=5 → page 3 has 2 items (Task 011, Task 012)
        assert len(body["items"]) == 2
        assert body["items"][0]["title"] == "Task 011"
        assert body["items"][1]["title"] == "Task 012"

    def test_page_beyond_last_returns_empty_items(self, client):
        _create_tasks(client, 3)
        resp = client.get("/tasks", params={"page": 99, "page_size": 20})
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 3   # total still reflects all matching rows


# ---------------------------------------------------------------------------
# Total and pages calculation
# ---------------------------------------------------------------------------

class TestPaginationMath:
    """total and pages fields are always accurate."""

    def test_total_matches_actual_count(self, client):
        _create_tasks(client, 7)
        resp = client.get("/tasks", params={"page": 1, "page_size": 3})
        assert resp.json()["total"] == 7

    def test_pages_is_ceil_of_total_over_page_size(self, client):
        _create_tasks(client, 7)
        resp = client.get("/tasks", params={"page": 1, "page_size": 3})
        body = resp.json()
        # ceil(7/3) = 3
        assert body["pages"] == 3

    def test_pages_exact_division(self, client):
        _create_tasks(client, 6)
        resp = client.get("/tasks", params={"page": 1, "page_size": 3})
        # ceil(6/3) = 2
        assert resp.json()["pages"] == 2

    def test_total_zero_on_empty_db(self, client):
        resp = client.get("/tasks")
        body = resp.json()
        assert body["total"] == 0
        assert body["pages"] == 0
        assert body["items"] == []

    def test_items_never_exceeds_page_size(self, client):
        _create_tasks(client, 25)
        resp = client.get("/tasks", params={"page": 1, "page_size": 10})
        assert len(resp.json()["items"]) == 10


# ---------------------------------------------------------------------------
# Pagination + filters compose correctly
# ---------------------------------------------------------------------------

class TestPaginationWithFilters:
    """Pagination respects active filters — total counts filtered rows only."""

    def test_total_reflects_filtered_subset(self, client):
        # Create 8 tasks; move first 3 to in_progress (valid pending→in_progress)
        ids = [client.post("/tasks", json={"title": f"T{i}"}).json()["id"] for i in range(8)]
        for task_id in ids[:3]:
            client.put(f"/tasks/{task_id}", json={"status": "in_progress", "version": 1})

        resp = client.get(
            "/tasks", params={"status": "in_progress", "page": 1, "page_size": 20}
        )
        body = resp.json()
        assert body["total"] == 3
        assert all(t["status"] == "in_progress" for t in body["items"])

    def test_filtered_pagination_slices_correctly(self, client):
        # 10 pending tasks
        _create_tasks(client, 10)
        # Move 2 to in_progress (valid transition from pending)
        list_resp = client.get("/tasks", params={"page": 1, "page_size": 20}).json()
        for task in list_resp["items"][:2]:
            client.put(
                f"/tasks/{task['id']}",
                json={"status": "in_progress", "version": task["version"]},
            )

        # Page 1 of pending tasks, page_size=3
        resp = client.get(
            "/tasks",
            params={"status": "pending", "page": 1, "page_size": 3},
        )
        body = resp.json()
        assert body["total"] == 8           # 10 - 2 moved to in_progress
        assert len(body["items"]) == 3
        assert all(t["status"] == "pending" for t in body["items"])


# ---------------------------------------------------------------------------
# Validation — invalid params rejected before hitting the DB
# ---------------------------------------------------------------------------

class TestPaginationValidation:
    """Out-of-range pagination params return 422."""

    def test_page_size_above_max_rejected(self, client):
        resp = client.get("/tasks", params={"page_size": 200})
        assert resp.status_code == 422

    def test_page_size_at_max_accepted(self, client):
        resp = client.get("/tasks", params={"page_size": 100})
        assert resp.status_code == 200

    def test_page_zero_rejected(self, client):
        resp = client.get("/tasks", params={"page": 0})
        assert resp.status_code == 422

    def test_page_size_zero_rejected(self, client):
        resp = client.get("/tasks", params={"page_size": 0})
        assert resp.status_code == 422

    def test_negative_page_rejected(self, client):
        resp = client.get("/tasks", params={"page": -1})
        assert resp.status_code == 422
