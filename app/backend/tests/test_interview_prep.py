"""Reaching `interview` starts a run, and that run may not make things up.

The interview brief is the artifact with the most to lose from invention: a
fabricated line on a résumé is embarrassing, a fabricated funding round gets
said out loud to someone who knows the answer. So the gate checks in Python
that the brief cites *something* before the Critic is asked whether the
citations say what the brief claims they say.

Also covered here: what the coach is handed that nothing else has — the
posting's own strengths and risks, and the gaps the résumé already conceded.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tinternship_backend.agents.interview_prep import (
    INTERVIEW_PREP_STATE_KEY,
    build_interview_prep,
    package_gaps_block,
    unsourced_company_claims,
)
from tinternship_backend.db.engine import session_scope
from tinternship_backend.db.models import (
    Application,
    ApplicationArtifact,
    ApplicationStatus,
    ArtifactKind,
    JobPosting,
)
from tinternship_backend.services import flows


def _seed(status: str = ApplicationStatus.HR_PRE_CALL) -> tuple[int, int]:
    with session_scope() as session:
        job = JobPosting(
            dedupe_key="nimbus-ml-intern",
            title="ML Intern",
            company="Nimbus Labs",
            url="https://nimbus.test/jobs/1",
            summary="Six months building training pipelines.",
            strengths=["Python and SQL are on the profile"],
            risks=["No PyTorch anywhere in the profile"],
            requirements=["PyTorch", "Python"],
            fit_score=7.4,
            fit_rationale="Strong on data engineering, thin on ML frameworks.",
            confidence="high",
        )
        session.add(job)
        session.flush()
        application = Application(job_posting_id=job.id, status=status, language="en")
        session.add(application)
        session.flush()
        return application.id, job.id


class TestTheHardCheck:
    """A brief that describes a company it never looked up is rejected."""

    def test_company_claims_without_a_single_source_are_refused(self):
        problem = unsourced_company_claims(
            {
                "company_brief": "Nimbus raised a $40M Series B in March.",
                "recent_developments": ["Acquired a vision startup."],
                "sources": [],
            }
        )
        assert "cites no sources" in problem

    def test_one_real_source_is_enough_for_the_gate_to_pass_it_on(self):
        """Presence, not correctness — whether the source *says* it is the
        Critic's job, and a hard check that tried to judge that would be a
        second, worse Critic."""
        assert (
            unsourced_company_claims(
                {
                    "company_brief": "Nimbus builds training infrastructure.",
                    "sources": [{"url": "https://nimbus.test/about"}],
                }
            )
            == ""
        )

    def test_a_brief_that_claims_nothing_about_the_employer_is_not_punished(self):
        """"The research found little about this employer" is an honest answer
        for a small company with no press, and must not be forced into
        inventing a citation to get through the gate."""
        assert unsourced_company_claims({"company_brief": "", "recent_developments": []}) == ""

    def test_a_source_entry_with_no_url_does_not_count(self):
        problem = unsourced_company_claims(
            {"company_brief": "Nimbus is huge.", "sources": [{"title": "Their site", "url": " "}]}
        )
        assert "cites no sources" in problem

    def test_the_gate_carries_it(self):
        _application_id, job_id = _seed()
        prep = build_interview_prep(job_id=job_id, application_id=1)
        gate = prep.sub_agents[1].sub_agents[2]
        assert gate._hard_check is unsourced_company_claims


class TestWhatTheCoachIsGiven:
    @pytest.mark.asyncio
    async def test_the_postings_own_strengths_and_risks_reach_the_researcher(self):
        """The app scored this posting when it found it. Re-deriving that
        assessment in the interview brief would produce a different one for no
        reason — and `risks` is exactly the list of things the interview will
        press on."""
        application_id, job_id = _seed()
        researcher = build_interview_prep(
            job_id=job_id, application_id=application_id
        ).sub_agents[0]

        class Ctx:
            state: dict = {}

        instruction = await researcher.instruction(Ctx())
        assert "No PyTorch anywhere in the profile" in instruction
        assert "Nimbus Labs" in instruction

    def test_the_resumes_declared_gaps_are_handed_over(self):
        application_id, _job_id = _seed()
        with session_scope() as session:
            session.add(
                ApplicationArtifact(
                    application_id=application_id,
                    kind=ArtifactKind.RESUME,
                    version=1,
                    content={
                        "keywords_missing": ["PyTorch", "Published research"],
                        "gap_analysis": ["No ML framework experience on record."],
                    },
                )
            )

        block = package_gaps_block(application_id)
        assert "PyTorch" in block
        assert "No ML framework experience on record." in block

    def test_the_latest_resume_wins_over_an_earlier_one(self):
        application_id, _job_id = _seed()
        with session_scope() as session:
            for version, missing in ((1, "Fortran"), (2, "PyTorch")):
                session.add(
                    ApplicationArtifact(
                        application_id=application_id,
                        kind=ArtifactKind.RESUME,
                        version=version,
                        content={"keywords_missing": [missing]},
                    )
                )

        block = package_gaps_block(application_id)
        assert "PyTorch" in block
        assert "Fortran" not in block

    def test_an_application_with_no_package_contributes_nothing(self):
        """Tracked by hand, never generated. `compose` drops an empty block."""
        application_id, _job_id = _seed()
        assert package_gaps_block(application_id) == ""


class TestTheFlow:
    @pytest.fixture()
    def client(self):
        from tinternship_backend.main import app

        return TestClient(app)

    def test_the_endpoint_streams(self, client, monkeypatch):
        application_id, _job_id = _seed()

        async def fake(app_id):
            yield ("phase", {"phase": "researching", "message": "Searching…"})
            yield ("result", {"artifact": {"id": 1}, "run_id": 4})

        monkeypatch.setattr(flows, "interview_prep_stream", fake)
        response = client.post(f"/api/applications/{application_id}/interview-prep")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

    def test_a_missing_application_is_a_404_and_not_a_stream(self, client):
        assert client.post("/api/applications/999999/interview-prep").status_code == 404

    async def test_the_language_is_stamped_on_rather_than_taken_from_the_model(
        self, monkeypatch
    ):
        """Same rule as the package's artifacts: which language this was written
        in is a fact about the request, and a model narrating into a free-text
        code field can end the JSON object early."""
        application_id, _job_id = _seed()
        with session_scope() as session:
            application = session.get(Application, application_id)
            application.language = "fr"
            session.add(application)

        async def fake_stream(agent, **kwargs):
            # 0 rather than an id: `_save_artifact` turns a falsy run id into a
            # NULL foreign key, which is the documented "saved, but no trace to
            # link it to" path and keeps this test off the AgentRun table.
            yield ("run", {"run_id": 0})
            yield (
                "state",
                {INTERVIEW_PREP_STATE_KEY: {"company_brief": "Nimbus.", "language": "de"}},
            )
            yield ("done", {"invocation_id": "inv-11"})

        async def no_resolution(sources):
            return sources

        monkeypatch.setattr(flows, "stream", fake_stream)
        monkeypatch.setattr(flows.grounding, "resolve_sources", no_resolution)

        result = await flows.run_interview_prep(application_id)
        assert result["artifact"]["content"]["language"] == "fr"

    async def test_a_run_that_produced_nothing_reports_an_error_not_an_empty_brief(
        self, monkeypatch
    ):
        application_id, _job_id = _seed()

        async def fake_stream(agent, **kwargs):
            yield ("run", {"run_id": 12})
            yield ("state", {})
            yield ("done", {"invocation_id": "inv-12"})

        monkeypatch.setattr(flows, "stream", fake_stream)

        events = [event async for event in flows.interview_prep_stream(application_id)]
        assert events[-1][0] == "error"

    async def test_every_saved_brief_is_a_new_version(self, monkeypatch):
        """A second interview at the same employer — the technical round after
        the screening call — must not overwrite what was written for the first."""
        application_id, _job_id = _seed()

        async def fake_stream(agent, **kwargs):
            yield ("run", {"run_id": 0})
            yield ("state", {INTERVIEW_PREP_STATE_KEY: {"company_brief": "Nimbus."}})
            yield ("done", {"invocation_id": "inv-13"})

        async def no_resolution(sources):
            return sources

        monkeypatch.setattr(flows, "stream", fake_stream)
        monkeypatch.setattr(flows.grounding, "resolve_sources", no_resolution)

        first = await flows.run_interview_prep(application_id)
        second = await flows.run_interview_prep(application_id)
        assert (first["artifact"]["version"], second["artifact"]["version"]) == (1, 2)

    def test_the_history_names_the_status_and_the_notes(self):
        application_id, _job_id = _seed()
        with session_scope() as session:
            application = session.get(Application, application_id)
            application.notes = "Recruiter call booked for Thursday."
            session.add(application)

        history = flows.interview_history(application_id)
        assert "Recruiter call booked for Thursday." in history
        assert "hr_pre_call" in history
