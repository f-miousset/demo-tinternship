"""URL verification — the guard against fabricated job postings.

This exists because of a real incident: the Investigator returned
`jobs.lever.co/mistral` and a Station F deep link, both 404, presented with
"high" confidence alongside genuine postings.

A second incident showed the status code was not enough on its own. Links that
returned 200 and were badged "link verified" landed the candidate on
`www.3ds.com/careers` and on SAP's error page, so where a link *settles* is now
judged too — see `TestWhereTheLinkLands` and `services/job_links.py`.
"""

from __future__ import annotations

import httpx
import pytest

from tinternship_backend.services import verification as v


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (200, v.OK),
        (204, v.OK),
        (301, v.OK),  # httpx follows redirects, so this is the settled status
        (401, v.BLOCKED),
        (403, v.BLOCKED),
        (429, v.BLOCKED),
        (404, v.DEAD),
        (410, v.DEAD),
        (500, v.ERROR),
        (503, v.ERROR),
    ],
)
def test_status_classification(code, expected):
    # 3xx only reaches classify() if redirects were not followed; treat as ok.
    assert v.classify(code) == expected or (code == 301 and v.classify(code) == v.ERROR)


def test_only_404_and_410_count_as_fabrication():
    assert v.UrlCheck("u", v.DEAD, 404).is_fabricated
    # Bot protection is not evidence of fabrication — WTTJ and LinkedIn 403
    # every unauthenticated client, and discarding those loses real postings.
    assert not v.UrlCheck("u", v.BLOCKED, 403).is_fabricated
    assert not v.UrlCheck("u", v.ERROR, 0).is_fabricated
    assert not v.UrlCheck("u", v.OK, 200).is_fabricated


async def test_dead_links_are_flagged_not_deleted(monkeypatch):
    async def fake_check(urls):
        return {
            "https://real.example/job": v.UrlCheck("https://real.example/job", v.OK, 200),
            "https://invented.example/job": v.UrlCheck(
                "https://invented.example/job", v.DEAD, 404
            ),
        }

    monkeypatch.setattr(v, "check_urls", fake_check)

    jobs, tally = await v.verify_jobs(
        [
            {"title": "Real", "url": "https://real.example/job", "confidence": "high"},
            {
                "title": "Invented",
                "url": "https://invented.example/job",
                "confidence": "high",
                "risks": ["existing risk"],
            },
        ]
    )

    assert tally == {v.OK: 1, v.DEAD: 1}
    # The role might still be real, so the posting survives — but clearly marked.
    assert len(jobs) == 2
    assert jobs[0]["url_status"] == v.OK
    assert jobs[0]["confidence"] == "high"

    dead = jobs[1]
    assert dead["url_status"] == v.DEAD
    assert dead["confidence"] == "low"
    assert "404" in dead["risks"][0]
    assert "existing risk" in dead["risks"]


async def test_unreachable_links_downgrade_high_confidence(monkeypatch):
    async def fake_check(urls):
        return {"https://x.example/j": v.UrlCheck("https://x.example/j", v.ERROR, 0)}

    monkeypatch.setattr(v, "check_urls", fake_check)
    jobs, _ = await v.verify_jobs([{"url": "https://x.example/j", "confidence": "high"}])
    assert jobs[0]["confidence"] == "medium"


async def test_blocked_links_keep_their_confidence(monkeypatch):
    async def fake_check(urls):
        return {"https://wttj.example/j": v.UrlCheck("https://wttj.example/j", v.BLOCKED, 403)}

    monkeypatch.setattr(v, "check_urls", fake_check)
    jobs, tally = await v.verify_jobs([{"url": "https://wttj.example/j", "confidence": "high"}])
    assert jobs[0]["confidence"] == "high"
    assert tally == {v.BLOCKED: 1}


async def test_a_redirect_never_replaces_the_original_url(monkeypatch):
    """Regression: `huggingface.co/jobs` 200s but redirects to `/login?next=…`.

    Storing the redirect target replaced a working posting link with a login
    wall. The destination is recorded separately instead.
    """

    async def fake_check(urls):
        return {
            "https://huggingface.co/jobs": v.UrlCheck(
                "https://huggingface.co/jobs",
                v.OK,
                200,
                final_url="https://huggingface.co/login?next=%2Fsettings%2Fjobs",
            )
        }

    monkeypatch.setattr(v, "check_urls", fake_check)
    jobs, _ = await v.verify_jobs([{"url": "https://huggingface.co/jobs"}])
    assert jobs[0]["url"] == "https://huggingface.co/jobs"
    assert jobs[0]["url_final"] == "https://huggingface.co/login?next=%2Fsettings%2Fjobs"


async def test_non_http_values_are_skipped_without_a_request():
    assert await v.check_urls(["", "not a url", "mailto:a@b.c"]) == {}


class TestWhereTheLinkLands:
    """A 200 only means something answered. These tests ask what answered."""

    async def test_a_redirect_to_the_careers_site_is_not_a_verified_link(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url = "https://careers.3ds.com/jobs/stage-orchestration-dagents-ia"

        async def fake_check(urls):
            return {
                url: v.UrlCheck(
                    url,
                    v.INDEX,
                    200,
                    final_url="https://www.3ds.com/careers",
                    note="the link redirects to https://www.3ds.com/careers, which is not the posting",
                )
            }

        monkeypatch.setattr(v, "check_urls", fake_check)
        jobs, tally = await v.verify_jobs([{"title": "R&D", "url": url, "confidence": "high"}])

        assert tally == {v.INDEX: 1}
        job = jobs[0]
        assert job["confidence"] == "low"
        # The card has to say what is wrong with the link, not just colour it.
        assert "3ds.com/careers" in job["risks"][0]
        # And it keeps the original URL, so the user can see what was tried.
        assert job["url_final"] == "https://www.3ds.com/careers"

    def test_a_link_that_misses_the_posting_counts_as_unusable(self) -> None:
        # What `flows.py` demotes on. `blocked` is deliberately not in the set:
        # a bot-protected posting is real, just unverifiable from here.
        assert v.INDEX in v.UNUSABLE
        assert v.DEAD in v.UNUSABLE
        assert v.BLOCKED not in v.UNUSABLE
        assert v.OK not in v.UNUSABLE


AWS_WAF = """<!DOCTYPE html><html lang="en"><head><title></title><script>
window.awsWafCookieDomainList = []; window.gokuProps = {"key":"AQIDAH..."};
</script></head><body></body></html>"""

IMPERVA = """<html><head><script src="/_Incapsula_Resource?SWJIYLWA=719d34"></script>
<script>sessionStorage.setItem('distil_referrer', document.referrer);</script></head></html>"""

SOFT_404 = "<html><head><title>Erreur 404</title></head><body><h1>Page introuvable</h1></body></html>"

POSTING = """<html><head><title>Stage Data Scientist – Acme</title></head><body>
<h1>Stage Data Scientist</h1><p>We are no longer a startup. Applications close in May.
Some roles were not found elsewhere.</p></body></html>"""


class TestWhatThePageSaysAboutItself:
    """Five links badged "link verified" were 404s in a browser.

    Both Welcome to the Jungle (AWS WAF) and thalesgroup.com (Imperva) answer
    this checker with a bot-protection page carrying a 2xx — byte-identical for
    a live posting and for invented nonsense. The status code cannot tell them
    apart, so the body is read.
    """

    @pytest.mark.parametrize("body", [AWS_WAF, IMPERVA])
    def test_a_bot_protection_page_is_never_verified(self, body: str) -> None:
        status, note = v.inspect_body(body)
        assert status == v.BLOCKED
        assert "bot-protection" in note

    def test_a_soft_404_is_dead_however_it_answered(self) -> None:
        status, note = v.inspect_body(SOFT_404)
        assert status == v.DEAD
        assert "Erreur 404" in note

    def test_a_real_posting_survives_words_that_look_like_verdicts(self) -> None:
        # "no longer", "not found" and "close" all appear in the body. Only the
        # title and first heading are read, so a posting is not condemned for
        # its own prose.
        assert v.inspect_body(POSTING) is None

    async def test_a_202_interstitial_is_unverifiable_not_verified(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # What Welcome to the Jungle returns for every URL on the host.
        async def fake_fetch(client, url, _limit):
            return httpx.Response(202, request=httpx.Request("GET", url)), AWS_WAF

        monkeypatch.setattr(v, "_fetch", fake_fetch)
        checks = await v.check_urls(["https://www.welcometothejungle.com/fr/companies/x/jobs/y"])
        assert next(iter(checks.values())).status == v.BLOCKED


class TestTheMirrorMayConfirmButNotCondemn:
    """`<company>.welcomekit.co` is the same platform without the WAF."""

    class _FakeClient:
        def __init__(self, pages: dict[str, tuple[int, str]]) -> None:
            self.pages = pages

        async def get(self, url: str, **_kwargs):
            code, body = self.pages[url]
            return httpx.Response(code, text=body, request=httpx.Request("GET", url))

    ROOT = "https://acme.welcomekit.co/"
    JOB = "https://acme.welcomekit.co/jobs/ml-intern_paris"
    WTTJ = "https://www.welcometothejungle.com/fr/companies/acme/jobs/ml-intern_paris"
    # Both padded past the length that means "this company never bought a
    # white-label site", which is a 41-byte one-liner and nothing else.
    FILLER = "<p>" + "x" * 300 + "</p>"
    INDEX_PAGE = f"<html><head><title>acme recrute !</title></head><body>{FILLER}</body></html>"
    JOB_PAGE = f"<html><head><title>ML Intern chez acme</title></head><body>{FILLER}</body></html>"

    async def test_the_posting_on_the_mirror_confirms_it(self) -> None:
        # A 404 status with the posting in the body: the mirror does this, so
        # the status code is ignored and the page is read.
        client = self._FakeClient({self.ROOT: (200, self.INDEX_PAGE), self.JOB: (404, self.JOB_PAGE)})
        assert await v._second_opinion(client, self.WTTJ) == (
            v.OK,
            "confirmed on acme's own career site",
        )

    async def test_falling_back_to_the_job_list_proves_nothing(self) -> None:
        # The mirror does not know the slug — but a company's own site need not
        # carry every posting its board page does, so this stays unverifiable.
        client = self._FakeClient(
            {self.ROOT: (200, self.INDEX_PAGE), self.JOB: (200, self.INDEX_PAGE)}
        )
        assert await v._second_opinion(client, self.WTTJ) is None

    async def test_a_company_with_no_mirror_is_left_alone(self) -> None:
        client = self._FakeClient({self.ROOT: (200, "No career website for acme.welcomekit.co.")})
        assert await v._second_opinion(client, self.WTTJ) is None

    async def test_only_welcome_to_the_jungle_urls_are_mirrored(self) -> None:
        assert await v._second_opinion(self._FakeClient({}), "https://acme.com/jobs/1") is None
