"""Dedup keys and job persistence — the parts that silently corrupt data if wrong."""

from __future__ import annotations

from sqlmodel import select

from tinternship_backend.db.engine import session_scope
from tinternship_backend.db.models import JobPosting
from tinternship_backend.tools.persistence import (
    UNUSABLE_LINK,
    dedupe_key,
    paste_key,
    posting_address,
    same_role,
    save_job_postings,
)


class TestDedupeKey:
    def test_same_role_different_aggregator_collapses(self):
        # The same job re-hosted by two aggregators must be one posting.
        a = dedupe_key("Machine Learning Intern", "Mistral AI", "https://indeed.fr/viewjob?jk=1")
        b = dedupe_key("Machine Learning Intern", "Mistral AI", "https://welcometothejungle.com/x")
        assert a == b

    def test_seasonal_and_gender_noise_is_stripped(self):
        a = dedupe_key("Stage Data Scientist H/F 2027", "Criteo", "https://criteo.com/1")
        b = dedupe_key("Data Scientist (Stagiaire) f/h", "Criteo", "https://criteo.com/2")
        assert a == b

    def test_different_companies_stay_separate(self):
        a = dedupe_key("Backend Intern", "Datadog", "https://x.com/1")
        b = dedupe_key("Backend Intern", "Doctolib", "https://x.com/1")
        assert a != b

    def test_different_roles_stay_separate(self):
        a = dedupe_key("Backend Intern", "Datadog", "https://x.com/1")
        b = dedupe_key("Frontend Intern", "Datadog", "https://x.com/2")
        assert a != b

    def test_missing_company_falls_back_to_host(self):
        # Without this, every company-less posting would collapse into one row.
        a = dedupe_key("Research Intern", "", "https://lab-a.fr/jobs/1")
        b = dedupe_key("Research Intern", "", "https://lab-b.fr/jobs/1")
        assert a != b


class TestSaveJobPostings:
    def test_saves_and_updates_rather_than_duplicating(self):
        first = save_job_postings(
            [
                {
                    "title": "ML Intern",
                    "company": "Mistral AI",
                    "url": "https://mistral.ai/jobs/1",
                    "fit_score": 8.5,
                    "fit_rationale": "Strong PyTorch match.",
                    "strengths": ["PyTorch"],
                    "risks": ["No publications"],
                    "keywords": ["PyTorch", "LLM"],
                }
            ]
        )
        assert first == {"status": "ok", "created": 1, "updated": 0, "skipped": 0, "saved": 1}

        second = save_job_postings(
            [
                {
                    "title": "ML Intern",
                    "company": "Mistral AI",
                    "url": "https://jobboard.com/rehosted",
                    "fit_score": 9.1,
                }
            ]
        )
        assert second["created"] == 0
        assert second["updated"] == 1

        with session_scope() as session:
            postings = session.exec(select(JobPosting)).all()
            assert len(postings) == 1
            assert postings[0].fit_score == 9.1

    def test_a_second_run_adds_to_the_first_run_s_postings(self):
        # The whole point of running again. Nothing a run returns can remove a
        # posting already on the page: the only rows it touches are the ones it
        # found again, and those it updates in place.
        save_job_postings(
            [
                {"title": "ML Intern", "company": "Mistral AI", "url": "https://mistral.ai/1",
                 "fit_score": 9.0},
                {"title": "Data Intern", "company": "Criteo", "url": "https://criteo.com/1",
                 "fit_score": 8.0},
            ]
        )
        second = save_job_postings(
            [
                # Found again — same posting, refreshed score.
                {"title": "ML Intern", "company": "Mistral AI", "url": "https://mistral.ai/1",
                 "fit_score": 9.4},
                {"title": "NLP Intern", "company": "Hugging Face", "url": "https://hf.co/1",
                 "fit_score": 8.6},
            ]
        )
        assert (second["created"], second["updated"]) == (1, 1)

        with session_scope() as session:
            # Read inside the session — the rows detach when it closes.
            scores = {p.title: p.fit_score for p in session.exec(select(JobPosting)).all()}
        assert set(scores) == {"ML Intern", "Data Intern", "NLP Intern"}
        # The one the second run never mentioned is untouched, not dropped.
        assert scores["Data Intern"] == 8.0
        assert scores["ML Intern"] == 9.4

    def test_skips_entries_without_an_identity(self):
        result = save_job_postings(
            [
                {"title": "", "company": "Acme", "url": "https://acme.com"},
                {"title": "Intern", "company": "", "url": ""},
                {"not": "a posting"},
                "garbage",
            ]
        )
        assert result["saved"] == 0

    def test_a_posting_with_no_link_is_not_saved(self):
        # The user cannot read it, check it or apply to it, so the card is worse
        # than the missing row. `services/job_links.py` drops these upstream;
        # this is the backstop that keeps one out of the database regardless.
        result = save_job_postings(
            [
                {"title": "Ghost Intern", "company": "Acme", "url": ""},
                {"title": "Real Intern", "company": "Acme", "url": "https://acme.com/jobs/1"},
            ]
        )
        assert result == {"status": "ok", "created": 1, "updated": 0, "skipped": 1, "saved": 1}
        with session_scope() as session:
            assert [p.title for p in session.exec(select(JobPosting)).all()] == ["Real Intern"]

    def test_a_posting_whose_link_misses_the_posting_is_not_saved(self):
        # The run drops these before it gets here. This is the backstop: a 404
        # that gets in once sits on the Jobs page until it is noticed by hand.
        result = save_job_postings(
            [
                {"title": "Closed", "company": "Acme", "url": "https://acme.com/jobs/1",
                 "url_status": "dead"},
                {"title": "Careers page", "company": "Acme", "url": "https://acme.com/jobs/2",
                 "url_status": "index"},
                {"title": "Real", "company": "Acme", "url": "https://acme.com/jobs/3",
                 "url_status": "ok"},
                # Unverifiable is not the same as wrong — a board behind bot
                # protection still gets shown.
                {"title": "Walled", "company": "Acme", "url": "https://acme.com/jobs/4",
                 "url_status": "blocked"},
            ]
        )
        assert result["skipped"] == 2
        with session_scope() as session:
            titles = {p.title for p in session.exec(select(JobPosting)).all()}
        assert titles == {"Real", "Walled"}

    def test_a_saved_posting_whose_link_breaks_later_is_dismissed(self):
        job = {"title": "ML Intern", "company": "Acme", "url": "https://acme.com/jobs/1"}
        save_job_postings([{**job, "url_status": "ok"}])
        save_job_postings([{**job, "url_status": "dead"}])

        with session_scope() as session:
            posting = session.exec(select(JobPosting)).one()
            # Dismissed rather than deleted: off the page, one toggle from being
            # seen. Read inside the session — the row detaches when it closes.
            assert posting.dismissed
            assert posting.url_status == "dead"

    def test_the_broken_link_statuses_match_the_verifier(self):
        # Spelled out in two places so `tools/` need not import `services/`.
        from tinternship_backend.services.verification import UNUSABLE

        assert UNUSABLE_LINK == UNUSABLE

    def test_the_one_line_summary_is_persisted(self):
        # The deck shows one card at a time and `summary` is the only prose on
        # it. Dropping it here would leave every card silent about the role
        # while `description` — three to six sentences, too long for a card —
        # sat in the row unread.
        save_job_postings(
            [
                {
                    "title": "ML Intern",
                    "company": "Mistral AI",
                    "url": "https://mistral.ai/jobs/1",
                    "summary": "Six-month LLM evaluation internship in Paris.",
                    "description": "A much longer three-to-six sentence body.",
                }
            ]
        )
        with session_scope() as session:
            posting = session.exec(select(JobPosting)).one()
            assert posting.summary == "Six-month LLM evaluation internship in Paris."
            assert posting.description == "A much longer three-to-six sentence body."

    def test_a_posting_that_gave_no_summary_saves_an_empty_one(self):
        save_job_postings(
            [{"title": "ML Intern", "company": "Mistral AI", "url": "https://mistral.ai/jobs/1"}]
        )
        with session_scope() as session:
            assert session.exec(select(JobPosting)).one().summary == ""

    def test_scalar_fields_are_coerced_to_lists(self):
        save_job_postings(
            [
                {
                    "title": "Data Intern",
                    "company": "Acme",
                    "url": "https://acme.com/1",
                    "requirements": "Python",
                    "risks": None,
                }
            ]
        )
        with session_scope() as session:
            posting = session.exec(select(JobPosting)).one()
            assert posting.requirements == ["Python"]
            assert posting.risks == []


class TestFuzzyTitleMatching:
    """The exact hash key missed the same LightOn role listed under two titles."""

    def test_a_longer_title_still_matches_its_shorter_form(self):
        assert same_role(
            "Open Machine Learning Intern",
            "Open Machine Learning Intern / Stage Machine Learning",
        )

    def test_french_and_english_forms_of_one_role_match(self):
        assert same_role("Data Scientist Intern", "Stagiaire Data Scientist H/F")

    def test_genuinely_different_roles_do_not_match(self):
        assert not same_role("Machine Learning Intern", "Frontend Developer Intern")
        assert not same_role("Data Engineer Intern", "Product Manager Intern")

    def test_generic_words_alone_are_not_enough_to_match(self):
        # "Engineer"/"Intern" are stripped, so these share no meaningful tokens.
        assert not same_role("Software Engineer Intern", "Hardware Engineer Intern")

    def test_a_short_title_does_not_swallow_a_longer_one(self):
        # The overlap is measured against the larger token set. Measured against
        # the smaller one, "AI Intern" is {ai} and matches anything at that
        # company with "AI" in the title — and a match overwrites the row, so a
        # re-run silently replaced a posting the candidate already had.
        assert not same_role("AI Intern", "AI Research Intern")
        assert not same_role("Data Science Intern", "Data Science Intern (MLOps & Deployment)")

    def test_a_second_role_at_the_same_company_keeps_its_own_card(self):
        save_job_postings(
            [{"title": "AI Intern", "company": "Acme", "url": "https://acme.com/jobs/1",
              "fit_score": 9.0}]
        )
        second = save_job_postings(
            [{"title": "AI Research Intern", "company": "Acme", "url": "https://acme.com/jobs/2",
              "fit_score": 7.0}]
        )
        assert second["created"] == 1
        with session_scope() as session:
            postings = session.exec(select(JobPosting)).all()
            assert {p.title for p in postings} == {"AI Intern", "AI Research Intern"}
            # The first card is untouched, not overwritten in place.
            first = next(p for p in postings if p.title == "AI Intern")
            assert (first.url, first.fit_score) == ("https://acme.com/jobs/1", 9.0)

    def test_a_near_duplicate_updates_rather_than_creating_a_second_card(self):
        save_job_postings(
            [{"title": "Open Machine Learning Intern", "company": "LightOn",
              "url": "https://lighton.ai/careers", "fit_score": 9.0}]
        )
        save_job_postings(
            [{"title": "Open Machine Learning Intern / Stage Machine Learning",
              "company": "LightOn", "url": "https://lighton.ai/careers/ml", "fit_score": 8.8}]
        )
        with session_scope() as session:
            postings = session.exec(select(JobPosting)).all()
            assert len(postings) == 1
            assert postings[0].fit_score == 8.8

    def test_the_same_title_at_different_companies_stays_separate(self):
        save_job_postings(
            [{"title": "ML Intern", "company": "LightOn", "url": "https://a.example"},
             {"title": "ML Intern", "company": "Mistral AI", "url": "https://b.example"}]
        )
        with session_scope() as session:
            assert len(session.exec(select(JobPosting)).all()) == 2


class TestPastedIdentity:
    """A paste is identified by its link or its text, never by company and title.

    Two postings at one company with look-alike titles were one row to
    `find_existing`, so pasting the second overwrote the first (2026-10-06).
    """

    def test_tracking_noise_does_not_change_the_address(self):
        assert posting_address("https://www.acme.com/jobs/12/?utm_source=x#apply") == (
            posting_address("acme.com/jobs/12")
        )

    def test_a_query_that_names_the_posting_is_kept(self):
        assert posting_address("https://indeed.fr/viewjob?jk=1") != posting_address(
            "https://indeed.fr/viewjob?jk=2"
        )

    def test_two_links_with_the_same_title_are_two_postings(self):
        for n in (1, 2):
            url = f"https://acme.com/jobs/{n}"
            save_job_postings(
                [{"title": "Stage Data Scientist H/F", "company": "Acme", "url": url}],
                pasted_as=paste_key(url),
            )
        with session_scope() as session:
            assert len(session.exec(select(JobPosting)).all()) == 2

    def test_two_texts_with_look_alike_titles_are_two_postings(self):
        for city in ("Paris", "Lyon"):
            save_job_postings(
                [{"title": f"Data Science Intern - {city}", "company": "Acme", "url": ""}],
                allow_missing_url=True,
                pasted_as=paste_key("", f"Data Science Intern in {city}, team {city}"),
            )
        with session_scope() as session:
            assert len(session.exec(select(JobPosting)).all()) == 2

    def test_a_paste_finds_the_row_a_search_saved_for_the_same_link(self):
        save_job_postings([{"title": "ML Intern", "company": "Acme", "url": "https://acme.com/jobs/7"}])
        url = "https://www.acme.com/jobs/7?utm_medium=email"
        result = save_job_postings(
            [{"title": "Machine Learning Intern", "company": "Acme", "url": url}],
            pasted_as=paste_key(url),
        )
        assert result["updated"] == 1
        with session_scope() as session:
            assert len(session.exec(select(JobPosting)).all()) == 1
