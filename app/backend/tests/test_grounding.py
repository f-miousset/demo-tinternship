"""Grounding-redirect resolution: a link has to name the site it opens.

For a playbook citation that is about being checkable. For a job posting it is
about being right at all — the redirector expires, so a card saved behind one
opens a dead Google URL weeks later.
"""

from __future__ import annotations

import pytest

from tinternship_backend.services import grounding, job_links

REDIRECT = (
    "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQEb0IRcSVtkfqCH"
)
REAL = "https://www.welcometothejungle.com/fr/companies/mistral-ai/jobs"


def test_detects_redirect_urls():
    assert grounding.is_grounding_redirect(REDIRECT)
    assert not grounding.is_grounding_redirect(REAL)
    assert not grounding.is_grounding_redirect("")


async def test_sources_are_rewritten_and_the_redirect_is_kept(monkeypatch):
    async def fake_resolve(urls):
        return {REDIRECT: REAL}

    monkeypatch.setattr(grounding, "resolve_urls", fake_resolve)

    result = await grounding.resolve_sources(
        [
            {"title": "WTTJ", "url": REDIRECT, "takeaway": "Apply in October"},
            {"title": "Already fine", "url": REAL, "takeaway": "n/a"},
        ]
    )
    assert result[0]["url"] == REAL
    # The original is retained so a citation can be reconciled with the trace.
    assert result[0]["redirect_url"] == REDIRECT
    assert result[0]["takeaway"] == "Apply in October"
    assert result[1] == {"title": "Already fine", "url": REAL, "takeaway": "n/a"}


async def test_unresolvable_links_keep_their_redirect_form(monkeypatch):
    async def fake_resolve(urls):
        return {}

    monkeypatch.setattr(grounding, "resolve_urls", fake_resolve)
    sources = [{"title": "Dead", "url": REDIRECT}]
    assert await grounding.resolve_sources(sources) == sources


async def test_empty_input_is_a_no_op():
    assert await grounding.resolve_sources([]) == []
    assert await grounding.resolve_urls([]) == {}


@pytest.mark.parametrize("url", ["", "not-a-url", "https://example.com"])
async def test_non_redirects_are_never_fetched(url):
    # resolve_urls short-circuits before opening a client, so this must not hang
    # or make a network call.
    assert await grounding.resolve_urls([url]) == {}


class TestJobPostings:
    """A posting's link is not a citation — resolving it is correctness, not polish.

    A citation behind a redirect is merely unreadable. A *posting* behind one
    opens a dead Google URL a few weeks after the run that found it, names
    Google as its source, and hides the site from the shape check that is
    supposed to drop careers pages for free.
    """

    @staticmethod
    def _mapping(monkeypatch, mapping: dict[str, str]) -> list[list[str]]:
        """Stub the fetch, recording exactly which URLs it was asked about."""
        asked: list[list[str]] = []

        async def fake_resolve(urls):
            asked.append(list(urls))
            return mapping

        monkeypatch.setattr(grounding, "resolve_urls", fake_resolve)
        return asked

    async def test_a_posting_behind_a_redirect_gets_the_employers_url(self, monkeypatch):
        self._mapping(monkeypatch, {REDIRECT: REAL})

        jobs = await grounding.resolve_jobs(
            [{"title": "ML intern", "company": "Mistral", "url": REDIRECT, "fit_score": 88}]
        )
        assert jobs[0]["url"] == REAL
        # The redirect is kept so the saved posting can be matched to its trace.
        assert jobs[0]["redirect_url"] == REDIRECT
        assert jobs[0]["fit_score"] == 88

    async def test_the_apply_link_is_resolved_too(self, monkeypatch):
        # `apply_url` is what the Apply button opens; a model that cited a
        # redirect for one field had no better source for the other.
        apply_redirect = REDIRECT + "-apply"
        apply_real = REAL + "/apply"
        self._mapping(monkeypatch, {apply_redirect: apply_real})

        jobs = await grounding.resolve_jobs(
            [{"title": "ML intern", "url": REAL, "apply_url": apply_redirect}]
        )
        assert jobs[0]["apply_url"] == apply_real
        assert jobs[0]["url"] == REAL
        # Only `url` earns a `redirect_url`: it is the one the row is identified by.
        assert "redirect_url" not in jobs[0]

    async def test_ordinary_postings_are_left_exactly_as_they_were(self, monkeypatch):
        asked = self._mapping(monkeypatch, {})
        jobs = [{"title": "ML intern", "url": REAL, "apply_url": ""}]
        assert await grounding.resolve_jobs(jobs) == jobs
        # Asked about, but `resolve_urls` never opens a client for a non-redirect.
        assert asked == [[REAL, ""]]

    async def test_an_unresolvable_redirect_keeps_its_form_for_the_shape_gate(
        self, monkeypatch
    ):
        # Non-fatal here on purpose: `job_links.classify` is what refuses it,
        # so the decision lives in one place instead of two.
        self._mapping(monkeypatch, {})
        jobs = [{"title": "Dead end", "url": REDIRECT}]
        assert await grounding.resolve_jobs(jobs) == jobs
        assert job_links.classify(REDIRECT).kind == job_links.REDIRECT

    async def test_an_empty_list_costs_nothing(self):
        assert await grounding.resolve_jobs([]) == []

    async def test_one_url_at_a_time_for_the_pasted_link_path(self, monkeypatch):
        self._mapping(monkeypatch, {REDIRECT: REAL})
        assert await grounding.resolve_url(REDIRECT) == REAL
        # Anything else comes back untouched, so the caller can hand it any link.
        assert await grounding.resolve_url(REAL) == REAL
        assert await grounding.resolve_url("") == ""
