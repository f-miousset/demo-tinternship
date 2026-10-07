"""Does the link open the posting? — the guard behind two real complaints.

Both come from a live run. Postings were saved whose link went to the company's
careers site rather than the job, and postings were saved with no link at all.
The URL check could not catch either: `careers.3ds.com/jobs/<slug>` returns 200
(after settling on `www.3ds.com/careers`), and a posting with no URL was never
fetched in the first place.
"""

from __future__ import annotations

import pytest

from tinternship_backend.services import job_links as links


class TestShape:
    """What a URL is, judged before spending an HTTP request on it."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.welcometothejungle.com/fr/companies/agoranov/jobs/stage-r-d-ia_paris",
            "https://station-f.welcomekit.co/companies/station-f/jobs/data-intern",
            "https://jobs.stationf.co/companies/hugging-face/jobs/ml-intern_paris",
            "https://www.linkedin.com/jobs/view/4123456789",
            "https://jobs.lever.co/mistral/9a1b2c3d-4e5f-6789-abcd-ef0123456789",
            "https://boards.greenhouse.io/anthropic/jobs/4012345",
            "https://jobs.sap.com/job/Levallois-Perret-Internship/1234567/",
            # An unknown domain with a plausible path is given the benefit of the
            # doubt: a false reject deletes a real job.
            "https://careers.criteo.com/jobs/data-scientist-intern-paris",
            "https://www.thalesgroup.com/fr/careers/R0306189",
        ],
    )
    def test_a_posting_url_is_a_posting(self, url: str) -> None:
        assert links.is_openable(url), links.classify(url).reason

    @pytest.mark.parametrize(
        "url",
        [
            # The exact fabrication this app has already been burned by.
            "https://jobs.lever.co/mistral",
            "https://boards.greenhouse.io/anthropic",
            # A company profile is not a job — Welcome to the Jungle's own caveat.
            "https://www.welcometothejungle.com/fr/companies/agoranov",
            "https://www.linkedin.com/jobs/search?keywords=stage%20data",
            "https://jobs.stationf.co/startups",
            # Saved by a real run: the requisition id trimmed off the end. The
            # site answers 200 from an error page.
            "https://jobs.sap.com/job/Levallois-Perret-Internship-Partner-Solution/",
            # The complaint in one URL: the company's careers site.
            "https://www.3ds.com/careers",
            "https://mistral.ai/careers",
            "https://www.company.com/en/careers/students",
            "https://example.com/jobs",
            "https://example.com/nous-rejoindre",
            "https://example.com/",
        ],
    )
    def test_a_landing_page_is_not_a_posting(self, url: str) -> None:
        verdict = links.classify(url)
        assert verdict.kind == links.INDEX
        assert verdict.reason

    @pytest.mark.parametrize("url", ["", "   ", "not a url", "mailto:jobs@example.com"])
    def test_no_link_is_its_own_verdict(self, url: str) -> None:
        # Distinct from `index`: nothing was found, rather than the wrong thing.
        assert links.classify(url).kind == links.MISSING

    def test_a_grounding_redirect_is_not_a_posting_link(self) -> None:
        # Run 8 ranked a real Saegus posting behind one of these. Its own kind:
        # there *is* a link, it just names Google, hides whatever site it opens
        # from every rule below, and stops working a few weeks after the run.
        # `services/grounding.py` resolves these first, so one arriving here is
        # one that could not be followed.
        url = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQHm9-B6wl"
        verdict = links.classify(url)
        assert verdict.kind == links.REDIRECT
        assert verdict.reason
        assert not links.is_openable(url)

    def test_locale_prefixes_do_not_make_a_careers_page_a_posting(self) -> None:
        assert links.classify("https://acme.com/en-us/careers").kind == links.INDEX
        assert links.classify("https://acme.com/fr/emplois").kind == links.INDEX


class TestLanding:
    """Where the redirects settled — the half a status code cannot see."""

    def test_a_deep_link_that_ends_on_the_careers_site_is_not_the_posting(self) -> None:
        # The real one: 200, and the candidate lands on a search box.
        verdict = links.landing(
            "https://careers.3ds.com/jobs/stage-orchestration-dagents-ia",
            "https://www.3ds.com/careers",
        )
        assert verdict.kind == links.INDEX
        assert "3ds.com/careers" in verdict.reason

    def test_a_redirect_up_the_same_tree_is_not_the_posting(self) -> None:
        assert (
            links.landing("https://acme.com/careers/job/7", "https://acme.com/careers").kind
            == links.INDEX
        )

    def test_an_error_page_is_gone_not_an_index(self) -> None:
        # The other real one: SAP answers 200 from /errorpage/.
        assert (
            links.landing(
                "https://jobs.sap.com/job/Slug/", "https://jobs.sap.com/errorpage/?errortype=x"
            ).kind
            == links.GONE
        )

    def test_a_login_wall_is_not_evidence_the_posting_is_missing(self) -> None:
        # LinkedIn and Hugging Face bounce logged-out clients. Condemning those
        # would throw away real postings, so they get their own verdict.
        assert (
            links.landing(
                "https://huggingface.co/jobs/ml-intern", "https://huggingface.co/login?next=/jobs"
            ).kind
            == links.LOGIN
        )
        assert (
            links.landing(
                "https://www.linkedin.com/jobs/view/123", "https://www.linkedin.com/authwall?x=1"
            ).kind
            == links.LOGIN
        )

    @pytest.mark.parametrize(
        ("url", "final"),
        [
            ("https://acme.com/jobs/1", ""),
            ("https://acme.com/jobs/1", "https://acme.com/jobs/1"),
            # Canonicalisation and tracking params are not a failed redirect.
            ("https://acme.com/jobs/1", "https://acme.com/jobs/1?utm_source=google"),
            ("https://acme.com/jobs/1", "https://www.acme.com/en/jobs/1"),
        ],
    )
    def test_an_ordinary_arrival_is_left_alone(self, url: str, final: str) -> None:
        assert links.landing(url, final).kind == links.POSTING


class TestPartition:
    def test_postings_with_no_usable_link_are_dropped_and_counted(self) -> None:
        kept, dropped = links.partition(
            [
                {"title": "Real", "url": "https://acme.com/jobs/ml-intern-2027"},
                {"title": "No link at all", "url": ""},
                {"title": "No link field"},
                {"title": "Careers page", "url": "https://acme.com/careers"},
            ]
        )
        assert [job["title"] for job in kept] == ["Real"]
        assert dropped == {links.MISSING: 2, links.INDEX: 1}

    def test_nothing_is_dropped_when_every_link_is_a_posting(self) -> None:
        jobs = [{"url": f"https://acme.com/jobs/{i}"} for i in range(3)]
        kept, dropped = links.partition(jobs)
        assert kept == jobs
        assert dropped == {}
