"""The last-resort check: what a real browser sees.

Welcome to the Jungle answers an HTTP client with an identical challenge page
for a live posting and for invented nonsense, so ten of thirteen saved postings
once read "link verified" while four were 404s. Chromium runs the challenge and
renders the page; these tests pin what is done with what it renders.

No test here starts a browser. `_read` is given a fake page, which is the whole
surface this module uses: `goto`, `wait_for_timeout`, `title`, `query_selector`
and `url`.
"""

from __future__ import annotations

import pytest

from tinternship_backend.config import get_settings
from tinternship_backend.services import browser_check


class FakePage:
    """The calls `_read` makes, and nothing else."""

    def __init__(
        self,
        *,
        title: str = "",
        heading: str = "",
        url: str = "",
        raises: bool = False,
        body: str = "",
    ):
        self._title, self._heading, self.url, self._raises = title, heading, url, raises
        self._body = body

    async def inner_text(self, _selector: str) -> str:
        return self._body

    async def content(self) -> str:
        return f"<html><body>{self._body}</body></html>"

    async def goto(self, url: str, **_kwargs):
        if self._raises:
            raise TimeoutError("navigation timed out")
        self.url = self.url or url

    async def wait_for_timeout(self, _ms: int) -> None:
        return None

    async def title(self) -> str:
        return self._title

    async def query_selector(self, _selector: str):
        if not self._heading:
            return None

        class Node:
            async def inner_text(inner_self) -> str:
                return self._heading

        return Node()


WTTJ = "https://www.welcometothejungle.com/fr/companies/moba/jobs/data-science-intern_paris"


class TestTheTitleIsTheVerdict:
    """Not the status code — Welcome to the Jungle serves a live posting under a
    202 and a dead one under a 200, and only the rendered title separates them."""

    async def test_a_rendered_404_is_dead(self) -> None:
        page = FakePage(title="Erreur 404", heading="Page introuvable", url=WTTJ)
        status, note = (await browser_check._read(page, WTTJ)).verdict
        assert status == browser_check.DEAD
        assert "Erreur 404" in note

    async def test_a_rendered_posting_is_verified(self) -> None:
        page = FakePage(title="Data Science Intern - Moba - Stage à Paris", url=WTTJ)
        status, note = (await browser_check._read(page, WTTJ)).verdict
        assert status == browser_check.OK
        assert "Moba" in note

    async def test_a_browser_that_lands_on_the_careers_page_says_so(self) -> None:
        page = FakePage(title="Careers at 3DS", url="https://www.3ds.com/careers")
        read = await browser_check._read(page, "https://careers.3ds.com/jobs/some-slug")
        assert read.verdict[0] == browser_check.INDEX

    async def test_a_sign_in_wall_is_still_not_evidence(self) -> None:
        # The candidate hits the same wall, but the posting may well be there.
        page = FakePage(title="Sign in", url="https://www.linkedin.com/authwall?x=1")
        read = await browser_check._read(page, "https://www.linkedin.com/jobs/view/123")
        assert read.verdict[0] == browser_check.BLOCKED

    async def test_the_page_is_only_read_when_someone_asked_for_it(self) -> None:
        # A verification run opens a handful of pages and wants verdicts. Only
        # the pasted-link path asks for the text, and it pays for it explicitly.
        page = FakePage(title="ML Intern - Acme", url=WTTJ, body="The posting itself.")
        assert (await browser_check._read(page, WTTJ)).text == ""
        read = await browser_check._read(page, WTTJ, capture=True)
        assert read.text == "The posting itself."
        assert "The posting itself." in read.html

    async def test_a_page_that_never_loaded_gives_no_verdict(self) -> None:
        # Silence, not a guess: the link keeps whatever the HTTP check said.
        assert await browser_check._read(FakePage(raises=True), WTTJ) is None

    async def test_a_blank_page_gives_no_verdict(self) -> None:
        assert await browser_check._read(FakePage(url=WTTJ), WTTJ) is None


class TestItStaysOutOfTheWay:
    async def test_nothing_runs_when_the_setting_is_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(get_settings(), "browser_verify", False)
        assert not browser_check.enabled()
        # Would raise on any attempt to import Playwright or launch a browser.
        assert await browser_check.recheck([WTTJ]) == {}

    async def test_no_unsettled_links_means_no_browser(self) -> None:
        assert await browser_check.recheck([]) == {}


class TestTheFallbackReachesTheChecker:
    """`check_urls` hands the browser exactly the links it could not settle."""

    async def test_only_unchecked_links_are_reopened(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tinternship_backend.services import verification as v

        good, walled = "https://acme.test/jobs/1", "https://waf.test/jobs/2"

        async def fake_fetch(_client, url, _limit):
            import httpx

            request = httpx.Request("GET", url)
            if url == good:
                return httpx.Response(200, request=request), "<title>ML Intern</title>"
            return httpx.Response(202, request=request), "window.awsWafCookieDomainList = []"

        asked: list[list[str]] = []

        async def fake_recheck(urls):
            asked.append(urls)
            return {walled: (v.DEAD, "opened in a browser: 'Erreur 404'")}

        monkeypatch.setattr(v, "_fetch", fake_fetch)
        monkeypatch.setattr(get_settings(), "browser_verify", True)
        monkeypatch.setattr(browser_check, "enabled", lambda: True)
        monkeypatch.setattr(browser_check, "recheck", fake_recheck)

        checks = await v.check_urls([good, walled])

        # The verified link is not re-opened — a browser is the expensive path.
        assert asked == [[walled]]
        assert checks[good].status == v.OK
        assert checks[walled].status == v.DEAD
        assert "Erreur 404" in checks[walled].note
