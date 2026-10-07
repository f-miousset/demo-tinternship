"""Chasing an application nobody answered.

Everything here guards a *silent* failure. A nudge that fires for an
application that has already been rejected is noise, and noise gets muted; a
nudge that never fires for one that has been ignored for a month is the whole
gap the feature exists to close. Neither shows up as an error anywhere.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from tinternship_backend.agents.follow_up import MAX_WORDS, too_long, word_count
from tinternship_backend.db.engine import session_scope
from tinternship_backend.db.models import (
    Application,
    ApplicationArtifact,
    ApplicationEvent,
    ApplicationStatus,
    ArtifactKind,
    JobPosting,
    utcnow,
)
from tinternship_backend.services import follow_up


def _application(
    *,
    status: str = ApplicationStatus.APPLIED,
    days_ago: int = 20,
    company: str = "Nimbus",
    key: str = "nimbus-ml-intern",
) -> int:
    """One tracked application whose last event was `days_ago` days back."""
    moment = utcnow() - timedelta(days=days_ago)
    with session_scope() as session:
        job = JobPosting(
            dedupe_key=key,
            title="ML Intern",
            company=company,
            url=f"https://example.com/{key}",
            apply_url=f"https://example.com/{key}/apply",
        )
        session.add(job)
        session.flush()
        application = Application(
            job_posting_id=job.id, status=status, applied_at=moment, created_at=moment
        )
        session.add(application)
        session.flush()
        session.add(
            ApplicationEvent(
                application_id=application.id, to_status=status, created_at=moment
            )
        )
        return application.id


def _event(application_id: int, *, days_ago: int = 0, note: str = "") -> None:
    with session_scope() as session:
        session.add(
            ApplicationEvent(
                application_id=application_id,
                note=note,
                created_at=utcnow() - timedelta(days=days_ago),
            )
        )


def _draft(application_id: int, *, days_ago: int = 0, content: dict | None = None) -> int:
    with session_scope() as session:
        artifact = ApplicationArtifact(
            application_id=application_id,
            kind=ArtifactKind.FOLLOW_UP,
            content=content or {"subject": "Re: ML Intern", "paragraphs": ["Hello."]},
            created_at=utcnow() - timedelta(days=days_ago),
        )
        session.add(artifact)
        session.flush()
        return artifact.id


class TestWhoGetsRaised:
    def test_silence_past_the_threshold_is_raised(self):
        _application(days_ago=20)

        assert [item.days_silent for item in follow_up.silent_applications()] == [20]

    def test_a_day_short_of_the_threshold_is_not(self):
        """Floored whole days. 13.9 days of silence is not yet 14."""
        _application(days_ago=13)

        assert follow_up.silent_applications() == []

    @pytest.mark.parametrize(
        "status",
        [
            ApplicationStatus.APPLIED,
            ApplicationStatus.HR_PRE_CALL,
            ApplicationStatus.TECHNICAL_TEST,
        ],
    )
    def test_every_status_where_they_owe_the_answer_is_chased(self, status):
        _application(status=status, days_ago=30)

        assert len(follow_up.silent_applications()) == 1

    @pytest.mark.parametrize(
        "status",
        [
            ApplicationStatus.SAVED,
            ApplicationStatus.PREPARING,
            ApplicationStatus.OFFER,
            ApplicationStatus.REJECTED,
            ApplicationStatus.GHOSTED,
            ApplicationStatus.WITHDRAWN,
        ],
    )
    def test_nothing_is_owed_on_the_others(self, status):
        """Not sent yet, or over. Chasing either is the noise that gets it muted."""
        _application(status=status, days_ago=90)

        assert follow_up.silent_applications() == []

    def test_an_application_in_the_trackers_trash_is_not_chased(self):
        """An email drafted for a job they gave up on is the sweep's worst output."""
        application_id = _application(days_ago=90)
        with session_scope() as session:
            application = session.get(Application, application_id)
            application.trashed_at = utcnow()
            session.add(application)

        assert follow_up.silent_applications() == []

    def test_taking_it_back_out_leaves_the_silence_where_it_was(self):
        # Trashing writes no event, so the clock never restarted: an
        # application ignored for 90 days is still 90 days silent when it comes
        # back, and is due immediately rather than in another fortnight.
        application_id = _application(days_ago=90)
        with session_scope() as session:
            application = session.get(Application, application_id)
            application.trashed_at = utcnow()
            session.add(application)
        with session_scope() as session:
            application = session.get(Application, application_id)
            application.trashed_at = None
            session.add(application)

        assert [item.days_silent for item in follow_up.silent_applications()] == [90]

    def test_the_longest_silence_comes_first(self):
        _application(days_ago=20, key="a", company="A")
        _application(days_ago=60, key="b", company="B")
        _application(days_ago=30, key="c", company="C")

        assert [item.company for item in follow_up.silent_applications()] == ["B", "C", "A"]

    def test_the_threshold_is_the_live_knob(self, monkeypatch):
        _application(days_ago=20)
        from tinternship_backend.config import get_settings

        monkeypatch.setattr(get_settings(), "follow_up_after_days", 30)
        assert follow_up.silent_applications() == []

        monkeypatch.setattr(get_settings(), "follow_up_after_days", 7)
        assert len(follow_up.silent_applications()) == 1


class TestTheEventLogIsTheClock:
    """There is no `last_chased_at` column, on purpose — see the module docstring."""

    def test_a_recent_note_means_the_application_is_not_being_ignored(self):
        application_id = _application(days_ago=40)
        _event(application_id, days_ago=2, note="Recruiter says decisions in March.")

        assert follow_up.silent_applications() == []

    def test_marking_it_sent_restarts_the_clock(self):
        application_id = _application(days_ago=40)
        assert follow_up.silent_applications()

        _event(application_id, note=follow_up.SENT_NOTE)

        assert follow_up.silent_applications() == []

    def test_failing_to_find_anybody_postpones_rather_than_dismisses(self):
        """A posting with no address still restarts the clock, then comes back.

        The nudge has two honest answers and this is the second one. It must
        not be permanent: in a fortnight there may be a name on the team page
        that is not there today, and an application nobody could chase is still
        one nobody has answered.
        """
        chased_this_week = _application(days_ago=40, company="Nimbus", key="nimbus-ml")
        _event(chased_this_week, days_ago=2, note=follow_up.NO_CONTACT_NOTE)

        chased_three_weeks_ago = _application(days_ago=40, company="Orbit", key="orbit-ml")
        _event(chased_three_weeks_ago, days_ago=20, note=follow_up.NO_CONTACT_NOTE)

        assert [item.application_id for item in follow_up.silent_applications()] == [
            chased_three_weeks_ago
        ]

    def test_an_application_with_no_events_falls_back_to_when_it_was_applied(self):
        application_id = _application(days_ago=30)
        with session_scope() as session:
            for event in session.exec(select(ApplicationEvent)).all():
                session.delete(event)

        assert [item.days_silent for item in follow_up.silent_applications()] == [30]
        assert follow_up.silent_applications()[0].application_id == application_id


class TestDrafts:
    def test_a_due_application_carries_whatever_draft_it_has(self):
        application_id = _application(days_ago=20)
        _draft(application_id)

        item = follow_up.silent_applications()[0]
        assert item.draft is not None
        assert item.draft["content"]["subject"] == "Re: ML Intern"
        assert item.draft_stale is False

    def test_a_draft_written_before_the_last_event_is_stale(self):
        application_id = _application(days_ago=40)
        _draft(application_id, days_ago=30)
        _event(application_id, days_ago=20, note="Chased on LinkedIn.")

        item = follow_up.silent_applications()[0]
        assert item.draft_stale is True

    def test_a_draft_asked_for_early_is_stale_by_the_time_it_comes_due(self):
        """The "Write the email" button can be pressed on day 3. If that draft
        then counted as current, the day-14 nudge would surface a fortnight-old
        email written about a three-day silence."""
        application_id = _application(days_ago=20)
        # Written 17 days ago — i.e. three days into the silence, well before
        # the 14-day threshold turned it into something worth chasing.
        _draft(application_id, days_ago=17)

        assert follow_up.silent_applications()[0].draft_stale is True

    def test_a_draft_written_once_it_was_actually_due_is_current(self):
        application_id = _application(days_ago=20)
        _draft(application_id, days_ago=2)

        assert follow_up.silent_applications()[0].draft_stale is False

    def test_pending_reports_the_threshold_it_used(self):
        payload = follow_up.pending()

        assert payload["after_days"] == follow_up.after_days()
        assert payload["follow_ups"] == []


class TestTheSweep:
    """The background pass, with the model call stubbed out."""

    @pytest.fixture()
    def drafted(self, monkeypatch) -> list[int]:
        seen: list[int] = []

        async def fake_run(application_id: int) -> dict[str, Any]:
            seen.append(application_id)
            return {}

        from tinternship_backend.services import flows

        monkeypatch.setattr(flows, "run_follow_up", fake_run)
        from tinternship_backend.config import get_settings

        monkeypatch.setattr(get_settings(), "google_api_key", "test-key")
        return seen

    async def test_writes_one_email_per_newly_silent_application(self, drafted):
        first = _application(days_ago=20, key="a", company="A")
        second = _application(days_ago=40, key="b", company="B")

        result = await follow_up.sweep()

        assert result == {"due": 2, "drafted": 2, "failed": 0}
        assert sorted(drafted) == sorted([first, second])

    async def test_does_not_rewrite_a_draft_that_is_still_current(self, drafted):
        """Otherwise every sweep spends a model call on every silent application
        forever, and the draft you were reading changes under you."""
        application_id = _application(days_ago=20)
        _draft(application_id)

        assert await follow_up.sweep() == {"due": 0, "drafted": 0, "failed": 0}
        assert drafted == []

    async def test_replaces_a_draft_the_candidate_asked_for_before_it_came_due(self, drafted):
        application_id = _application(days_ago=20)
        _draft(application_id, days_ago=17)

        await follow_up.sweep()

        assert drafted == [application_id]

    async def test_rewrites_a_draft_that_predates_the_latest_event(self, drafted):
        application_id = _application(days_ago=40)
        _draft(application_id, days_ago=30)
        _event(application_id, days_ago=20, note="Left a voicemail.")

        await follow_up.sweep()

        assert drafted == [application_id]

    async def test_one_failure_does_not_stop_the_rest(self, monkeypatch):
        from tinternship_backend.config import get_settings
        from tinternship_backend.services import flows

        monkeypatch.setattr(get_settings(), "google_api_key", "test-key")
        done: list[int] = []

        async def flaky(application_id: int) -> dict[str, Any]:
            if not done:
                done.append(application_id)
                raise RuntimeError("the model fell over")
            done.append(application_id)
            return {}

        monkeypatch.setattr(flows, "run_follow_up", flaky)
        _application(days_ago=20, key="a", company="A")
        _application(days_ago=40, key="b", company="B")

        result = await follow_up.sweep()

        assert result["due"] == 2 and result["drafted"] == 1 and result["failed"] == 1
        assert len(done) == 2

    async def test_does_nothing_without_an_api_key(self, monkeypatch):
        """Every run would fail identically and fill the trace log with it."""
        from tinternship_backend.config import get_settings

        monkeypatch.setattr(get_settings(), "google_api_key", "")
        _application(days_ago=40)

        assert await follow_up.sweep() == {"due": 0, "drafted": 0, "failed": 0}


class TestSilence:
    """What the application page reads — it offers the button whether or not
    anything is due, so it needs the rule even when nothing is."""

    def _silence(self, application_id: int):
        from sqlmodel import select as _select

        with session_scope() as session:
            application = session.get(Application, application_id)
            events = list(
                session.exec(
                    _select(ApplicationEvent).where(
                        ApplicationEvent.application_id == application_id
                    ).order_by(ApplicationEvent.created_at)
                ).all()
            )
            return follow_up.silence_of(application, events)

    def test_a_quiet_but_not_yet_due_application_is_sendable_and_not_due(self):
        silence = self._silence(_application(days_ago=5))

        assert silence.days == 5
        assert silence.waiting is True
        assert silence.sendable is True
        assert silence.due is False

    @pytest.mark.parametrize("status", [ApplicationStatus.SAVED, ApplicationStatus.PREPARING])
    def test_an_application_that_was_never_sent_has_nothing_to_chase(self, status):
        silence = self._silence(_application(status=status, days_ago=40))

        assert silence.sendable is False
        assert silence.due is False

    def test_a_rejection_is_still_sendable_even_though_nothing_is_owed(self):
        """Unusual to chase, but the candidate's call — the button stays live."""
        silence = self._silence(_application(status=ApplicationStatus.REJECTED, days_ago=40))

        assert silence.sendable is True
        assert silence.waiting is False
        assert silence.due is False


class TestDraftContext:
    def test_carries_the_timeline_and_todays_date(self):
        application_id = _application(days_ago=20)
        _event(application_id, days_ago=18, note="Auto-acknowledgement received.")

        context = follow_up.draft_context(application_id)

        assert "Auto-acknowledgement received." in context.history
        assert utcnow().date().isoformat() in context.history

    def test_forbids_inventing_anything_the_record_does_not_hold(self):
        application_id = _application(days_ago=20)

        assert "it did not happen" in follow_up.draft_context(application_id).history

    def test_carries_what_the_cover_letter_already_argued(self):
        """So the chase does not make the same three points a second time."""
        application_id = _application(days_ago=20)
        with session_scope() as session:
            session.add(
                ApplicationArtifact(
                    application_id=application_id,
                    kind=ArtifactKind.COVER_LETTER,
                    content={
                        "recipient": "Dr Awad",
                        "subject": "Application — ML Intern",
                        "facts_used": ["Rebuilt the ingest pipeline at SAP"],
                    },
                )
            )

        history = follow_up.draft_context(application_id).history

        assert "Dr Awad" in history
        assert "Rebuilt the ingest pipeline at SAP" in history

    def test_carries_the_previous_chase_so_the_second_is_not_a_copy(self):
        application_id = _application(days_ago=20)
        _draft(
            application_id,
            days_ago=30,
            content={"subject": "Re: ML Intern", "paragraphs": ["Just checking in."]},
        )

        assert "Just checking in." in follow_up.draft_context(application_id).history

    def test_an_unknown_application_is_a_value_error_not_a_500(self):
        with pytest.raises(ValueError):
            follow_up.draft_context(9999)


class TestTheLengthGate:
    """The one thing about this email that is arithmetic rather than taste."""

    def test_counts_the_body_only(self):
        email = {
            "greeting": "Dear Dr Awad,",
            "paragraphs": ["one two three", "four five"],
            "sign_off": "Kind regards,",
            "signature": "Alex Martin · +33 6 00 00 00 00",
        }
        # The furniture every email carries would otherwise penalise a longer
        # sign-off instead of a longer argument.
        assert word_count(email) == 5

    def test_a_short_email_passes(self):
        assert too_long({"paragraphs": ["Hello, any news on the ML Intern role?"]}) == ""

    def test_an_over_long_email_is_rejected_with_the_numbers(self):
        violation = too_long({"paragraphs": [" ".join(["word"] * (MAX_WORDS + 25))]})

        assert str(MAX_WORDS) in violation
        assert "25 over" in violation

    def test_the_prompt_the_rubric_and_the_gate_all_state_the_same_limit(self):
        """Three places said "short"; only one of them was ever enforced."""
        from tinternship_backend.agents.prompts import FOLLOW_UP_INSTRUCTION
        from tinternship_backend.agents.rubrics import FOLLOW_UP_RUBRIC

        rendered = FOLLOW_UP_INSTRUCTION.format(honesty="", max_words=MAX_WORDS)
        assert f"{MAX_WORDS} words" in rendered
        brevity = next(c for c in FOLLOW_UP_RUBRIC.criteria if c.name == "brevity")
        assert str(MAX_WORDS) in brevity.description


class TestEndpoints:
    @pytest.fixture()
    def client(self) -> TestClient:
        from tinternship_backend.main import app

        return TestClient(app)

    def test_the_collection_route_is_not_read_as_an_application_id(self, client):
        """Routes match in declaration order, and `/{application_id}` is an
        `int` path — declared first it would swallow "follow-ups" and answer
        422 forever."""
        response = client.get("/api/applications/follow-ups")

        assert response.status_code == 200
        assert set(response.json()) == {"after_days", "follow_ups"}

    def test_serves_the_due_list_with_its_draft(self, client):
        application_id = _application(days_ago=20)
        _draft(application_id)

        payload = client.get("/api/applications/follow-ups").json()

        assert len(payload["follow_ups"]) == 1
        due = payload["follow_ups"][0]
        assert due["application_id"] == application_id
        assert due["days_silent"] == 20
        assert due["job"]["company"] == "Nimbus"
        assert due["draft"]["content"]["subject"] == "Re: ML Intern"

    def test_marking_it_sent_writes_a_timeline_event_and_clears_it(self, client):
        application_id = _application(days_ago=20)

        assert client.post(f"/api/applications/{application_id}/follow-up/sent").status_code == 200

        timeline = client.get(f"/api/applications/{application_id}").json()["timeline"]
        assert timeline[-1]["note"] == follow_up.SENT_NOTE
        # Same status either way: nothing has happened at the employer's end.
        assert timeline[-1]["from"] == timeline[-1]["to"] == ApplicationStatus.APPLIED
        assert client.get("/api/applications/follow-ups").json()["follow_ups"] == []

    def test_failing_to_contact_anyone_is_recorded_in_the_same_timeline(self, client):
        """The answer for a posting with nobody behind it.

        Marking it "sent" instead would put a lie in the timeline — and the
        timeline is what `draft_context` hands the writer, so the next chase
        would be written as a second one to somebody who never got a first.
        """
        application_id = _application(days_ago=20)

        response = client.post(f"/api/applications/{application_id}/follow-up/no-contact")

        assert response.status_code == 200
        timeline = client.get(f"/api/applications/{application_id}").json()["timeline"]
        assert timeline[-1]["note"] == follow_up.NO_CONTACT_NOTE
        # Nothing happened at the employer's end, so the status does not move.
        assert timeline[-1]["from"] == timeline[-1]["to"] == ApplicationStatus.APPLIED
        assert client.get("/api/applications/follow-ups").json()["follow_ups"] == []

    @pytest.mark.parametrize(
        "path", ["/follow-up", "/follow-up/sent", "/follow-up/no-contact"]
    )
    def test_an_unknown_application_is_a_404_before_any_run_starts(self, client, path):
        assert client.post(f"/api/applications/9999{path}").status_code == 404

    def test_the_detail_endpoint_reports_the_silence_even_when_nothing_is_due(self, client):
        """The application page offers to write the email whenever you want one,
        so it needs the silence on an application the Tracker is not raising."""
        application_id = _application(days_ago=3)

        silence = client.get(f"/api/applications/{application_id}").json()["silence"]

        assert silence["days"] == 3
        assert silence["due"] is False
        assert silence["sendable"] is True
        assert silence["after_days"] == follow_up.after_days()
        assert client.get("/api/applications/follow-ups").json()["follow_ups"] == []
