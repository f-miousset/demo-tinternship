"""The long runs stream, and a stream is never silent.

`POST /api/jobs/search` and `POST /api/applications/{id}/generate` both take
minutes. As single blocking responses they were being cut off by the proxy in
front of the app — Cloudflare answers 524 after 100 seconds of silence — while
the run carried on to completion here, so the browser reported a failure over
results that had already been saved. `POST /api/jobs/import` joined them for the
same reason: one link, but a fetch, a possible Chromium launch and two model
calls.

These tests pin the two halves of the fix: frames keep arriving while a run
thinks, and the events a run already produces come out as progress.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tinternship_backend.agents.investigator import RANKED_STATE_KEY
from tinternship_backend.api import sse
from tinternship_backend.db.models import ArtifactKind
from tinternship_backend.observability.context import (
    RunContext,
    current_run,
    run_context,
)
from tinternship_backend.services import flows


def frames(body: str) -> list[tuple[str, Any]]:
    """Parse an SSE body the way `lib/api.ts` does, comments included."""
    parsed: list[tuple[str, Any]] = []
    for chunk in body.split("\n\n"):
        event_type = "message"
        data: list[str] = []
        for line in chunk.splitlines():
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if data:
            parsed.append((event_type, json.loads("\n".join(data))))
    return parsed


class TestKeepAlive:
    """The whole point: bytes on the wire while nothing is happening."""

    async def test_a_quiet_source_is_padded_with_comment_frames(self):
        async def slow():
            await asyncio.sleep(0.15)
            yield ("phase", {"message": "at last"})

        produced = [frame async for frame in sse.event_stream(slow(), keepalive=0.02)]

        assert produced.count(sse.KEEPALIVE_FRAME) >= 2
        # And the event that was being waited on is not lost to the timeout: the
        # keep-alive interrupts the wait, never the run.
        assert produced[-1].startswith("event: phase")
        assert sum(1 for frame in produced if frame.startswith("event: phase")) == 1

    def test_a_keep_alive_carries_no_data_so_every_client_ignores_it(self):
        assert sse.KEEPALIVE_FRAME.startswith(":")
        assert "data:" not in sse.KEEPALIVE_FRAME
        assert frames(sse.KEEPALIVE_FRAME) == []

    async def test_a_busy_source_is_not_padded(self):
        async def quick():
            yield ("phase", {"message": "one"})
            yield ("phase", {"message": "two"})

        produced = [frame async for frame in sse.event_stream(quick(), keepalive=5)]
        assert produced == [
            sse.format_event("phase", {"message": "one"}),
            sse.format_event("phase", {"message": "two"}),
        ]

    async def test_a_source_that_raises_ends_in_an_error_frame(self):
        async def broken():
            yield ("phase", {"message": "one"})
            raise RuntimeError("the model fell over")

        produced = [frame async for frame in sse.event_stream(broken(), keepalive=5)]
        assert frames("".join(produced))[-1][0] == "error"

    async def test_the_error_frame_says_what_to_do_about_it(self):
        """The 200 is already sent, so nothing else can humanise this one."""

        async def out_of_quota():
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
            yield  # pragma: no cover - makes this a generator

        produced = [frame async for frame in sse.event_stream(out_of_quota(), keepalive=5)]
        (_, data), = frames("".join(produced))
        assert "quota" in data["error"]
        assert "ai.dev/rate-limit" in data["error"]


class TestAmbientRunSurvivesTheStream:
    """The run a stream opens stays ambient for the whole stream.

    Pulling each event in its own task gave the source a fresh copy of the
    context every time, because a generator borrows the context of whatever
    resumes it. `run_context(...)` then set the run on one pull's context and
    reset it on another's: every interview turn ended in `ValueError: <Token
    ...> was created in a different Context`, marking a run that had actually
    succeeded as failed — and `AuditPlugin` had already been reading None, so
    every trace event after the first was filed under no run.
    """

    async def test_every_event_sees_the_run_and_the_stream_ends_clean(self):
        seen: list[int | None] = []

        async def runs():
            with run_context(RunContext(run_id=42, kind="interrogator")):
                for index in range(3):
                    ambient = current_run()
                    seen.append(ambient.run_id if ambient else None)
                    yield ("event", {"index": index})

        produced = [frame async for frame in sse.event_stream(runs(), keepalive=5)]

        assert seen == [42, 42, 42]
        assert [event_type for event_type, _ in frames("".join(produced))] == ["event"] * 3

    async def test_the_run_does_not_leak_into_the_request_that_streamed_it(self):
        async def runs():
            with run_context(RunContext(run_id=42, kind="interrogator")):
                yield ("event", {})

        [frame async for frame in sse.event_stream(runs(), keepalive=5)]

        assert current_run() is None

    async def test_closing_a_stream_from_another_context_is_not_a_failure(self):
        """What a client hanging up mid-run looks like: the generator is left to
        the asyncgen finaliser, which closes it from wherever it happens to be."""

        async def runs():
            with run_context(RunContext(run_id=7, kind="interrogator")):
                yield ("event", {})

        source = runs()
        await asyncio.ensure_future(source.__anext__())  # the run is set in a task…
        await source.aclose()  # …and closed here, where its token means nothing


@pytest.fixture
def fake_investigator(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A run with every side effect stubbed, so only the event shape is tested."""
    seen: dict[str, Any] = {"authors": ["query_planner", "scout", "normaliser", "matcher"]}

    async def fake_stream(agent, **kwargs):
        yield ("run", {"run_id": 7, "session_id": "investigator", "kind": "investigator"})
        for author in seen["authors"]:
            # Several events per turn — the page wants one line per stage.
            yield ("event", {"author": author, "text": "thinking", "partial": False})
            yield ("event", {"author": author, "text": "still thinking", "partial": False})
        yield ("state", {RANKED_STATE_KEY: {"jobs": [{"url": "https://e.test/1"}], "strategy_notes": "n"}})
        yield ("done", {"run_id": 7, "text": "", "invocation_id": "inv-7"})

    async def fake_verify(jobs):
        return jobs, {"ok": len(jobs)}

    async def fake_digest(*_args, **_kwargs):
        return {}

    async def fake_audit(**_kwargs):
        seen["audited"] = True
        return {"overall": 8.0}

    def fake_save(jobs):
        seen["saved"] = len(jobs)
        return {"saved": len(jobs), "created": len(jobs)}

    monkeypatch.setattr(flows, "stream", fake_stream)
    monkeypatch.setattr(flows.verification, "verify_jobs", fake_verify)
    monkeypatch.setattr(flows, "build_digest", fake_digest)
    monkeypatch.setattr(flows, "audit_artifact", fake_audit)
    monkeypatch.setattr(flows, "save_job_postings", fake_save)
    return seen


class TestInvestigatorStream:
    async def test_every_stage_reports_once_and_the_run_ends_on_a_result(
        self, fake_investigator: dict[str, Any]
    ) -> None:
        events = [event async for event in flows.investigator_stream(target_results=5)]
        kinds = [event_type for event_type, _ in events]
        phases = [data["phase"] for event_type, data in events if event_type == "phase"]

        assert kinds[0] == "phase"  # the feedback digest, before any agent runs
        assert "run" in kinds
        assert kinds[-1] == "result"
        assert phases == [
            "feedback",
            "query_planner",
            "scout",
            "normaliser",
            "matcher",
            "verify",
            "save",
            "audit",
        ]

    async def test_a_single_posting_is_not_reported_as_1_postings(
        self, fake_investigator: dict[str, Any]
    ) -> None:
        events = [event async for event in flows.investigator_stream(target_results=5)]
        lines = {data["phase"]: data["message"] for kind, data in events if kind == "phase"}
        assert lines["verify"].startswith("Checking 1 posting link —")
        assert lines["save"] == "Saving 1 posting…"

    async def test_the_result_is_what_the_blocking_endpoint_used_to_return(
        self, fake_investigator: dict[str, Any]
    ) -> None:
        streamed = [data for event_type, data in
                    [e async for e in flows.investigator_stream(target_results=5)]
                    if event_type == "result"][0]
        drained = await flows.run_investigator(target_results=5)

        assert streamed == drained
        assert drained["run_id"] == 7
        assert drained["audit"] == {"overall": 8.0}

    async def test_a_failed_run_stops_there_rather_than_saving_nothing_over_the_list(
        self, fake_investigator: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def failing_stream(agent, **kwargs):
            yield ("run", {"run_id": 7})
            yield ("error", {"run_id": 7, "error": "Gemini quota exceeded."})

        monkeypatch.setattr(flows, "stream", failing_stream)

        events = [event async for event in flows.investigator_stream(target_results=5)]

        assert events[-1] == ("error", {"run_id": 7, "error": "Gemini quota exceeded."})
        assert "saved" not in fake_investigator
        assert "audited" not in fake_investigator

    async def test_draining_a_failed_run_raises_what_the_browser_would_have_been_shown(
        self, fake_investigator: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def failing_stream(agent, **kwargs):
            yield ("error", {"error": "Gemini quota exceeded."})

        monkeypatch.setattr(flows, "stream", failing_stream)

        with pytest.raises(flows.RunFailed, match="quota"):
            await flows.run_investigator(target_results=5)


class TestHrExpertStream:
    @pytest.fixture
    def fake_hr(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        from tinternship_backend.agents.hr_expert import PLAYBOOK_STATE_KEY

        seen: dict[str, Any] = {"playbook": {"sources": ["https://redirect.test/1"]}}

        async def fake_stream(agent, **kwargs):
            yield ("run", {"run_id": 5, "session_id": "hr-expert", "kind": "hr_expert"})
            for author in ("hr_researcher", "playbook_writer"):
                yield ("event", {"author": author, "text": "", "partial": False})
            yield ("state", {PLAYBOOK_STATE_KEY: seen["playbook"]})
            yield ("done", {"run_id": 5, "text": "", "invocation_id": "inv-5"})

        async def fake_resolve(sources):
            return ["https://real.test/1" for _ in sources]

        async def fake_audit(**_kwargs):
            seen["audited"] = True
            return {"overall": 7.7}

        monkeypatch.setattr(flows, "stream", fake_stream)
        monkeypatch.setattr(flows.grounding, "resolve_sources", fake_resolve)
        monkeypatch.setattr(flows, "audit_artifact", fake_audit)
        return seen

    async def test_research_then_synthesis_then_the_work_around_them(
        self, fake_hr: dict[str, Any]
    ) -> None:
        events = [event async for event in flows.hr_expert_stream()]
        phases = [data["phase"] for event_type, data in events if event_type == "phase"]

        assert phases == ["hr_researcher", "playbook_writer", "sources", "save", "audit"]
        assert events[-1][0] == "result"

    async def test_a_single_citation_is_not_reported_as_1_citations(
        self, fake_hr: dict[str, Any]
    ) -> None:
        events = [event async for event in flows.hr_expert_stream()]
        sources = [data for kind, data in events if kind == "phase" and data["phase"] == "sources"]
        assert "the one citation" in sources[0]["message"]

    async def test_the_playbook_is_versioned_and_its_citations_resolved(
        self, fake_hr: dict[str, Any]
    ) -> None:
        result = await flows.run_hr_expert()

        assert result["playbook"]["sources"] == ["https://real.test/1"]
        assert result["prompt"]["version"] >= 1
        assert result["audit"] == {"overall": 7.7}
        assert result["run_id"] == 5

    async def test_a_run_with_no_playbook_says_so_rather_than_versioning_nothing(
        self, fake_hr: dict[str, Any]
    ) -> None:
        """This used to be a ValueError the endpoint turned into a 422. The 200
        is already sent by the time we know, so it has to be an event now."""
        fake_hr["playbook"] = {}

        events = [event async for event in flows.hr_expert_stream()]

        assert events[-1][0] == "error"
        assert "did not produce a playbook" in events[-1][1]["error"]
        assert "audited" not in fake_hr
        with pytest.raises(flows.RunFailed, match="did not produce a playbook"):
            await flows.run_hr_expert()


class TestApplyingStages:
    """Two artifacts in flight at once, so an event's author is the progress."""

    def test_an_author_names_both_the_artifact_and_what_is_happening_to_it(self):
        stages: dict[str, str] = {}
        assert flows._applying_stage("resume_agent", stages) == (ArtifactKind.RESUME, "writing")
        assert flows._applying_stage("resume_agent_critic", stages) == (
            ArtifactKind.RESUME,
            "reviewing",
        )
        assert flows._applying_stage("resume_agent_gate", stages) == (ArtifactKind.RESUME, "gate")
        assert flows._applying_stage("cover_letter_agent", stages) == (
            ArtifactKind.COVER_LETTER,
            "writing",
        )

    def test_the_producer_speaking_after_its_critic_is_a_revision(self):
        assert flows._applying_stage("cover_letter_agent", {ArtifactKind.COVER_LETTER: "gate"}) == (
            ArtifactKind.COVER_LETTER,
            "revising",
        )
        # But a producer taking several turns to write its first draft is not.
        assert flows._applying_stage(
            "cover_letter_agent", {ArtifactKind.COVER_LETTER: "writing"}
        ) == (ArtifactKind.COVER_LETTER, "writing")

    def test_agents_that_are_not_one_of_the_two_are_ignored(self):
        assert flows._applying_stage("applying_team", {}) is None
        assert flows._applying_stage("interrogator", {}) is None

    def test_the_gates_own_verdict_is_the_progress_line(self):
        summary = "Audit resume: 8.2/10 (threshold 7.5) — passed."
        assert flows._stage_message(ArtifactKind.RESUME, "gate", summary) == summary
        assert "résumé" in flows._stage_message(ArtifactKind.RESUME, "gate", "")
        assert "résumé" in flows._stage_message(ArtifactKind.RESUME, "writing", summary)


class TestEndpoints:
    @pytest.fixture()
    def client(self):
        from tinternship_backend.main import app

        return TestClient(app)

    def _application(self) -> int:
        from tinternship_backend.db.engine import session_scope
        from tinternship_backend.db.models import Application, JobPosting

        with session_scope() as session:
            job = JobPosting(dedupe_key="k", title="ML Intern", company="Nimbus", url="https://e.test/1")
            session.add(job)
            session.flush()
            application = Application(job_posting_id=job.id)
            session.add(application)
            session.flush()
            return application.id

    def test_the_search_endpoint_streams(self, client, monkeypatch):
        async def fake(**kwargs):
            yield ("phase", {"phase": "scout", "message": "Searching…"})
            yield ("result", {"jobs": [], "target_results": kwargs.get("target_results")})

        monkeypatch.setattr(flows, "investigator_stream", fake)
        response = client.post("/api/jobs/search?target_results=5")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        assert frames(response.text) == [
            ("phase", {"phase": "scout", "message": "Searching…"}),
            ("result", {"jobs": [], "target_results": 5}),
        ]

    def test_the_import_endpoint_streams(self, client, monkeypatch):
        # A fetch, sometimes a Chromium launch to get past bot protection, then
        # two model calls — comfortably past the 100 seconds a silent proxied
        # request gets, so this one streams too.
        async def fake(url, *_args, **_kwargs):
            yield ("phase", {"phase": "fetch", "message": "Opening the link…"})
            yield ("result", {"job": {"url": url}, "job_id": 4, "run_id": 9})

        monkeypatch.setattr(flows, "import_link_stream", fake)
        response = client.post("/api/jobs/import", json={"url": "https://acme.test/jobs/1"})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert frames(response.text) == [
            ("phase", {"phase": "fetch", "message": "Opening the link…"}),
            ("result", {"job": {"url": "https://acme.test/jobs/1"}, "job_id": 4, "run_id": 9}),
        ]

    def test_the_hr_expert_endpoint_streams(self, client, monkeypatch):
        async def fake(**kwargs):
            yield ("phase", {"phase": "hr_researcher", "message": "Searching…"})
            yield ("result", {"playbook": {}, "run_id": 5})

        monkeypatch.setattr(flows, "hr_expert_stream", fake)
        response = client.post("/api/strategy/hr-expert")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert [event_type for event_type, _ in frames(response.text)] == ["phase", "result"]

    def test_the_generate_endpoint_streams(self, client, monkeypatch, base_documents_installed):
        async def fake(application_id, job_id, language, personalisation="", cover_letter=False, resume=True):
            yield ("phase", {"phase": "writing", "track": "resume", "message": "Writing…"})
            yield ("result", {"artifacts": {}, "run_id": 3})

        monkeypatch.setattr(flows, "applying_stream", fake)
        response = client.post(f"/api/applications/{self._application()}/generate")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert [event_type for event_type, _ in frames(response.text)] == ["phase", "result"]

    def test_what_can_be_rejected_before_the_run_still_answers_with_json(self, client):
        """A stream is a 200 by the time anything is in it, so validation comes first."""
        response = client.post(
            f"/api/applications/{self._application()}/generate", json={"language": "de"}
        )
        assert response.status_code == 400
        assert "de" in response.json()["detail"]

        assert client.post("/api/applications/999999/generate").status_code == 404
