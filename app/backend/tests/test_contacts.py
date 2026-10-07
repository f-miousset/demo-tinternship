"""Opening an application looks for people to write to, and may not invent any.

A shortlist of confident, plausible, entirely fabricated people is
indistinguishable from a good one until the candidate messages a stranger. So
the gate checks in Python that every name carries the page that named it, before
the Critic is asked whether those pages say what the shortlist claims — and the
flow proves every link afterwards, which is `test_outreach.py`.

Covered here: the hard check, what the scout is handed that nothing else has,
the run's wiring, and the message the candidate asks for one person at a time.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from tinternship_backend.agents.contacts import (
    CONTACTS_STATE_KEY,
    OPENING_STATE_KEY,
    build_contacts,
    build_opener,
    schools_block,
    unsourced_people,
)
from tinternship_backend.agents.schemas import EducationEntry, MasterProfile
from tinternship_backend.db.engine import get_engine, session_scope
from tinternship_backend.db.models import (
    Application,
    ApplicationArtifact,
    ApplicationStatus,
    ArtifactKind,
    JobPosting,
)
from tinternship_backend.services import flows, outreach
from tinternship_backend.services.profile_store import save_profile


def _seed(status: str = ApplicationStatus.SAVED) -> tuple[int, int]:
    with session_scope() as session:
        job = JobPosting(
            dedupe_key="nimbus-ml-intern",
            title="ML Intern",
            company="Nimbus Labs",
            url="https://nimbus.test/jobs/1",
            summary="Six months building training pipelines.",
            keywords=["computer vision"],
            requirements=["PyTorch"],
            fit_score=7.4,
            confidence="high",
        )
        session.add(job)
        session.flush()
        application = Application(job_posting_id=job.id, status=status, language="en")
        session.add(application)
        session.flush()
        return application.id, job.id


def _profile() -> None:
    save_profile(
        MasterProfile(
            full_name="Alex Martin",
            education=[EducationEntry(degree="MSc", institution="INSA Lyon")],
        )
    )


class TestTheHardCheck:
    def test_a_name_with_no_page_behind_it_is_refused(self):
        problem = unsourced_people(
            {"people": [{"name": "Claire Dupont", "role": "Campus Manager", "evidence_url": ""}]}
        )
        assert "Claire Dupont" in problem
        assert "evidence_url" in problem

    def test_a_sourced_name_passes(self):
        assert (
            unsourced_people(
                {"people": [{"name": "Claire Dupont", "evidence_url": "https://nimbus.test/team"}]}
            )
            == ""
        )

    def test_finding_nobody_is_not_a_failure(self):
        """A small employer with no findable staff is an ordinary result, and
        forcing a citation out of it would only produce a fabricated one. The
        searches the app builds work with no names at all."""
        assert unsourced_people({"people": [], "notes": "Nobody is published."}) == ""

    def test_something_that_is_not_a_url_does_not_count_as_a_source(self):
        problem = unsourced_people(
            {"people": [{"name": "Claire Dupont", "evidence_url": "their team page"}]}
        )
        assert "Claire Dupont" in problem

    def test_the_gate_carries_it(self):
        _application_id, job_id = _seed()
        contacts = build_contacts(job_id=job_id)
        gate = contacts.sub_agents[1].sub_agents[2]
        assert gate._hard_check is unsourced_people


class TestWhatTheScoutIsGiven:
    def test_the_schools_are_pulled_out_of_the_profile_and_given_a_reason(self):
        """They are already in the profile JSON, and that is the problem: buried
        in an education array they read as biography rather than as the first
        search to run."""
        _profile()
        block = schools_block()
        assert "INSA Lyon" in block
        assert "alumni" in block.lower()

    def test_no_schools_means_no_block_rather_than_an_empty_heading(self):
        assert schools_block() == ""

    @pytest.mark.asyncio
    async def test_the_posting_and_the_school_both_reach_the_scout(self):
        _profile()
        _application_id, job_id = _seed()
        scout = build_contacts(job_id=job_id).sub_agents[0]

        class Ctx:
            state: dict = {}

        instruction = await scout.instruction(Ctx())
        assert "Nimbus Labs" in instruction
        assert "INSA Lyon" in instruction
        # The failure this whole feature turns on, said in the prompt as well as
        # enforced in Python afterwards.
        assert "Never assemble a profile URL" in instruction


class TestTheFlow:
    @pytest.fixture()
    def client(self):
        from tinternship_backend.main import app

        return TestClient(app)

    def test_the_endpoint_streams(self, client, monkeypatch):
        application_id, _job_id = _seed()

        async def fake(app_id):
            yield ("phase", {"phase": "researching", "message": "Looking…"})
            yield ("result", {"artifact": {"id": 1}, "run_id": 4})

        monkeypatch.setattr(flows, "contacts_stream", fake)
        response = client.post(f"/api/applications/{application_id}/contacts")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

    def test_a_missing_application_is_a_404_and_not_a_stream(self, client):
        assert client.post("/api/applications/999999/contacts").status_code == 404

    def test_an_application_whose_posting_is_gone_is_a_409(self, client):
        """There is no employer to look for people at, and that is a fact a
        status code can carry — inside the stream it would read as a failed run
        on a page that had already switched to showing progress.

        The posting has to be removed behind the foreign key to arrange this,
        which is the point: it is a state the app cannot reach by itself and
        must survive anyway, the same guard the interview brief carries."""
        application_id, job_id = _seed()
        with get_engine().connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.exec_driver_sql("DELETE FROM job_posting WHERE id = ?", (job_id,))
            connection.commit()

        response = client.post(f"/api/applications/{application_id}/contacts")
        assert response.status_code == 409
        assert "posting is gone" in response.json()["detail"]

    async def test_the_employers_name_reaches_the_link_builder(self, monkeypatch):
        """The searches are built from the posting's own company and title, not
        from anything the model wrote — so this is the join that matters."""
        _profile()
        application_id, _job_id = _seed()
        seen: dict = {}

        async def fake_stream(agent, **kwargs):
            yield ("run", {"run_id": 0})
            yield ("state", {CONTACTS_STATE_KEY: {"people": []}})
            yield ("done", {"invocation_id": "inv-1"})

        original = outreach.resolve

        async def spy(plan, **kwargs):
            seen.update(kwargs)
            return await original(plan, **kwargs)

        monkeypatch.setattr(flows, "stream", fake_stream)
        monkeypatch.setattr(flows.outreach, "resolve", spy)

        result = await flows.run_contacts(application_id)
        assert seen["company"] == "Nimbus Labs"
        assert seen["title"] == "ML Intern"
        assert seen["keywords"] == ["computer vision"]
        # And the artifact that lands is the built searches, not the model's.
        angles = result["artifact"]["content"]["angles"]
        assert [angle["key"] for angle in angles][:2] == ["alumni", "recruiters"]

    async def test_the_language_is_stamped_on_rather_than_taken_from_the_model(
        self, monkeypatch
    ):
        application_id, _job_id = _seed()
        with session_scope() as session:
            application = session.get(Application, application_id)
            application.language = "fr"
            session.add(application)

        async def fake_stream(agent, **kwargs):
            yield ("run", {"run_id": 0})
            yield ("state", {CONTACTS_STATE_KEY: {"people": [], "language": "de"}})
            yield ("done", {"invocation_id": "inv-2"})

        monkeypatch.setattr(flows, "stream", fake_stream)

        result = await flows.run_contacts(application_id)
        assert result["artifact"]["content"]["language"] == "fr"

    async def test_a_writer_that_produced_nothing_still_saves_the_searches(
        self, monkeypatch
    ):
        """The searches are built from the posting and the profile, so they
        survive an agent that produced nothing at all — and throwing away a
        grounded search that already worked is a choice, not a consequence."""
        _profile()
        application_id, _job_id = _seed()

        # 0 rather than an id: `_save_artifact` turns a falsy run id into a NULL
        # foreign key, which keeps this test off the AgentRun table.
        async def fake_stream(agent, **kwargs):
            yield ("run", {"run_id": 0})
            yield ("state", {})
            yield ("done", {"invocation_id": "inv-3"})

        monkeypatch.setattr(flows, "stream", fake_stream)

        result = await flows.run_contacts(application_id)
        content = result["artifact"]["content"]
        assert len(content["angles"]) == 6
        assert all(angle["url"] for angle in content["angles"])
        # And it may not look like a run that simply found nobody.
        assert content["degraded"]
        assert "did not finish" in content["notes"]

    async def test_a_derailed_model_does_not_take_the_run_down_with_it(
        self, monkeypatch
    ):
        """The 2026-08-29 incident: the writer answered `"language": "fr` and
        enumerated locale tags until the output ceiling, so the JSON never
        closed and pydantic threw. That used to end the run and lose the
        grounded search with it."""
        _profile()
        application_id, _job_id = _seed()

        async def fake_stream(agent, **kwargs):
            yield ("run", {"run_id": 0})
            yield ("error", {"error": "Invalid JSON: EOF while parsing a string"})

        monkeypatch.setattr(flows, "stream", fake_stream)

        events = [event async for event in flows.contacts_stream(application_id)]
        kinds = [kind for kind, _data in events]
        assert kinds[-1] == "result"
        content = events[-1][1]["artifact"]["content"]
        assert len(content["angles"]) == 6
        assert "EOF while parsing" in content["degraded"]

    def test_the_schema_has_no_language_field_to_derail_in(self):
        """The root cause, pinned. A free-text code field has no stopping rule
        under constrained decoding, and the language is a fact about the
        request — `contacts_stream` stamps it on. Same lesson as
        `TailoredResume`, learned twice."""
        from tinternship_backend.agents.schemas import ContactPlan

        assert "language" not in ContactPlan.model_fields

    def test_the_two_vocabulary_fields_are_enums_not_free_strings(self):
        """For the same reason, and it is `ScoredPosting.index`'s reason: a
        listed value is one a constrained decoder cannot run past."""
        from tinternship_backend.agents.schemas import ContactLead

        schema = ContactLead.model_json_schema()["properties"]
        assert schema["category"]["enum"][0] == "recruiter"
        assert schema["confidence"]["enum"] == ["high", "medium", "low"]

    async def test_every_run_saves_a_new_version(self, monkeypatch):
        """People move on. An application chased six weeks later gets a fresh
        shortlist, and the old one still records who was written to."""
        application_id, _job_id = _seed()

        async def fake_stream(agent, **kwargs):
            yield ("run", {"run_id": 0})
            yield ("state", {CONTACTS_STATE_KEY: {"people": []}})
            yield ("done", {"invocation_id": "inv-4"})

        monkeypatch.setattr(flows, "stream", fake_stream)

        first = await flows.run_contacts(application_id)
        second = await flows.run_contacts(application_id)
        assert (first["artifact"]["version"], second["artifact"]["version"]) == (1, 2)
        assert first["artifact"]["kind"] == ArtifactKind.CONTACTS

    async def test_the_links_stage_is_announced_before_the_save(self, monkeypatch):
        """It is the stage that does the work the feature is for, and it costs a
        round of fetches — a page that said nothing here would look stuck."""
        application_id, _job_id = _seed()

        async def fake_stream(agent, **kwargs):
            yield ("run", {"run_id": 0})
            yield ("state", {CONTACTS_STATE_KEY: {"people": []}})
            yield ("done", {"invocation_id": "inv-5"})

        monkeypatch.setattr(flows, "stream", fake_stream)

        phases = [
            data["phase"]
            async for kind, data in flows.contacts_stream(application_id)
            if kind == "phase"
        ]
        assert phases == ["links", "saved"]


class TestTheMessage:
    """It is written when the button is pressed, and never before.

    The shortlist run used to write a line for everybody it named. Eight drafts
    to send one is output tokens, run time and a weighted Critic criterion spent
    on seven the candidate never opened — so the message moved out of the
    shortlist on 2026-09-03 and became its own one-call run.
    """

    async def _shortlist(self, monkeypatch, people: list[dict]) -> int:
        """One saved shortlist, with the people already resolved past `outreach`."""
        application_id, _job_id = _seed()

        async def fake_stream(agent, **kwargs):
            yield ("run", {"run_id": 0})
            yield ("state", {CONTACTS_STATE_KEY: {"people": people}})
            yield ("done", {"invocation_id": "inv-msg"})

        async def no_fetch(urls):
            from tinternship_backend.services.outreach import LIVE, PageCheck

            return {
                url: PageCheck(url=url, verdict=LIVE, title="Claire Dupont - Nimbus Labs")
                for url in urls
            }

        monkeypatch.setattr(flows, "stream", fake_stream)
        monkeypatch.setattr(flows.outreach, "check_pages", no_fetch)
        await flows.run_contacts(application_id)
        return application_id

    def test_the_shortlist_schema_cannot_carry_a_message(self):
        """The strategist has no field to write one in, which is what makes
        "not automatically" a property of the object rather than a promise in a
        prompt — the same move as `ContactPlan` having no `language`."""
        from tinternship_backend.agents.schemas import ContactLead

        assert "opening_line" not in ContactLead.model_fields

    async def test_a_saved_shortlist_arrives_with_every_message_empty(
        self, monkeypatch
    ):
        application_id = await self._shortlist(
            monkeypatch,
            [{"name": "Claire Dupont", "role": "Campus Manager", "evidence_url": "https://nimbus.test/team"}],
        )
        with session_scope() as session:
            artifact = session.exec(
                select(ApplicationArtifact).where(
                    ApplicationArtifact.application_id == application_id
                )
            ).one()
            assert artifact.content["people"][0]["opening_line"] == ""

    async def test_writing_it_stores_it_on_the_shortlist(self, monkeypatch):
        """In place, on the same version. A new version would make *Look
        again* — which really does re-research — indistinguishable from this."""
        application_id = await self._shortlist(
            monkeypatch,
            [{"name": "Claire Dupont", "role": "Campus Manager", "evidence_url": "https://nimbus.test/team"}],
        )

        async def fake_execute(agent, **kwargs):
            class Result:
                run_id = 11
                state = {OPENING_STATE_KEY: {"message": "Bonjour Claire, INSA Lyon too."}}

            return Result()

        monkeypatch.setattr(flows, "execute", fake_execute)
        written = await flows.write_opening_line(application_id, 0, "Claire Dupont")

        assert written["opening_line"] == "Bonjour Claire, INSA Lyon too."
        assert written["over_limit"] is False
        with session_scope() as session:
            artifacts = session.exec(
                select(ApplicationArtifact).where(
                    ApplicationArtifact.application_id == application_id
                )
            ).all()
            # One artifact still, with the message on it.
            assert len(artifacts) == 1
            assert artifacts[0].content["people"][0]["opening_line"].startswith("Bonjour")

    async def test_a_message_over_linkedins_limit_is_measured_not_hidden(
        self, monkeypatch
    ):
        """The prompt asks for 280; this is where being wrong is counted. A note
        that arrives truncated is worse than one the page flagged."""
        application_id = await self._shortlist(
            monkeypatch,
            [{"name": "Claire Dupont", "role": "Campus Manager", "evidence_url": "https://nimbus.test/team"}],
        )

        async def fake_execute(agent, **kwargs):
            class Result:
                run_id = 12
                state = {OPENING_STATE_KEY: {"message": "x" * 400}}

            return Result()

        monkeypatch.setattr(flows, "execute", fake_execute)
        written = await flows.write_opening_line(application_id, 0, "Claire Dupont")
        assert written["over_limit"] is True

    async def test_it_refuses_to_write_onto_somebody_else(self, monkeypatch):
        """The shortlist was re-run in another tab and renumbered. A message
        about the wrong human being, filed under a name that did not write it,
        reads exactly like a considered one."""
        application_id = await self._shortlist(
            monkeypatch,
            [{"name": "Claire Dupont", "role": "Campus Manager", "evidence_url": "https://nimbus.test/team"}],
        )

        with pytest.raises(flows.PersonMoved):
            await flows.write_opening_line(application_id, 0, "Thomas Bernard")
        with pytest.raises(flows.PersonMoved):
            await flows.write_opening_line(application_id, 7, "Claire Dupont")

    async def test_there_is_nothing_to_write_before_a_shortlist_exists(self):
        application_id, _job_id = _seed()
        with pytest.raises(ValueError, match="No shortlist"):
            await flows.write_opening_line(application_id, 0, "Claire Dupont")

    async def test_the_writer_is_given_that_person_and_not_the_list(self):
        """One person in the prompt, by name, with the page their role was read
        off — and the schools block phrased for somebody writing rather than
        somebody searching."""
        _profile()
        _application_id, job_id = _seed()
        opener = build_opener(
            job_id,
            {
                "name": "Claire Dupont",
                "role": "Campus Manager",
                "why": "She runs the internship programme",
                "evidence_url": "https://nimbus.test/team",
            },
            approach=["Message on LinkedIn before applying."],
        )

        class Ctx:
            state: dict = {}

        instruction = await opener.instruction(Ctx())
        assert "Claire Dupont" in instruction
        assert "She runs the internship programme" in instruction
        assert "https://nimbus.test/team" in instruction
        assert "Message on LinkedIn before applying." in instruction
        assert "Nimbus Labs" in instruction
        assert "INSA Lyon" in instruction
        # The 280-character rule is asked for here and counted in Python after.
        assert "280 characters" in instruction
        # And it is not being told to run a search it cannot run.
        assert "Search for people at this" not in instruction
