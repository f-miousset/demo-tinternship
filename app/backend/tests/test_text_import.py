"""Pasting a posting's *text* puts it on the list, with or without a link.

The third way in, and the one that exists for the postings the other two cannot
reach: the one that arrived as an email or a PDF, and the one on a board whose
bot protection answers a fetch — and then a real browser — with a challenge.

Its contract is the pasted link's with one clause changed. It may not say no to
a posting the candidate supplied, exactly as the link path may not; but where a
link that does not open a posting fails the *whole* import there, here it is a
detail the text happened to carry, so it is dropped and the posting is saved
without it. The one thing this path must never do is present a posting with no
proved link as though its link had been checked.

Nothing here reaches the network or starts a model: the agent run and
`verification.check_urls` are stubbed. What is under test is the pipeline around
them — what is refused, what becomes of a link in the text, and what is written
down.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlmodel import select

from tinternship_backend.agents.reader import ASSESSED_STATE_KEY, READ_STATE_KEY
from tinternship_backend.db.engine import session_scope
from tinternship_backend.db.models import Application, JobPosting
from tinternship_backend.services import flows, verification

POSTING_URL = "https://boards.greenhouse.io/acme/jobs/4012345"

# What somebody actually pastes: the posting, with the email it arrived in
# wrapped around it. Comfortably over `MIN_PASTED_TEXT`.
PASTED = """
Hi! Saw this and thought of you.

ML Research Intern — Acme, Paris
Six-month internship on the research team, starting in January. You will work on
representation learning with the perception group, in PyTorch, alongside two
research engineers.

Requirements: enrolled in a Master's programme, PyTorch, written English.
Nice to have: a publication, experience with distributed training.

Apply by 30 September.
"""


async def _no_digest(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """A paste is scored against the brief alone — the digest call must not run."""
    raise AssertionError("a paste must not build the feedback digest")


def _fake_run(
    posting: dict[str, Any], assessment: dict[str, Any] | None = None
) -> Any:
    """Stand in for the two-stage agent run, returning what each stage produced."""

    async def fake_stream(_agent, **_kwargs):
        yield ("run", {"run_id": 9, "session_id": "text-intake", "kind": "text_intake"})
        for author in ("reader", "matcher"):
            yield ("event", {"author": author, "text": "", "partial": False})
        yield (
            "state",
            {
                READ_STATE_KEY: posting,
                ASSESSED_STATE_KEY: assessment
                if assessment is not None
                else {"fit_score": 7.0, "fit_rationale": "PyTorch on both sides", "confidence": "medium"},
            },
        )
        yield ("done", {"run_id": 9, "text": "", "invocation_id": "inv-9"})

    return fake_stream


@pytest.fixture(autouse=True)
def clean_postings() -> None:
    with session_scope() as session:
        for posting in session.exec(select(JobPosting)).all():
            session.delete(posting)


@pytest.fixture
def fake_paste(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A pasted posting that names no link, and no model or network anywhere."""
    seen: dict[str, Any] = {"checked": []}

    async def fake_audit(**kwargs):
        seen["audited"] = kwargs.get("artifact")
        return {"overall": 7.5}

    async def fake_check(urls: list[str]):
        seen["checked"] += list(urls)
        return {
            url: verification.UrlCheck(url=url, status=verification.OK, http_status=200)
            for url in urls
        }

    monkeypatch.setattr(flows, "build_digest", _no_digest)
    monkeypatch.setattr(flows, "audit_artifact", fake_audit)
    monkeypatch.setattr(flows.verification, "check_urls", fake_check)
    monkeypatch.setattr(
        flows, "stream", _fake_run({"title": "ML Research Intern", "company": "Acme"})
    )
    return seen


async def _errors(text: str) -> list[str]:
    return [
        str(data.get("error"))
        async for event, data in flows.import_text_stream(text)
        if event == "error"
    ]


class TestWhatItRefuses:
    async def test_a_paste_too_short_to_be_a_posting_is_refused_before_any_run(
        self, fake_paste: dict[str, Any]
    ) -> None:
        # Answered in a millisecond rather than after two model calls, and it
        # names the other field: a bare URL in this box is a user who wanted
        # "Paste a link".
        errors = await _errors(POSTING_URL)
        assert errors and "too short" in errors[0]
        assert "Paste a link" in errors[0]
        with session_scope() as session:
            assert session.exec(select(JobPosting)).all() == []

    async def test_text_the_reader_says_is_not_one_posting_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, fake_paste: dict[str, Any]
    ) -> None:
        # An empty title is how the Reader reports "this is a list of roles, an
        # About page, a signature block". Saving a card assembled out of one is
        # the outcome worse than saying so.
        monkeypatch.setattr(flows, "stream", _fake_run({"title": "", "company": "Acme"}))
        errors = await _errors(PASTED)
        assert errors and "single job posting" in errors[0]
        with session_scope() as session:
            assert session.exec(select(JobPosting)).all() == []


class TestWhatItSaves:
    async def test_a_posting_with_no_link_at_all_is_still_saved(
        self, fake_paste: dict[str, Any]
    ) -> None:
        # The one place in the app where a posting may have no URL. Everywhere
        # else that is a lead the candidate cannot read; here they are holding
        # the posting, and refusing it would throw away what they just gave us.
        result = await flows.import_text(PASTED)

        assert result["job_id"]
        assert result["saved"]["created"] == 1
        assert result["link_note"] == "The text did not carry a link, so this posting has none."
        with session_scope() as session:
            saved = session.exec(select(JobPosting)).one()
            assert saved.title == "ML Research Intern"
            assert saved.company == "Acme"
            assert saved.url == ""
            assert saved.fit_score == 7.0
            # Not `ok`: nothing was checked, and a badge saying otherwise on a
            # link that does not exist is the failure this path could have had.
            assert saved.url_status == verification.UNCHECKED

    async def test_a_link_the_text_carried_is_proved_and_kept(
        self, monkeypatch: pytest.MonkeyPatch, fake_paste: dict[str, Any]
    ) -> None:
        monkeypatch.setattr(
            flows,
            "stream",
            _fake_run({"title": "ML Research Intern", "company": "Acme", "url": POSTING_URL}),
        )
        result = await flows.import_text(PASTED)

        assert fake_paste["checked"] == [POSTING_URL]
        assert result["link_note"] == ""
        with session_scope() as session:
            saved = session.exec(select(JobPosting)).one()
            assert saved.url == POSTING_URL
            assert saved.url_status == verification.OK
            assert saved.source == "boards.greenhouse.io"

    async def test_a_link_that_does_not_open_a_posting_is_dropped_not_saved(
        self, monkeypatch: pytest.MonkeyPatch, fake_paste: dict[str, Any]
    ) -> None:
        # A careers page is the commonest URL inside a pasted posting — it is in
        # the footer of half of them. Dropping it by shape costs no fetch, and
        # the posting is still saved, which is the difference from the link path.
        monkeypatch.setattr(
            flows,
            "stream",
            _fake_run(
                {"title": "ML Research Intern", "company": "Acme", "url": "https://acme.com/careers"}
            ),
        )
        result = await flows.import_text(PASTED)

        assert fake_paste["checked"] == []
        assert "dropped" in result["link_note"]
        with session_scope() as session:
            saved = session.exec(select(JobPosting)).one()
            assert saved.url == ""
            assert saved.url_status == verification.UNCHECKED

    async def test_a_link_that_is_dead_is_dropped_and_the_posting_still_lands(
        self, monkeypatch: pytest.MonkeyPatch, fake_paste: dict[str, Any]
    ) -> None:
        async def dead(urls: list[str]):
            return {
                url: verification.UrlCheck(
                    url=url, status=verification.DEAD, http_status=404, note="it answered 404"
                )
                for url in urls
            }

        monkeypatch.setattr(flows.verification, "check_urls", dead)
        monkeypatch.setattr(
            flows,
            "stream",
            _fake_run({"title": "ML Research Intern", "company": "Acme", "url": POSTING_URL}),
        )
        result = await flows.import_text(PASTED)

        assert "it answered 404" in result["link_note"]
        with session_scope() as session:
            assert session.exec(select(JobPosting)).one().url == ""

    async def test_the_date_in_the_text_is_parsed_into_the_ordering_key(
        self, monkeypatch: pytest.MonkeyPatch, fake_paste: dict[str, Any]
    ) -> None:
        monkeypatch.setattr(
            flows,
            "stream",
            _fake_run(
                {"title": "ML Research Intern", "company": "Acme", "posted_at": "2026-08-20"}
            ),
        )
        await flows.import_text(PASTED)
        with session_scope() as session:
            assert session.exec(select(JobPosting)).one().posted_on == "2026-08-20"

    async def test_pasting_the_same_posting_twice_updates_one_row(
        self, fake_paste: dict[str, Any]
    ) -> None:
        # Found by `find_existing`, the same function `save_job_postings` used to
        # decide where to write — a lookup by URL would find nothing here, since
        # there is no URL.
        await flows.import_text(PASTED)
        result = await flows.import_text(PASTED)

        assert result["already_saved"] is True
        assert result["job_id"]
        with session_scope() as session:
            assert len(session.exec(select(JobPosting)).all()) == 1

    async def test_a_second_posting_with_a_look_alike_title_gets_its_own_row(
        self, monkeypatch: pytest.MonkeyPatch, fake_paste: dict[str, Any]
    ) -> None:
        # Same company, nearly the same title, a different posting. Matched by
        # company and title, the second paste overwrote the first (2026-10-06);
        # with no link, the text pasted is what tells them apart.
        await flows.import_text(PASTED)
        monkeypatch.setattr(
            flows, "stream", _fake_run({"title": "ML Research Intern - Lyon", "company": "Acme"})
        )
        other = PASTED.replace("Paris", "Lyon").replace("perception", "robotics")
        result = await flows.import_text(other)

        assert result["already_saved"] is False
        with session_scope() as session:
            titles = {p.title for p in session.exec(select(JobPosting)).all()}
            assert titles == {"ML Research Intern", "ML Research Intern - Lyon"}
            assert len(session.exec(select(Application)).all()) == 2

    async def test_pasting_a_dismissed_posting_brings_it_back(
        self, fake_paste: dict[str, Any]
    ) -> None:
        await flows.import_text(PASTED)
        with session_scope() as session:
            posting = session.exec(select(JobPosting)).one()
            posting.dismissed = True
            session.add(posting)

        result = await flows.import_text(PASTED)

        assert result["restored"] is True
        with session_scope() as session:
            assert session.exec(select(JobPosting)).one().dismissed is False

    async def test_pasting_a_posting_says_yes_to_it(
        self, fake_paste: dict[str, Any]
    ) -> None:
        # Same as the pasted link, and it has to be: the two paths differ in
        # what they read, never in what the candidate meant by pasting.
        result = await flows.import_text(PASTED)

        assert result["tracked"] is True
        assert result["application_id"]
        with session_scope() as session:
            application = session.exec(select(Application)).one()
            assert application.job_posting_id == result["job_id"]
            assert application.pinned is False

    async def test_pasting_one_already_tracked_does_not_track_it_twice(
        self, fake_paste: dict[str, Any]
    ) -> None:
        await flows.import_text(PASTED)
        result = await flows.import_text(PASTED)

        assert result["tracked"] is False
        with session_scope() as session:
            assert len(session.exec(select(Application)).all()) == 1

    async def test_the_score_is_audited_like_any_other_ranking(
        self, fake_paste: dict[str, Any]
    ) -> None:
        result = await flows.import_text(PASTED)
        assert result["audit"] == {"overall": 7.5}
        assert fake_paste["audited"]["jobs"][0]["title"] == "ML Research Intern"


class TestTheProgressItReports:
    async def test_every_stage_announces_itself(self, fake_paste: dict[str, Any]) -> None:
        # No `fetch` and no `browser`: there is nothing to open. The candidate
        # watching this should not be told the app is loading a page.
        phases = [
            data["phase"]
            async for event, data in flows.import_text_stream(PASTED)
            if event == "phase"
        ]
        assert phases == ["reader", "matcher", "verify", "save", "audit"]
