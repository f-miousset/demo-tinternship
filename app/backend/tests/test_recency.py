"""Recency: parsing what a posting claims, and what that claim costs it.

An internship posting is perishable, so `services/recency.py` reorders the
ranking on age. That makes date parsing load-bearing in a way it usually is not:
a `3 days ago` the parser drops is a fresh posting demoted to middle-aged, and a
`6 months` it reads as an age when the posting meant its own duration is a live
job buried. Both directions are tested here.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tinternship_backend.services import recency

TODAY = date(2026, 8, 18)


class TestParse:
    """The four dialects that actually reach us, and the ones that must not."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            # Structured boards: Adzuna's `created`, and plain ISO.
            ("2026-08-12T09:30:00Z", date(2026, 8, 12)),
            ("2026-08-12", date(2026, 8, 12)),
            ("2026-08-12T09:30:00+02:00", date(2026, 8, 12)),
            # A month with no day is the month. The 1st is the conservative
            # read: overstating age costs a slot, understating it costs an
            # application into a closed pipeline.
            ("2026-07", date(2026, 7, 1)),
            # Posting pages, in the three languages this app searches in.
            ("12 August 2026", date(2026, 8, 12)),
            ("August 12, 2026", date(2026, 8, 12)),
            ("Aug 12, 2026", date(2026, 8, 12)),
            ("12 août 2026", date(2026, 8, 12)),
            ("12 juillet 2026", date(2026, 7, 12)),
            ("12. August 2026", date(2026, 8, 12)),
            ("12/08/2026", date(2026, 8, 12)),
            # Search snippets, which is where most leads come from.
            ("Posted 3 days ago", TODAY - timedelta(days=3)),
            ("posted 2 weeks ago", TODAY - timedelta(days=14)),
            ("Publiée il y a 5 jours", TODAY - timedelta(days=5)),
            ("il y a 2 semaines", TODAY - timedelta(days=14)),
            ("vor 3 Tagen veröffentlicht", TODAY - timedelta(days=3)),
            ("posted 20 hours ago", TODAY),
            ("today", TODAY),
            ("aujourd'hui", TODAY),
            ("yesterday", TODAY - timedelta(days=1)),
            ("hier", TODAY - timedelta(days=1)),
            ("Just posted", TODAY),
        ],
    )
    def test_reads_a_real_date(self, text: str, expected: date) -> None:
        assert recency.parse(text, on=TODAY) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            None,
            "unknown",
            "rolling",
            # The trap this parser exists to avoid: a duration, not an age. A
            # posting whose `posted_at` was filled with its own length must not
            # be treated as six months old and buried.
            "6 months",
            "stage de 6 mois",
            "durée 4 à 6 mois",
            # A start date is not a posting date.
            "starts September 2026",
        ],
    )
    def test_refuses_what_is_not_a_posting_date(self, text: str | None) -> None:
        assert recency.parse(text, on=TODAY) is None

    def test_a_future_date_is_refused_rather_than_treated_as_fresh(self) -> None:
        """A start date filed as a posting date must not become the top result."""
        assert recency.parse("2027-01-15", on=TODAY) is None

    def test_age_is_measured_from_today(self) -> None:
        assert recency.age_days("2026-08-11", on=TODAY) == 7
        assert recency.age_days("nothing here", on=TODAY) is None


class TestFromPage:
    """The employer's own answer, read off the page verification already fetched."""

    def test_reads_schema_org_date_posted(self) -> None:
        html = """
        <html><head><script type="application/ld+json">
        {"@type": "JobPosting", "title": "ML Intern", "datePosted": "2026-08-14"}
        </script></head><body>…</body></html>
        """
        assert recency.from_page(html) == "2026-08-14"

    def test_reads_it_html_escaped_too(self) -> None:
        """Some boards embed the JSON-LD into an attribute rather than a script."""
        html = '<div data-page="{&quot;datePosted&quot;:&quot;2026-08-01&quot;}">'
        assert recency.from_page(html) == "2026-08-01"

    def test_falls_back_to_the_published_time_meta(self) -> None:
        html = '<meta property="article:published_time" content="2026-07-30T08:00:00Z" />'
        assert recency.from_page(html) == "2026-07-30"

    def test_a_page_that_says_nothing_returns_nothing(self) -> None:
        assert recency.from_page("<html><body>Great opportunity!</body></html>") == ""

    def test_a_nonsense_date_is_not_believed(self) -> None:
        html = '<script>{"datePosted": "soon"}</script>'
        assert recency.from_page(html) == ""


class TestFreshness:
    """What an age is worth. The shape matters more than any single number."""

    def test_today_is_worth_full_marks(self) -> None:
        assert recency.freshness(0) == pytest.approx(1.0)

    def test_freshness_only_ever_falls_with_age(self) -> None:
        values = [recency.freshness(age) for age in range(0, 365, 7)]
        assert values == sorted(values, reverse=True)

    def test_a_half_life_costs_half_the_distance_to_the_floor(self) -> None:
        half = recency.freshness(round(recency.half_life_days()))
        assert half == pytest.approx(recency.FLOOR + (1 - recency.FLOOR) / 2, abs=0.02)

    def test_age_discounts_a_match_but_never_annuls_it(self) -> None:
        """A great old posting still beats a poor fresh one. That is the floor's job."""
        assert recency.score(9.0, 400) > recency.score(2.0, 0)

    def test_an_undated_posting_sits_between_fresh_and_stale(self) -> None:
        """Neither promoted nor buried — the honest position for "it didn't say"."""
        assert recency.freshness(3) > recency.freshness(None) > recency.freshness(120)


class TestRank:
    """The promise: of two comparable matches, the fresher one is on top."""

    def _job(self, title: str, fit: float, posted: str) -> dict:
        return {"title": title, "fit_score": fit, "posted_at": posted}

    def test_a_fresh_posting_outranks_a_slightly_better_stale_one(self) -> None:
        ranked = recency.rank(
            [
                self._job("stale", 9.0, "2026-03-01"),
                self._job("fresh", 8.0, "2026-08-16"),
            ],
            on=TODAY,
        )
        assert [job["title"] for job in ranked] == ["fresh", "stale"]

    def test_equal_ages_are_still_ordered_by_fit(self) -> None:
        ranked = recency.rank(
            [
                self._job("weaker", 6.0, "2026-08-16"),
                self._job("stronger", 8.5, "2026-08-16"),
            ],
            on=TODAY,
        )
        assert [job["title"] for job in ranked] == ["stronger", "weaker"]

    def test_an_undated_posting_is_not_thrown_to_the_bottom(self) -> None:
        """Most search leads carry no date; burying them would empty the page."""
        ranked = recency.rank(
            [
                self._job("stale", 8.0, "2026-01-04"),
                self._job("undated", 8.0, ""),
            ],
            on=TODAY,
        )
        assert [job["title"] for job in ranked] == ["undated", "stale"]

    def test_ranking_annotates_rather_than_rewriting_the_score(self) -> None:
        """`fit_score` stays the matcher's judgement — the discount is a separate key."""
        ranked = recency.rank([self._job("job", 7.5, "2026-05-01")], on=TODAY)
        assert ranked[0]["fit_score"] == 7.5
        assert ranked[0]["recency_score"] < 7.5
        assert ranked[0]["posted_on"] == "2026-05-01"
        assert ranked[0]["posted_days_ago"] == 109

    def test_tally_buckets_what_the_run_found(self) -> None:
        counts = recency.tally(
            recency.rank(
                [
                    self._job("a", 8.0, "2026-08-16"),
                    self._job("b", 8.0, "2026-08-01"),
                    self._job("c", 8.0, "2026-06-20"),
                    self._job("d", 8.0, "2025-11-02"),
                    self._job("e", 8.0, ""),
                ],
                on=TODAY,
            )
        )
        assert counts == {"week": 1, "month": 1, "quarter": 1, "older": 1, "undated": 1}
