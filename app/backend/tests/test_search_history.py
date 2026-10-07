"""Account-based history of sent search queries for the Jobs chat (Ask the agents)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from tinternship_backend.db.engine import session_scope
from tinternship_backend.db.models import AgentRun, RunKind, utcnow
from tinternship_backend.main import app
from tinternship_backend.services import search_history


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_history():
    search_history.clear_history()
    yield
    search_history.clear_history()


class TestSearchHistoryService:
    def test_record_and_list_query(self):
        item = search_history.record_query("Mistral AI in Paris")
        assert item is not None
        assert item.text == "Mistral AI in Paris"

        history = search_history.list_history()
        assert len(history) == 1
        assert history[0].text == "Mistral AI in Paris"

    def test_record_ignores_empty_query(self):
        assert search_history.record_query("   ") is None
        assert len(search_history.list_history()) == 0

    def test_deduplicates_case_insensitively_and_moves_to_top(self):
        t1 = utcnow() - timedelta(minutes=10)
        t2 = utcnow() - timedelta(minutes=5)
        t3 = utcnow()

        search_history.record_query("First Query", created_at=t1, updated_at=t1)
        search_history.record_query("Second Query", created_at=t2, updated_at=t2)
        # Duplicate with different case
        search_history.record_query("first query", created_at=t3, updated_at=t3)

        history = search_history.list_history()
        assert len(history) == 2
        # Freshest is now first query
        assert history[0].text == "first query"
        assert history[1].text == "Second Query"

    def test_prunes_past_max_items(self):
        for i in range(55):
            search_history.record_query(f"Query {i}")

        history = search_history.list_history(limit=100)
        assert len(history) == search_history.MAX_HISTORY_ITEMS

    def test_delete_and_clear(self):
        item1 = search_history.record_query("To keep")
        item2 = search_history.record_query("To delete")
        assert item1 is not None and item2 is not None

        assert search_history.delete_query(item2.id) is True
        history = search_history.list_history()
        assert len(history) == 1
        assert history[0].text == "To keep"

        assert search_history.clear_history() == 1
        assert len(search_history.list_history()) == 0

    def test_backfill_from_agent_runs(self):
        with session_scope() as session:
            run1 = AgentRun(
                kind=RunKind.INVESTIGATOR,
                label="run 1",
                input={"focus": "Databricks internships", "target_results": 15},
                started_at=utcnow() - timedelta(days=1),
            )
            run2 = AgentRun(
                kind=RunKind.INVESTIGATOR,
                label="run 2",
                input={"focus": "Mistral AI", "target_results": 15},
                started_at=utcnow(),
            )
            run3 = AgentRun(
                kind=RunKind.INVESTIGATOR,
                label="unsteered run",
                input={"target_results": 15},
                started_at=utcnow(),
            )
            session.add(run1)
            session.add(run2)
            session.add(run3)

        added = search_history.backfill_from_runs()
        assert added == 2

        history = search_history.list_history()
        assert len(history) == 2
        texts = [item.text for item in history]
        assert "Mistral AI" in texts
        assert "Databricks internships" in texts

        # Idempotent: once queries exist, backfill does not duplicate
        assert search_history.backfill_from_runs() == 0


class TestSearchHistoryApi:
    def test_history_endpoints_flow(self, client: TestClient):
        # 1. Initially empty
        res = client.get("/api/jobs/search/history")
        assert res.status_code == 200
        assert res.json() == {"items": []}

        # 2. Add query
        res = client.post("/api/jobs/search/history", json={"text": "Deep learning in Lyon"})
        assert res.status_code == 200
        data = res.json()
        assert data["text"] == "Deep learning in Lyon"
        assert "id" in data
        assert "timestamp" in data
        query_id = int(data["id"])

        # 3. List queries
        res = client.get("/api/jobs/search/history")
        assert res.status_code == 200
        items = res.json()["items"]
        assert len(items) == 1
        assert items[0]["text"] == "Deep learning in Lyon"

        # 4. Sync queries
        res = client.post(
            "/api/jobs/search/history/sync",
            json={
                "items": [
                    {"text": "Remote AI role", "timestamp": 1725500000000},
                    {"text": "deep learning in lyon", "timestamp": 1725510000000},
                ]
            },
        )
        assert res.status_code == 200
        items = res.json()["items"]
        assert len(items) == 2

        # 5. Delete specific query
        res = client.delete(f"/api/jobs/search/history/{query_id}")
        assert res.status_code == 200
        assert res.json()["deleted"] is True

        # 6. Clear all
        res = client.delete("/api/jobs/search/history")
        assert res.status_code == 200
        assert res.json()["deleted_count"] >= 1

        res = client.get("/api/jobs/search/history")
        assert res.json() == {"items": []}
