"""Pasting a link puts one posting on the list — or says why it cannot.

The Investigator earns its results and may drop what it does not like. This
path has the opposite contract: the candidate named this posting, so it goes on
the list at whatever it scores. The only refusals are about the link, and each
one has to arrive as a sentence the candidate can act on rather than a card
assembled out of a careers-page navigation menu.

Nothing here reaches the network or starts a model. `verification.fetch_posting`
and the agent run are stubbed; what is under test is the pipeline around them —
which link gets refused, what is merged, and what is written down.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlmodel import select

from tinternship_backend.agents.reader import ASSESSED_STATE_KEY, READ_STATE_KEY
from tinternship_backend.api.jobs import list_jobs
from tinternship_backend.db.engine import session_scope
from tinternship_backend.db.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    JobPosting,
    utcnow,
)
from tinternship_backend.services import flows, job_links, page_text, verification

POSTING_URL = "https://boards.greenhouse.io/acme/jobs/4012345"

PAGE = """
<html><head><title>ML Research Intern — Acme</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting","title":"ML Research Intern",
 "datePosted":"2026-08-20","validThrough":"2026-09-30","employmentType":"INTERN",
 "hiringOrganization":{"@type":"Organization","name":"Acme"},
 "jobLocation":{"@type":"Place","address":{"@type":"PostalAddress","addressLocality":"Paris"}},
 "description":"<p>Six-month internship on the research team.</p><ul><li>PyTorch</li></ul>"}
</script>
<script>window.analytics = {track: function(){}};</script>
<style>.hero { color: red; }</style></head>
<body><h1>ML Research Intern</h1>
<p>Six-month internship on the research team, starting in January.</p>
<ul><li>PyTorch</li><li>Enrolled in a Master's programme</li></ul>
</body></html>
"""


async def _no_digest(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """A paste is scored against the brief alone — the digest call must not run."""
    raise AssertionError("a paste must not build the feedback digest")


def _fake_run(
    posting: dict[str, Any], assessment: dict[str, Any] | None = None
) -> Any:
    """Stand in for the two-stage agent run, returning what each stage produced."""

    async def fake_stream(_agent, **_kwargs):
        yield ("run", {"run_id": 7, "session_id": "link-intake", "kind": "link_intake"})
        for author in ("reader", "matcher"):
            yield ("event", {"author": author, "text": "", "partial": False})
        yield (
            "state",
            {
                READ_STATE_KEY: posting,
                ASSESSED_STATE_KEY: assessment
                if assessment is not None
                else {"fit_score": 8.5, "fit_rationale": "PyTorch on both sides", "confidence": "high"},
            },
        )
        yield ("done", {"run_id": 7, "text": "", "invocation_id": "inv-7"})

    return fake_stream


@pytest.fixture
def fake_import(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A live link, a readable page, and no model or network anywhere."""
    seen: dict[str, Any] = {"fetches": []}

    async def fake_fetch(url: str):
        seen["fetches"].append(url)
        return verification.UrlCheck(url=url, status=verification.OK, http_status=200), PAGE

    async def fake_audit(**kwargs):
        seen["audited"] = kwargs.get("artifact")
        return {"overall": 8.0}

    monkeypatch.setattr(flows.verification, "fetch_posting", fake_fetch)
    monkeypatch.setattr(flows, "build_digest", _no_digest)
    monkeypatch.setattr(flows, "audit_artifact", fake_audit)
    monkeypatch.setattr(
        flows,
        "stream",
        _fake_run({"title": "ML Research Intern", "company": "Acme", "url": POSTING_URL}),
    )
    return seen


async def _errors(url: str) -> list[str]:
    return [
        str(data.get("error"))
        async for event, data in flows.import_link_stream(url)
        if event == "error"
    ]


class TestLinksItRefuses:
    """Each refusal is a sentence the candidate can act on, not a saved card."""

    async def test_a_careers_index_is_refused_without_fetching_it(
        self, fake_import: dict[str, Any]
    ) -> None:
        # The same shape rule that drops these from a search run answers here in
        # a millisecond, instead of after a fetch and two model calls.
        errors = await _errors("https://www.acme.com/careers")
        assert errors and "not open a single job posting" in errors[0]
        assert fake_import["fetches"] == []

    async def test_a_board_landing_page_is_refused(self, fake_import: dict[str, Any]) -> None:
        errors = await _errors("https://jobs.lever.co/acme")
        assert errors and "jobs.lever.co" in errors[0]
        assert fake_import["fetches"] == []

    async def test_something_that_is_not_a_link_is_refused(
        self, fake_import: dict[str, Any]
    ) -> None:
        errors = await _errors("ML Research Intern at Acme")
        assert errors and "does not look like a link" in errors[0]

    async def test_a_dead_link_is_refused_with_what_it_returned(
        self, monkeypatch: pytest.MonkeyPatch, fake_import: dict[str, Any]
    ) -> None:
        async def dead(url: str):
            return verification.UrlCheck(url=url, status=verification.DEAD, http_status=404), ""

        monkeypatch.setattr(flows.verification, "fetch_posting", dead)
        errors = await _errors(POSTING_URL)
        assert errors and "does not reach a posting" in errors[0]
        with session_scope() as session:
            assert session.exec(select(JobPosting)).all() == []

    async def test_an_unreadable_page_is_refused_rather_than_guessed_at(
        self, monkeypatch: pytest.MonkeyPatch, fake_import: dict[str, Any]
    ) -> None:
        # Bot protection with the browser fallback off: no text, so nothing to
        # read. Inventing a posting from the challenge page is the one outcome
        # worse than telling the candidate it did not work.
        async def walled(url: str):
            return (
                verification.UrlCheck(url=url, status=verification.OK, http_status=200),
                "<html><body>Just a moment...</body></html>",
            )

        monkeypatch.setattr(flows.verification, "fetch_posting", walled)
        errors = await _errors(POSTING_URL)
        assert errors and "nothing readable" in errors[0]

    async def test_a_page_the_reader_says_is_not_a_posting_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, fake_import: dict[str, Any]
    ) -> None:
        # An empty title is how the Reader reports "this is a list of roles".
        monkeypatch.setattr(flows, "stream", _fake_run({"title": "", "company": "Acme"}))
        errors = await _errors(POSTING_URL)
        assert errors and "single job posting" in errors[0]
        with session_scope() as session:
            assert session.exec(select(JobPosting)).all() == []


class TestWhatItSaves:
    async def test_the_posting_lands_on_the_list_scored_and_verified(
        self, fake_import: dict[str, Any]
    ) -> None:
        result = await flows.import_link(POSTING_URL)

        assert result["job_id"]
        assert result["saved"]["created"] == 1
        with session_scope() as session:
            saved = session.exec(select(JobPosting)).one()
            assert saved.title == "ML Research Intern"
            assert saved.company == "Acme"
            assert saved.url == POSTING_URL
            assert saved.fit_score == 8.5
            assert saved.url_status == verification.OK
            assert saved.dismissed is False

    async def test_the_url_saved_is_the_one_that_was_pasted(
        self, monkeypatch: pytest.MonkeyPatch, fake_import: dict[str, Any]
    ) -> None:
        # The Reader is told to copy the link verbatim. This is the field the
        # whole row is identified by, so Python holds it rather than trusting
        # that — a model that "tidies" a query string off a requisition URL
        # would otherwise save a link to somebody else's job.
        monkeypatch.setattr(
            flows,
            "stream",
            _fake_run(
                {"title": "ML Research Intern", "company": "Acme", "url": "https://acme.com/tidied"}
            ),
        )
        await flows.import_link(POSTING_URL)
        with session_scope() as session:
            assert session.exec(select(JobPosting)).one().url == POSTING_URL

    async def test_a_url_pasted_without_its_scheme_still_works(
        self, fake_import: dict[str, Any]
    ) -> None:
        result = await flows.import_link("boards.greenhouse.io/acme/jobs/4012345 ")
        assert result["job_id"]
        assert fake_import["fetches"] == [POSTING_URL]

    async def test_the_page_date_is_parsed_into_the_ordering_key(
        self, monkeypatch: pytest.MonkeyPatch, fake_import: dict[str, Any]
    ) -> None:
        # `posted_on` is what the Jobs page sorts on. A posting saved with only
        # the prose date would sort as undated forever.
        monkeypatch.setattr(
            flows,
            "stream",
            _fake_run(
                {
                    "title": "ML Research Intern",
                    "company": "Acme",
                    "url": POSTING_URL,
                    "posted_at": "2026-08-20",
                }
            ),
        )
        await flows.import_link(POSTING_URL)
        with session_scope() as session:
            assert session.exec(select(JobPosting)).one().posted_on == "2026-08-20"

    async def test_the_source_falls_back_to_the_site_the_link_is_on(
        self, fake_import: dict[str, Any]
    ) -> None:
        with session_scope():
            pass
        await flows.import_link(POSTING_URL)
        with session_scope() as session:
            assert session.exec(select(JobPosting)).one().source == "boards.greenhouse.io"

    async def test_pasting_a_dismissed_posting_brings_it_back(
        self, fake_import: dict[str, Any]
    ) -> None:
        # Dismissing is an answer to "should I have found this?", and a search
        # run must never overrule it. Pasting the link is a different question
        # — the candidate is asking for this one by name.
        await flows.import_link(POSTING_URL)
        with session_scope() as session:
            posting = session.exec(select(JobPosting)).one()
            posting.dismissed = True
            session.add(posting)

        result = await flows.import_link(POSTING_URL)

        assert result["restored"] is True
        assert result["already_saved"] is True
        with session_scope() as session:
            assert session.exec(select(JobPosting)).one().dismissed is False

    async def test_pasting_a_posting_whose_application_was_trashed_brings_that_back(
        self, fake_import: dict[str, Any]
    ) -> None:
        # Same principle, other trash — and since a paste tracks the posting,
        # this is now the ordinary way to change your mind about a pasted one:
        # throw the application away from the Tracker, then paste it again. It
        # comes back to the board with everything it had.
        await flows.import_link(POSTING_URL)
        with session_scope() as session:
            application = session.exec(select(Application)).one()
            application.trashed_at = utcnow()
            session.add(application)

        result = await flows.import_link(POSTING_URL)

        assert result["untrashed"] is True
        assert result["restored"] is False
        with session_scope() as session:
            assert session.exec(select(Application)).one().trashed_at is None

    async def test_pasting_a_posting_says_yes_to_it(
        self, fake_import: dict[str, Any]
    ) -> None:
        # The swipe right, taken on the candidate's behalf. They went and found
        # this posting and fetched its link; the deck exists to make a choice
        # they have already made.
        result = await flows.import_link(POSTING_URL)

        assert result["tracked"] is True
        assert result["application_id"]
        with session_scope() as session:
            application = session.exec(select(Application)).one()
            assert application.id == result["application_id"]
            assert application.job_posting_id == result["job_id"]
            # Never pinned: a pin is a second thing to say, and the deck's up
            # swipe is where it is said.
            assert application.pinned is False
            assert application.trashed_at is None
            # The same first event a swipe writes, so the Tracker can say where
            # this application came from.
            event = session.exec(select(ApplicationEvent)).one()
            assert event.to_status == ApplicationStatus.SAVED
            assert "pasted" in event.note

    async def test_the_application_opens_in_the_postings_own_language(
        self, monkeypatch: pytest.MonkeyPatch, fake_import: dict[str, Any]
    ) -> None:
        # Nobody is asked which language to write in any more, so the posting is.
        # `services/language_check.posting_language` reads it off the prose the
        # Reader wrote, and it lands on the application as the language the
        # package will be generated in.
        monkeypatch.setattr(
            flows,
            "stream",
            _fake_run(
                {
                    "title": "Stage Data Scientist H/F",
                    "company": "Acme",
                    "url": POSTING_URL,
                    "description": (
                        "Au sein de notre équipe Data, vous participerez à la conception "
                        "et à la mise en production de modèles de Machine Learning."
                    ),
                }
            ),
        )
        await flows.import_link(POSTING_URL)
        with session_scope() as session:
            assert session.exec(select(Application)).one().language == "fr"

    async def test_a_second_posting_with_the_same_title_gets_its_own_row(
        self, fake_import: dict[str, Any]
    ) -> None:
        # Same company, same title, different posting: the title match a search
        # run uses folded the second paste into the first one's row, overwriting
        # it and its application (2026-10-06). The link is the identity here.
        first = await flows.import_link(POSTING_URL)
        second = await flows.import_link("https://boards.greenhouse.io/acme/jobs/4099999")

        assert second["already_saved"] is False
        assert second["job_id"] != first["job_id"]
        assert second["application_id"] != first["application_id"]
        with session_scope() as session:
            urls = {p.url for p in session.exec(select(JobPosting)).all()}
            assert urls == {POSTING_URL, "https://boards.greenhouse.io/acme/jobs/4099999"}
            assert len(session.exec(select(Application)).all()) == 2

    async def test_pasting_one_already_tracked_does_not_track_it_twice(
        self, fake_import: dict[str, Any]
    ) -> None:
        await flows.import_link(POSTING_URL)
        result = await flows.import_link(POSTING_URL)

        # Honest on a re-paste: the posting was re-read and re-scored, and the
        # application it already had is the one the result points at.
        assert result["tracked"] is False
        assert result["application_id"]
        with session_scope() as session:
            assert len(session.exec(select(Application)).all()) == 1

    async def test_the_tracked_posting_is_off_the_deck(
        self, fake_import: dict[str, Any]
    ) -> None:
        # The consequence the candidate sees. `api/jobs.list_jobs` keeps every
        # posting with an application out of the deck, so a pasted posting is
        # never swiped on — the result card links to the application instead.
        await flows.import_link(POSTING_URL)
        assert list_jobs(view="deck")["jobs"] == []

    async def test_the_score_is_audited_like_any_other_ranking(
        self, fake_import: dict[str, Any]
    ) -> None:
        result = await flows.import_link(POSTING_URL)
        assert result["audit"] == {"overall": 8.0}
        assert fake_import["audited"]["jobs"][0]["title"] == "ML Research Intern"


class TestTheProgressItReports:
    async def test_every_stage_announces_itself(self, fake_import: dict[str, Any]) -> None:
        phases = [
            data["phase"]
            async for event, data in flows.import_link_stream(POSTING_URL)
            if event == "phase"
        ]
        assert phases == ["fetch", "reader", "matcher", "save", "audit"]


class TestReadingThePage:
    """`page_text` is what stands between 400 KB of markup and the prompt."""

    def test_the_structured_posting_is_pulled_out_of_the_page(self) -> None:
        posting = page_text.json_ld_posting(PAGE)
        assert posting is not None
        assert posting["title"] == "ML Research Intern"
        assert posting["datePosted"] == "2026-08-20"

    def test_it_is_found_however_the_site_nests_it(self) -> None:
        wrapped = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@graph":['
            '{"@type":"BreadcrumbList"},{"@type":["JobPosting"],"title":"Buried"}]}'
            "</script>"
        )
        assert page_text.json_ld_posting(wrapped)["title"] == "Buried"

    def test_a_malformed_block_does_not_hide_a_valid_one(self) -> None:
        broken = (
            '<script type="application/ld+json">{not json at all}</script>'
            '<script type="application/ld+json">{"@type":"JobPosting","title":"Second"}</script>'
        )
        assert page_text.json_ld_posting(broken)["title"] == "Second"

    def test_a_page_with_no_structured_data_yields_none(self) -> None:
        assert page_text.json_ld_posting("<html><body>Nothing here</body></html>") is None

    def test_scripts_and_styles_are_not_page_text(self) -> None:
        text = page_text.readable(PAGE)
        assert "window.analytics" not in text
        assert "color: red" not in text
        assert "Six-month internship on the research team" in text

    def test_list_items_keep_their_boundaries(self) -> None:
        # Without this a requirements list arrives as one run-on sentence and
        # the Reader has to guess where each item ended.
        text = page_text.readable("<ul><li>PyTorch</li><li>Master's</li></ul>")
        assert text.splitlines() == ["PyTorch", "", "Master's"]

    def test_the_facts_and_the_prose_both_reach_the_prompt(self) -> None:
        prompt = page_text.for_reader(PAGE)
        assert "schema.org JobPosting" in prompt
        assert "- title: ML Research Intern" in prompt
        assert "- datePosted: 2026-08-20" in prompt
        # The nested company and city are flattened rather than left as objects.
        assert "- company: Acme" in prompt
        assert "Paris" in prompt
        assert "The visible text of the page" in prompt

    def test_an_empty_page_reads_as_empty(self) -> None:
        # The caller's cue to open a real browser, not something to hand a model.
        assert page_text.for_reader("") == ""


class TestNamingTheSite:
    def test_a_priority_board_is_called_by_its_name(self) -> None:
        assert (
            job_links.site_name("https://www.welcometothejungle.com/fr/companies/x/jobs/y")
            == "Welcome to the Jungle"
        )

    def test_anything_else_is_called_by_its_host(self) -> None:
        assert job_links.site_name("https://careers.acme.com/jobs/1") == "careers.acme.com"

    def test_a_non_url_has_no_name(self) -> None:
        assert job_links.site_name("not a url") == ""


class TestTheScorerSeesOnlyTheBrief:
    """A paste is scored against the search brief alone (2026-09-23).

    The playbook, the profile, the feedback digest and the list of saved
    postings are what a search run needs to choose fifteen postings out of
    dozens. A paste chooses nothing, so they were only cost — and a block that
    creeps back in is invisible from the outside: the run still succeeds, just
    slower and dearer.
    """

    class Ctx:
        state: dict[str, object] = {"read_posting": {"title": "ML Research Intern"}}

    async def test_the_prompt_carries_the_brief_and_nothing_else(self) -> None:
        from tinternship_backend.agents.reader import build_scorer
        from tinternship_backend.services import context_blocks

        prompt = await build_scorer().instruction(self.Ctx())
        assert context_blocks.brief_block() in prompt
        assert "ML Research Intern" in prompt
        assert context_blocks.MISSING_PLAYBOOK not in prompt
        assert context_blocks.MISSING_PROFILE not in prompt
        assert "Candidate master profile" not in prompt
        assert "Feedback from the candidate's application history" not in prompt
