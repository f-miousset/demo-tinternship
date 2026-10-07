"""The last resort: open the link in a real browser and read what it says.

An HTTP client cannot verify a link on a board that answers every request with
a JavaScript challenge. Welcome to the Jungle — the app's first-priority board —
does exactly that: AWS WAF returns a byte-identical 202 for a live posting and
for a URL invented on the spot, so ten of thirteen saved postings once read
"link verified" while four of them were 404s. `verification.py` stopped calling
those verified, which was honest but not useful: the candidate still had to open
every one by hand to find out. That is the work this app exists to do.

Chromium executes the challenge like any browser and then renders the page. The
rendered **title is the verdict** — the HTTP status is not, and measurably so:
Welcome to the Jungle serves a live posting under a 202 and a dead one under a
200, and only the title tells them apart ("Erreur 404" against the job's own
name). So this module reads what the page calls itself and hands it to the same
`job_links.headline_says_gone` rule the HTTP path uses.

It runs **only on links the HTTP check could not settle**, which keeps a browser
out of the common case: a run of fifteen postings typically starts one Chromium
for the handful behind bot protection and leaves the rest alone.

`read_page` is the second caller, from the pasted-link path: same navigation,
but it keeps the rendered page as well as the verdict, because there the point
is to *read* a posting an HTTP client is never shown.

Every failure here — Playwright missing, Chromium not installed, a launch that
dies, a page that times out — returns *no verdict* for that URL rather than a
bad one. The link stays `blocked`, which is where it already was.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from typing import Any

from ..config import get_settings
from . import job_links

logger = logging.getLogger(__name__)

# One browser, a few tabs. Chromium is the memory-hungry part; pages are cheap,
# but a WAF challenge is CPU-bound JavaScript and the API box is shared.
_PAGES = 3
# What Chromium reports as the outcome, in the vocabulary of `verification.py`.
# Kept as plain strings so this module does not import from its own caller.
OK = "ok"
DEAD = "dead"
INDEX = "index"
BLOCKED = "blocked"

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


def enabled() -> bool:
    """Whether to try at all — the setting, and Playwright being importable."""
    if not get_settings().browser_verify:
        return False
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        logger.info("Browser verification is on but Playwright is not installed; skipping")
        return False
    return True


@dataclass(frozen=True)
class Rendered:
    """What a real browser made of a page: the verdict, and the page itself.

    `verdict` is `(status, note)` in `verification.py`'s vocabulary, or `None`
    when Chromium could not settle the question — the link then stays wherever
    the HTTP check left it. `text` is the rendered page, which only the
    pasted-link path asks for: `recheck` wants a verdict and throws it away.
    """

    verdict: tuple[str, str] | None = None
    text: str = ""
    html: str = ""


async def _read(page: Any, url: str, *, capture: bool = False) -> Rendered | None:
    """Navigate and judge, or `None` when the page never became readable."""
    settings = get_settings()
    try:
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=int(settings.browser_verify_timeout_seconds * 1000),
        )
        # A challenge page swaps itself for the real one a beat after load, and
        # a single-page app paints its 404 in the same window. Neither has
        # settled at `domcontentloaded`.
        await page.wait_for_timeout(int(settings.browser_verify_settle_seconds * 1000))
        title = await page.title()
        heading = ""
        node = await page.query_selector("h1")
        if node is not None:
            heading = (await node.inner_text())[:200]
        final_url = page.url
        # Only for a caller that wants to read the posting. A verification run
        # opens a handful of pages at once and has no use for their text.
        text = await page.inner_text("body") if capture else ""
        markup = await page.content() if capture else ""
    except Exception:
        logger.debug("Browser check failed for %s", url, exc_info=True)
        return None

    rendered = f"{title} {heading}".strip()
    if not rendered and not final_url:
        return None

    read = Rendered(text=text, html=markup)

    gone = job_links.headline_says_gone(rendered)
    if gone is not None:
        return replace(read, verdict=(DEAD, gone.reason))

    landed = job_links.landing(url, final_url)
    if landed.kind == job_links.GONE:
        return replace(read, verdict=(DEAD, landed.reason))
    if landed.kind == job_links.INDEX:
        return replace(read, verdict=(INDEX, landed.reason))
    if landed.kind == job_links.LOGIN:
        # A sign-in wall in a real browser is a sign-in wall for the candidate
        # too, but it is still not evidence the posting is missing.
        return replace(read, verdict=(BLOCKED, landed.reason))

    if not rendered:
        # Rendered nothing and went nowhere: no verdict rather than a wrong one.
        return None
    return replace(read, verdict=(OK, f"opened in a browser: {rendered[:70]!r}"))


async def recheck(urls: list[str]) -> dict[str, tuple[str, str]]:
    """Verdicts for the URLs a browser could settle. Absent keys are unchanged."""
    settings = get_settings()
    targets = list(dict.fromkeys(u for u in urls if u))[: settings.browser_verify_max]
    if not targets or not enabled():
        return {}

    from playwright.async_api import async_playwright

    verdicts: dict[str, tuple[str, str]] = {}
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(args=["--disable-dev-shm-usage"])
            try:
                context = await browser.new_context(
                    user_agent=_UA, locale="fr-FR", viewport={"width": 1280, "height": 900}
                )
                semaphore = asyncio.Semaphore(_PAGES)

                async def one(url: str) -> None:
                    async with semaphore:
                        page = await context.new_page()
                        try:
                            read = await _read(page, url)
                        finally:
                            await page.close()
                        if read is not None and read.verdict is not None:
                            verdicts[url] = read.verdict

                await asyncio.gather(*(one(url) for url in targets), return_exceptions=True)
            finally:
                await browser.close()
    except Exception:
        # A missing Chromium, a sandbox refusal, an OOM. The HTTP verdicts stand.
        logger.warning("Browser verification unavailable; links stay unchecked", exc_info=True)
        return verdicts

    logger.info("Browser settled %s of %s unchecked link(s)", len(verdicts), len(targets))
    return verdicts


async def read_page(url: str) -> Rendered | None:
    """Open one link in a real browser and hand back what it rendered.

    The pasted-link path's fallback. An HTTP fetch of a Welcome to the Jungle
    posting returns an AWS WAF challenge, not the job — the same blind spot
    that made this module necessary for verification — so a candidate pasting
    the app's first-priority board would otherwise be told their link could not
    be read. Chromium runs the challenge and renders the posting.

    `None` when Playwright is missing, disabled, or the page never rendered:
    the caller reports that it could not read the page rather than inventing
    one. Costs a browser launch, so it is the fallback and not the first try.
    """
    if not url or not enabled():
        return None

    from playwright.async_api import async_playwright

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(args=["--disable-dev-shm-usage"])
            try:
                context = await browser.new_context(
                    user_agent=_UA, locale="fr-FR", viewport={"width": 1280, "height": 900}
                )
                page = await context.new_page()
                try:
                    return await _read(page, url, capture=True)
                finally:
                    await page.close()
            finally:
                await browser.close()
    except Exception:
        logger.warning("Browser could not open %s", url, exc_info=True)
        return None
