"""`run_investigator` enforces the result count itself.

The Matcher is asked for the top N, but a prompt is a request, not a guarantee.
These tests replace the agent run with a fixture that deliberately over-returns
and check that the pipeline still hands back N — and that it cuts *before*
verification, so the run does not spend HTTP requests on postings it is about
to drop.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from tinternship_backend.agents.investigator import MAX_RESULTS, RANKED_STATE_KEY
from tinternship_backend.services import (
    flows,
    grounding,
    job_links,
    recency,
    verification,
)


@pytest.fixture
def fake_run(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub every side effect of a run; record what each stage was handed."""
    seen: dict[str, Any] = {}

    async def fake_stream(agent, **kwargs):
        seen["payload"] = kwargs.get("payload")
        seen["label"] = kwargs.get("label")
        jobs = [
            {"title": f"Job {index}", "company": f"Co {index}", "url": f"https://e.test/{index}"}
            for index in range(100)
        ]
        yield ("run", {"run_id": 1, "session_id": "investigator", "kind": "investigator"})
        for author in ("query_planner", "scout", "normaliser", "matcher"):
            yield ("event", {"author": author, "text": "", "partial": False})
        yield ("state", {RANKED_STATE_KEY: {"jobs": jobs, "strategy_notes": ""}})
        yield ("done", {"run_id": 1, "text": "", "invocation_id": "inv-1"})

    async def fake_verify(jobs):
        seen["verified"] = seen.get("verified", 0) + len(jobs)
        return [{**job, "url_status": "ok"} for job in jobs], {"ok": len(jobs)}

    async def fake_digest(*_args, **_kwargs):
        return {}

    async def fake_audit(**_kwargs):
        return {}

    def fake_save(jobs):
        seen["saved"] = len(jobs)
        return {"saved": len(jobs), "created": len(jobs)}

    monkeypatch.setattr(flows, "stream", fake_stream)
    monkeypatch.setattr(flows.verification, "verify_jobs", fake_verify)
    monkeypatch.setattr(flows, "build_digest", fake_digest)
    monkeypatch.setattr(flows, "audit_artifact", fake_audit)
    monkeypatch.setattr(flows, "save_job_postings", fake_save)
    return seen


@pytest.mark.parametrize("target", [5, 15, 40])
async def test_returns_exactly_the_target_when_the_matcher_over_returns(
    fake_run: dict[str, Any], target: int
) -> None:
    result = await flows.run_investigator(target_results=target)

    assert len(result["jobs"]) == target
    assert result["target_results"] == target
    assert fake_run["saved"] == target


async def test_good_links_cost_exactly_one_wave(fake_run: dict[str, Any]) -> None:
    # Verification is the expensive part — a browser opens whatever bot
    # protection hides — so a run where every link works checks the target and
    # not one link more, however many spares the matcher handed over.
    await flows.run_investigator(target_results=5)
    assert fake_run["verified"] == 5


class TestLinksTheUserCanOpen:
    """Two complaints from a real run, in the order the pipeline meets them."""

    @staticmethod
    def _ranked(monkeypatch: pytest.MonkeyPatch, jobs: list[dict[str, Any]]) -> dict[str, Any]:
        """Run the flow over a fixed ranked list, stubbing everything after it."""
        seen: dict[str, Any] = {}

        async def fake_stream(agent, **kwargs):
            yield ("run", {"run_id": 1, "session_id": "investigator", "kind": "investigator"})
            yield ("state", {RANKED_STATE_KEY: {"jobs": jobs, "strategy_notes": ""}})
            yield ("done", {"run_id": 1, "text": "", "invocation_id": "inv-1"})

        async def fake_verify(candidates):
            seen["verified"] = [job.get("url") for job in candidates]
            seen.setdefault("waves", []).append(len(candidates))
            # Statuses come from the fixture's own `url_status`, so a test can
            # say "this link lands on a careers page" without any HTTP.
            return [
                {**job, "url_status": job.get("url_status", verification.OK)}
                for job in candidates
            ], {}

        async def fake_nothing(*_args, **_kwargs):
            return {}

        monkeypatch.setattr(flows, "stream", fake_stream)
        monkeypatch.setattr(flows.verification, "verify_jobs", fake_verify)
        monkeypatch.setattr(flows, "build_digest", fake_nothing)
        monkeypatch.setattr(flows, "audit_artifact", fake_nothing)
        monkeypatch.setattr(flows, "save_job_postings", lambda jobs: {"saved": len(jobs)})
        return seen

    async def test_a_posting_with_no_link_never_reaches_the_user(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._ranked(
            monkeypatch,
            [
                {"title": "Real", "company": "A", "url": "https://a.test/jobs/ml-intern"},
                {"title": "Linkless", "company": "B", "url": ""},
                {"title": "Careers page", "company": "C", "url": "https://c.test/careers"},
            ],
        )
        result = await flows.run_investigator(target_results=5)

        assert [job["title"] for job in result["jobs"]] == ["Real"]
        # And it cost nothing to know: neither bad link was ever fetched.
        assert seen["verified"] == ["https://a.test/jobs/ml-intern"]
        assert result["link_drops"] == {"missing": 1, "index": 1}

    async def test_a_link_that_lands_on_a_careers_page_loses_its_slot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Top-ranked, but the link resolves to the company's careers index —
        # which only a fetch can reveal. With five working links behind it, the
        # buffer has a real posting to promote into the slot it gives up.
        self._ranked(
            monkeypatch,
            [
                {
                    "title": "Best fit",
                    "company": "A",
                    "url": "https://a.test/jobs/1",
                    "url_status": verification.INDEX,
                },
                *(
                    {"title": f"Runner-up {n}", "company": "B", "url": f"https://b.test/jobs/{n}"}
                    for n in range(5)
                ),
            ],
        )
        result = await flows.run_investigator(target_results=5)

        titles = [job["title"] for job in result["jobs"]]
        assert titles == [f"Runner-up {n}" for n in range(5)]
        # None of these postings carries a date, so the recency sort has nothing
        # to separate them by and the Matcher's order stands.
        assert result["url_check"] == {verification.OK: 5}

    async def test_a_broken_link_is_never_shown_even_as_the_only_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Not demoted — gone. A card the candidate opens onto a 404 wastes the
        # time this app exists to save, so an empty list beats a wrong one.
        self._ranked(
            monkeypatch,
            [
                {
                    "title": "Only one",
                    "company": "A",
                    "url": "https://a.test/jobs/1",
                    "url_status": verification.DEAD,
                }
            ],
        )
        result = await flows.run_investigator(target_results=5)
        assert result["jobs"] == []
        assert result["link_drops"] == {verification.DEAD: 1}

    async def test_a_broken_link_pulls_the_next_candidate_into_its_slot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # What the matcher's spares are for: five asked for, the first three
        # broken, so three more are checked and the count still comes out right.
        seen = self._ranked(
            monkeypatch,
            [
                {
                    "title": f"Broken {n}",
                    "company": "A",
                    "url": f"https://a.test/jobs/x{n}",
                    "url_status": verification.DEAD,
                }
                for n in range(3)
            ]
            + [
                {"title": f"Good {n}", "company": "B", "url": f"https://b.test/jobs/{n}"}
                for n in range(5)
            ],
        )
        result = await flows.run_investigator(target_results=5)

        titles = [job["title"] for job in result["jobs"]]
        assert titles == [f"Good {n}" for n in range(5)]
        assert result["link_drops"] == {verification.DEAD: 3}
        # Two waves: five, then the three replacements. Not all eight at once.
        assert seen["waves"] == [5, 3]

    async def test_a_run_of_nothing_but_broken_links_stops_checking(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The ceiling: without it, a ranking of forty dead links would open
        # forty browsers to learn what the first ten already said.
        seen = self._ranked(
            monkeypatch,
            [
                {
                    "title": f"Broken {n}",
                    "company": "A",
                    "url": f"https://a.test/jobs/{n}",
                    "url_status": verification.DEAD,
                }
                for n in range(40)
            ],
        )
        result = await flows.run_investigator(target_results=5)

        assert result["jobs"] == []
        assert sum(seen["waves"]) == 5 * flows.VERIFY_BUDGET


class TestRecencyOutranksTheMatcher:
    """The Matcher's order is a request; freshest-first is the guarantee.

    Same shape as the result-count tests above and for the same reason: the
    prompt asks the model to weight recency, and this is what makes it true of
    the run whatever the model returned.
    """

    @staticmethod
    def _ranked(monkeypatch: pytest.MonkeyPatch, jobs: list[dict[str, Any]]) -> None:
        async def fake_stream(agent, **kwargs):
            yield ("run", {"run_id": 1, "session_id": "investigator", "kind": "investigator"})
            yield ("state", {RANKED_STATE_KEY: {"jobs": jobs, "strategy_notes": ""}})
            yield ("done", {"run_id": 1, "text": "", "invocation_id": "inv-1"})

        async def fake_verify(candidates):
            return [{**job, "url_status": verification.OK} for job in candidates], {}

        async def fake_nothing(*_args, **_kwargs):
            return {}

        monkeypatch.setattr(flows, "stream", fake_stream)
        monkeypatch.setattr(flows.verification, "verify_jobs", fake_verify)
        monkeypatch.setattr(flows, "build_digest", fake_nothing)
        monkeypatch.setattr(flows, "audit_artifact", fake_nothing)
        monkeypatch.setattr(flows, "save_job_postings", lambda jobs: {"saved": len(jobs)})

    def _job(self, title: str, fit: float, posted: str) -> dict[str, Any]:
        return {
            "title": title,
            "company": "A",
            "url": f"https://a.test/jobs/{title.lower()}",
            "fit_score": fit,
            "posted_at": posted,
        }

    async def test_a_stale_posting_is_demoted_however_it_was_ranked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        today = recency.today()
        self._ranked(
            monkeypatch,
            [
                self._job("Stale", 9.5, (today - timedelta(days=210)).isoformat()),
                self._job("Fresh", 8.0, (today - timedelta(days=2)).isoformat()),
            ],
        )
        result = await flows.run_investigator(target_results=5)

        assert [job["title"] for job in result["jobs"]] == ["Fresh", "Stale"]
        # Demoted, not deleted: with nothing else to show, an old posting that
        # is still open is a real job.
        assert len(result["jobs"]) == 2

    async def test_freshness_decides_which_postings_get_the_slots(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The cut happens after the sort, so the target is spent on fresh ones.

        Ten strong old postings and five weaker fresh ones: on the Matcher's
        own order the candidate would have seen nothing but last winter.
        """
        today = recency.today()
        self._ranked(
            monkeypatch,
            [
                self._job(f"Old{n}", 9.0, (today - timedelta(days=200 + n)).isoformat())
                for n in range(10)
            ]
            + [
                self._job(f"New{n}", 7.0, (today - timedelta(days=n)).isoformat())
                for n in range(5)
            ],
        )
        result = await flows.run_investigator(target_results=5)

        assert [job["title"] for job in result["jobs"]] == [f"New{n}" for n in range(5)]

    async def test_the_run_reports_how_fresh_its_results_are(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        today = recency.today()
        self._ranked(
            monkeypatch,
            [
                self._job("Today", 8.0, today.isoformat()),
                self._job("Undated", 8.0, ""),
            ],
        )
        result = await flows.run_investigator(target_results=5)

        assert result["freshness"] == {
            "week": 1,
            "month": 0,
            "quarter": 0,
            "older": 0,
            "undated": 1,
        }


class TestGroundingRedirects:
    """A posting's URL has to be the posting's, not Google's.

    Run 8 ranked a real Saegus posting whose `url` was a
    `vertexaisearch.cloud.google.com/grounding-api-redirect/<opaque>` link —
    the form Google Search grounding hands the model, which it cites faithfully.
    Those expire within weeks, name Google as the source, and hide the site they
    open from the shape gate. `services/flows.py` resolves them before anything
    else looks at a URL; these tests are what says "before".
    """

    REDIRECT = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQHm9"
    REAL = "https://www.welcometothejungle.com/fr/companies/saegus/jobs/consultant-data_paris"

    @staticmethod
    def _ranked(
        monkeypatch: pytest.MonkeyPatch,
        jobs: list[dict[str, Any]],
        resolved: dict[str, str],
    ) -> dict[str, Any]:
        """Run the flow over a fixed ranked list, with the redirector stubbed.

        Only the HTTP hop is faked: `grounding.resolve_jobs` itself runs, so
        this exercises the real wiring between the two.
        """
        seen: dict[str, Any] = {}

        async def fake_stream(agent, **kwargs):
            yield ("run", {"run_id": 1, "session_id": "investigator", "kind": "investigator"})
            yield ("state", {RANKED_STATE_KEY: {"jobs": jobs, "strategy_notes": ""}})
            yield ("done", {"run_id": 1, "text": "", "invocation_id": "inv-1"})

        async def fake_resolve_urls(urls):
            seen["asked"] = [url for url in urls if grounding.is_grounding_redirect(url)]
            return {url: resolved[url] for url in seen["asked"] if url in resolved}

        async def fake_verify(candidates):
            seen["verified"] = [job.get("url") for job in candidates]
            return [{**job, "url_status": verification.OK} for job in candidates], {}

        async def fake_nothing(*_args, **_kwargs):
            return {}

        def fake_save(saved: list[dict[str, Any]]) -> dict[str, Any]:
            seen["saved"] = saved
            return {"saved": len(saved)}

        monkeypatch.setattr(flows, "stream", fake_stream)
        monkeypatch.setattr(flows.grounding, "resolve_urls", fake_resolve_urls)
        monkeypatch.setattr(flows.verification, "verify_jobs", fake_verify)
        monkeypatch.setattr(flows, "build_digest", fake_nothing)
        monkeypatch.setattr(flows, "audit_artifact", fake_nothing)
        monkeypatch.setattr(flows, "save_job_postings", fake_save)
        return seen

    async def test_the_posting_is_saved_under_the_employers_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._ranked(
            monkeypatch,
            [{"title": "Consultant Data", "company": "Saegus", "url": self.REDIRECT}],
            {self.REDIRECT: self.REAL},
        )
        result = await flows.run_investigator(target_results=5)

        # Resolved before the shape gate, before the fetch, and before the row
        # is written — every stage downstream sees one URL, the real one.
        assert seen["verified"] == [self.REAL]
        assert [job["url"] for job in seen["saved"]] == [self.REAL]
        assert result["jobs"][0]["url"] == self.REAL
        assert result["jobs"][0]["redirect_url"] == self.REDIRECT
        assert result["link_drops"] == {}

    async def test_a_careers_page_behind_a_redirect_is_still_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The shape gate is the cheap check, and a redirect blinds it: this
        # posting looks fine until the redirect is followed to `/careers`.
        seen = self._ranked(
            monkeypatch,
            [
                {"title": "Not a posting", "company": "A", "url": self.REDIRECT},
                {"title": "Real", "company": "B", "url": "https://b.test/jobs/ml-intern"},
            ],
            {self.REDIRECT: "https://a.test/en/careers"},
        )
        result = await flows.run_investigator(target_results=5)

        assert [job["title"] for job in result["jobs"]] == ["Real"]
        assert result["link_drops"] == {job_links.INDEX: 1}
        assert seen["verified"] == ["https://b.test/jobs/ml-intern"]

    async def test_a_redirect_that_cannot_be_followed_never_becomes_a_card(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Nothing came back from the redirector, so the link still names Google.
        # Saving it would put a card on the deck that dies in a few weeks, so it
        # loses its slot to the posting behind it — and costs no HTTP request.
        seen = self._ranked(
            monkeypatch,
            [
                {"title": "Unresolvable", "company": "A", "url": self.REDIRECT},
                {"title": "Real", "company": "B", "url": "https://b.test/jobs/ml-intern"},
            ],
            {},
        )
        result = await flows.run_investigator(target_results=5)

        assert [job["title"] for job in result["jobs"]] == ["Real"]
        assert result["link_drops"] == {job_links.REDIRECT: 1}
        assert seen["verified"] == ["https://b.test/jobs/ml-intern"]

    async def test_a_run_with_no_redirects_asks_the_redirector_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._ranked(
            monkeypatch,
            [{"title": "Real", "company": "B", "url": "https://b.test/jobs/ml-intern"}],
            {},
        )
        await flows.run_investigator(target_results=5)
        assert seen["asked"] == []


async def test_out_of_range_target_is_clamped(fake_run: dict[str, Any]) -> None:
    result = await flows.run_investigator(target_results=10_000)
    assert result["target_results"] == MAX_RESULTS
    assert len(result["jobs"]) == MAX_RESULTS


async def test_target_reaches_the_run_record(fake_run: dict[str, Any]) -> None:
    await flows.run_investigator(target_results=20)
    assert fake_run["payload"]["target_results"] == 20
    assert "20" in fake_run["label"]
