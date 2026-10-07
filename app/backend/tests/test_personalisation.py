"""What the candidate knows that the posting does not, and where it goes.

Asking for a package opens a dialog: someone you know on the team, a
conversation at a careers fair, an angle you want taken. That sentence is
usually the most useful thing in the whole prompt — no amount of research can
find it — so it reaches the Résumé and Cover Letter agents as its own block, and
their Critics too, because a named contact in a letter is otherwise
indistinguishable from an invented one.

Asking for a package also moves a `saved` application to `preparing`, since
writing the documents *is* the preparation.
"""

from __future__ import annotations

import pytest
from conftest import applying_critics, applying_producers, build_letter_plan, build_plan
from fastapi.testclient import TestClient

from tinternship_backend.agents.applying import build_applying_team
from tinternship_backend.db.engine import session_scope
from tinternship_backend.db.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    JobPosting,
)
from tinternship_backend.services import flows
from tinternship_backend.services.context_blocks import personalisation_block

NOTE = "I met Claire Dupont, their data lead, at the Forum INSA in March."


def _application(status: str = ApplicationStatus.SAVED) -> int:
    with session_scope() as session:
        job = JobPosting(dedupe_key="k", title="ML Intern", company="Nimbus", url="https://e.test/1")
        session.add(job)
        session.flush()
        application = Application(job_posting_id=job.id, status=status)
        session.add(application)
        session.flush()
        return application.id


class TestTheBlock:
    def test_nothing_typed_renders_nothing(self):
        """`compose` drops an empty block, so an agent that never sees one reads
        exactly as it did before this existed."""
        assert personalisation_block("") == ""
        assert personalisation_block("   \n ") == ""

    def test_it_quotes_what_was_written_verbatim(self):
        block = personalisation_block(NOTE)
        assert NOTE in block

    def test_a_multi_line_note_stays_inside_the_quote(self):
        """One `>` per line — otherwise the second line escapes the block quote
        and reads as an instruction to the model rather than as the
        candidate's words."""
        block = personalisation_block("First line.\nSecond line.")
        assert "> First line." in block
        assert "> Second line." in block

    def test_it_says_what_may_not_be_done_with_it(self):
        """A conversation is a conversation. The failure mode is a letter that
        upgrades "I met their data lead" into "Claire Dupont suggested I apply"."""
        block = personalisation_block(NOTE)
        assert "referral" in block


class TestItReachesTheWriters:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("agent_name", ["resume_agent", "cover_letter_agent"])
    async def test_both_producers_are_told(self, agent_name):
        team = build_applying_team(
            job_id=0,
            resume_plan=build_plan("en"),
            letter_plan=build_letter_plan("en"),
            personalisation=NOTE,
        )
        class Ctx:
            state: dict = {}

        assert NOTE in await applying_producers(team)[agent_name].instruction(Ctx())

    @pytest.mark.asyncio
    async def test_the_critics_are_told_too(self):
        """Without it, the Critic sees a name in the letter that appears nowhere
        in the profile or the posting and correctly calls it an unsupported
        claim — killing the single most useful sentence in the package."""
        team = build_applying_team(
            job_id=0,
            resume_plan=build_plan("en"),
            letter_plan=build_letter_plan("en"),
            personalisation=NOTE,
        )

        class Ctx:
            state: dict = {}

        for critic in applying_critics(team).values():
            assert NOTE in await critic.instruction(Ctx()), critic.name


@pytest.mark.usefixtures("base_documents_installed")
class TestTheEndpoint:
    @pytest.fixture()
    def client(self, monkeypatch):
        from tinternship_backend.main import app

        self.seen: dict = {}

        async def fake(application_id, job_id, language, personalisation="", cover_letter=False, resume=True):
            self.seen["personalisation"] = personalisation
            yield ("result", {"artifacts": {}, "run_id": 0})

        monkeypatch.setattr(flows, "applying_stream", fake)
        return TestClient(app)

    def test_what_was_typed_is_stored_and_passed_to_the_run(self, client):
        application_id = _application()
        client.post(
            f"/api/applications/{application_id}/generate", json={"personalisation": NOTE}
        )

        assert self.seen["personalisation"] == NOTE
        assert client.get(f"/api/applications/{application_id}").json()["personalisation"] == NOTE

    def test_regenerating_without_saying_anything_keeps_the_note(self, client):
        """The dialog starts from what you wrote last time; an omitted field is
        "leave it alone", not "clear it"."""
        application_id = _application()
        client.post(
            f"/api/applications/{application_id}/generate", json={"personalisation": NOTE}
        )
        client.post(f"/api/applications/{application_id}/generate", json={"language": "fr"})

        assert self.seen["personalisation"] == NOTE

    def test_an_empty_string_is_a_deliberate_clear(self, client):
        application_id = _application()
        client.post(
            f"/api/applications/{application_id}/generate", json={"personalisation": NOTE}
        )
        client.post(f"/api/applications/{application_id}/generate", json={"personalisation": ""})

        assert self.seen["personalisation"] == ""


class TestGeneratingMovesTheCard:
    @pytest.fixture()
    def client(self, monkeypatch):
        from tinternship_backend.main import app

        async def fake(application_id, job_id, language, personalisation="", cover_letter=False, resume=True):
            yield ("result", {"artifacts": {}, "run_id": 0})

        monkeypatch.setattr(flows, "applying_stream", fake)
        return TestClient(app)

    def test_a_saved_application_becomes_preparing(self, client):
        application_id = _application()
        client.post(f"/api/applications/{application_id}/generate")

        assert (
            client.get(f"/api/applications/{application_id}").json()["status"]
            == ApplicationStatus.PREPARING
        )

    def test_the_move_lands_in_the_timeline_like_any_other(self, client):
        application_id = _application()
        client.post(f"/api/applications/{application_id}/generate")

        with session_scope() as session:
            from sqlmodel import select

            notes = [
                event.note
                for event in session.exec(
                    select(ApplicationEvent).where(
                        ApplicationEvent.application_id == application_id
                    )
                ).all()
            ]
        assert "Generating the application package." in notes

    @pytest.mark.parametrize(
        "status",
        [
            ApplicationStatus.APPLIED,
            ApplicationStatus.HR_PRE_CALL,
            ApplicationStatus.OFFER,
            ApplicationStatus.REJECTED,
        ],
    )
    def test_regenerating_never_walks_a_status_backwards(self, client, status):
        """Rewriting the letter for an interview you already have must not file
        the application back under "preparing"."""
        application_id = _application(status=status)
        client.post(f"/api/applications/{application_id}/generate")

        assert client.get(f"/api/applications/{application_id}").json()["status"] == status
