"""A posting the candidate answered never comes back from a search run.

Dismissing a posting is a verdict, validating one puts it on the Tracker, and
throwing that application away afterwards is a third verdict — the one reached
after they looked properly. All three settle the question, so a run that returns
the posting again has spent a slot re-asking it.

`services/context_blocks.known_postings_block` *asks* three of the four agents
not to; this file owns the promise underneath —
`tools/persistence.partition_answered`, called by `investigator_stream` beside
the link drop and, crucially, **before the count is cut**, so every posting
removed for this frees its slot for one of the spares the matcher was asked for.

The pasted-link path is deliberately exempt and `test_link_import.py` owns that:
naming a link yourself outranks an old verdict, whichever of the two trashes it
put the posting in.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tinternship_backend.agents.investigator import RANKED_STATE_KEY
from tinternship_backend.main import create_app
from tinternship_backend.services import flows
from tinternship_backend.tools.persistence import partition_answered, save_job_postings

client = TestClient(create_app())


def posting(index: int, **fields: object) -> dict[str, Any]:
    return {
        "title": f"Job {index}",
        "company": f"Co {index}",
        "url": f"https://co{index}.example/role",
        "url_status": "ok",
        **fields,
    }


def save(index: int, **fields: object) -> int:
    save_job_postings([posting(index, **fields)])
    for job in client.get("/api/jobs", params={"view": "all"}).json()["jobs"]:
        if job["title"] == f"Job {index}":
            return int(job["id"])
    raise AssertionError(f"Job {index} was not saved")


class TestThePartition:
    def test_a_posting_nobody_has_seen_is_kept(self):
        kept, drops = partition_answered([posting(1)])
        assert [job["title"] for job in kept] == ["Job 1"]
        assert drops == {}

    def test_a_dismissed_posting_is_dropped_and_counted(self):
        job_id = save(1)
        client.post(f"/api/jobs/{job_id}/dismiss", params={"dismissed": True})

        kept, drops = partition_answered([posting(1)])
        assert kept == []
        assert drops == {"dismissed": 1}

    def test_a_validated_posting_is_dropped_and_counted(self):
        job_id = save(1)
        client.post("/api/applications", json={"job_posting_id": job_id})

        kept, drops = partition_answered([posting(1)])
        assert kept == []
        assert drops == {"applied": 1}

    def test_a_trashed_application_still_answers_for_its_posting(self):
        # The row survives the trash, so the posting behind it stays answered.
        # If this ever stopped holding, giving up on an application would put
        # its posting back in the pool for the next run to re-propose.
        job_id = save(1)
        application = client.post("/api/applications", json={"job_posting_id": job_id}).json()
        client.post(f"/api/applications/{application['id']}/trash")

        kept, drops = partition_answered([posting(1)])
        assert kept == []
        assert drops == {"trashed": 1}

    def test_a_trashed_application_is_not_counted_as_applied(self):
        # Three verdicts, three tallies. The Jobs page reports this number, and
        # calling a trashed one `applied` would tell the candidate a run
        # re-found something they are tracking when they are not.
        job_id = save(1)
        application = client.post("/api/applications", json={"job_posting_id": job_id}).json()
        client.post(f"/api/applications/{application['id']}/trash")

        _, drops = partition_answered([posting(1)])
        assert "applied" not in drops

    def test_taking_one_back_out_of_the_trash_makes_it_applied_again(self):
        job_id = save(1)
        application = client.post("/api/applications", json={"job_posting_id": job_id}).json()
        client.post(f"/api/applications/{application['id']}/trash")
        client.post(f"/api/applications/{application['id']}/trash", params={"trashed": False})

        _, drops = partition_answered([posting(1)])
        assert drops == {"applied": 1}

    def test_a_posting_already_saved_but_unanswered_is_kept(self):
        # Re-finding one the candidate has not decided on yet is how a posting
        # gets a fresh score and a fresh link check. Only a verdict removes it.
        save(1)
        kept, _ = partition_answered([posting(1)])
        assert [job["title"] for job in kept] == ["Job 1"]

    def test_a_re_listing_under_a_different_title_is_still_the_same_answer(self):
        # It matches by the same rule `save_job_postings` writes by — exact
        # dedupe key, then the fuzzy same-company fallback — because a filter
        # that called a posting new while the writer called it an update would
        # let a dismissal be silently overwritten.
        save_job_postings(
            [
                {
                    "title": "Machine Learning Intern",
                    "company": "LightOn",
                    "url": "https://lighton.example/ml",
                    "url_status": "ok",
                }
            ]
        )
        job_id = client.get("/api/jobs", params={"view": "all"}).json()["jobs"][0]["id"]
        client.post(f"/api/jobs/{job_id}/dismiss", params={"dismissed": True})

        kept, drops = partition_answered(
            [
                {
                    "title": "Machine Learning Intern / Stage Machine Learning",
                    "company": "LightOn",
                    "url": "https://elsewhere.example/ml",
                }
            ]
        )
        assert kept == []
        assert drops == {"dismissed": 1}


@pytest.fixture
def fake_run(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A run whose matcher returns twenty postings, in a fixed order."""
    seen: dict[str, Any] = {}

    async def fake_stream(agent, **kwargs):
        yield ("run", {"run_id": 1, "session_id": "investigator", "kind": "investigator"})
        yield ("state", {RANKED_STATE_KEY: {"jobs": [posting(i) for i in range(20)]}})
        yield ("done", {"run_id": 1, "text": "", "invocation_id": "inv-1"})

    async def fake_verify(jobs):
        seen["verified"] = seen.get("verified", 0) + len(jobs)
        return [{**job, "url_status": "ok"} for job in jobs], {"ok": len(jobs)}

    async def nothing(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(flows, "stream", fake_stream)
    monkeypatch.setattr(flows.verification, "verify_jobs", fake_verify)
    monkeypatch.setattr(flows, "build_digest", nothing)
    monkeypatch.setattr(flows, "audit_artifact", nothing)
    return seen


class TestTheRun:
    async def test_a_dismissed_posting_does_not_come_back(self, fake_run: dict[str, Any]):
        job_id = save(0)
        client.post(f"/api/jobs/{job_id}/dismiss", params={"dismissed": True})

        result = await flows.run_investigator(target_results=5)

        assert "Job 0" not in [job["title"] for job in result["jobs"]]
        assert result["answered_drops"] == {"dismissed": 1}

    async def test_a_validated_posting_does_not_come_back(self, fake_run: dict[str, Any]):
        job_id = save(0)
        client.post("/api/applications", json={"job_posting_id": job_id})

        result = await flows.run_investigator(target_results=5)

        assert "Job 0" not in [job["title"] for job in result["jobs"]]
        assert result["answered_drops"] == {"applied": 1}

    async def test_the_freed_slot_goes_to_a_spare(self, fake_run: dict[str, Any]):
        # The whole reason the drop happens before the cut. Answered postings
        # occupy the top two ranks here; a run that dropped them afterwards
        # would hand back three postings when five were asked for.
        dismissed = save(0)
        client.post(f"/api/jobs/{dismissed}/dismiss", params={"dismissed": True})
        applied = save(1)
        client.post("/api/applications", json={"job_posting_id": applied})

        result = await flows.run_investigator(target_results=5)

        assert len(result["jobs"]) == 5
        assert [job["title"] for job in result["jobs"]] == [f"Job {i}" for i in range(2, 7)]

    async def test_a_trashed_application_does_not_come_back(self, fake_run: dict[str, Any]):
        job_id = save(0)
        application = client.post("/api/applications", json={"job_posting_id": job_id}).json()
        client.post(f"/api/applications/{application['id']}/trash")

        result = await flows.run_investigator(target_results=5)

        assert "Job 0" not in [job["title"] for job in result["jobs"]]
        assert result["answered_drops"] == {"trashed": 1}

    async def test_a_run_with_nothing_answered_says_so_with_an_empty_tally(
        self, fake_run: dict[str, Any]
    ):
        result = await flows.run_investigator(target_results=5)
        assert result["answered_drops"] == {}
        assert len(result["jobs"]) == 5
