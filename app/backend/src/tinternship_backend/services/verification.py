"""Checking that a discovered posting actually exists.

A grounded model will happily produce a *plausible* URL — during development the
Investigator returned `jobs.lever.co/mistral` and a Station F deep link that
were both 404. Plausible-but-fabricated postings are the worst possible failure
for this app: the candidate wastes time, and the ranking is built on fiction.

So every posting URL is fetched before it is persisted. This is deterministic —
it does not care *why* the model produced a bad link.

Classification matters more than a pass/fail bit:

* `ok`      — 2xx, and the redirects settled on the posting itself.
* `blocked` — 401/403/429, or a redirect to a sign-in page. Bot protection, not
              a dead link. Welcome to the Jungle and LinkedIn both do this to
              unauthenticated clients, so treating it as fabrication would throw
              away good postings.
* `index`   — 2xx, but the link lands on the company's careers page, a board
              search page or somewhere else that is not this posting.
* `dead`    — 404/410, or a redirect to an error page. The posting is not there.
* `error`   — DNS failure, timeout, TLS problem. Unknown; treated as unverified
              rather than condemned.

Anything still `blocked` after all that was never actually looked at, so
`browser_check.py` opens it in Chromium and reads the page the candidate would
see. That is the only thing that works on a board answering every request with
a JavaScript challenge.

The fetch answers a second question for free. Most job pages carry a schema.org
`datePosted`, so the bytes pulled to prove a posting exists also say when it was
published — the employer's own answer, not one inferred from a search snippet.
`services/recency.py` reads it out, and the ranking is reordered on it.

The status code alone was not enough. Three saved postings returned 200 and
were badged "link verified" while sending the candidate to a search box: a
`careers.3ds.com` deep link that settled on `www.3ds.com/careers`, a
`jobs.sap.com` link missing its requisition id that settled on `/errorpage/`,
and a Lever board landing page. So where a link *ends up* is judged too, by
`services/job_links.py`.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, replace
from urllib.parse import urlparse

import httpx

from . import job_links, recency

logger = logging.getLogger(__name__)

_CONCURRENCY = 8
_TIMEOUT = 15.0
# Public because `services/outreach.py` fetches LinkedIn with the same identity.
# One definition, so a UA that stops working is fixed in one place rather than in
# whichever module noticed first.
BROWSER_HEADERS = {
    # Without a browser-ish UA a lot of career sites 403 everything, which would
    # make the "blocked" bucket uselessly large.
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

# How much of the page to read. A challenge page announces itself in `<head>`
# and a "not found" page in its title, so the first slice is all that is needed
# — and a posting link that turns out to be a 30 MB PDF costs 64 KB, not 30 MB.
_BODY_LIMIT = 64 * 1024
# What `inspect` reads instead. Checking a link only needs the head; *reading*
# the posting needs the body it is in, and a board's job page routinely spends
# its first 64 KB on a script bundle before the posting starts.
_READ_LIMIT = 512 * 1024
_READABLE = ("text/", "application/json", "application/xhtml", "application/xml")

# A 2xx whose body is a bot-protection interstitial. The tell is that the WAF
# answers *every* URL on the host with the same page — Welcome to the Jungle
# returns byte-identical 202s for a live posting and for invented nonsense — so
# the fetch proves nothing at all and must not be reported as proof.
_CHALLENGE_MARKERS = (
    "awswafcookiedomainlist",  # AWS WAF — Welcome to the Jungle
    "gokuprops",  # the AWS WAF challenge payload
    "_incapsula_resource",  # Imperva — thalesgroup.com
    "distil_referrer",
    "challenge-platform",  # Cloudflare
    "cf_chl_opt",
    "just a moment...",
    "checking your browser",
    "enable javascript and cookies to continue",
    "captcha-delivery.com",  # DataDome
    "px-captcha",
    "please verify you are a human",
)


OK = "ok"
BLOCKED = "blocked"
INDEX = "index"
DEAD = "dead"
ERROR = "error"
UNCHECKED = "unchecked"

# What a status does to the posting that carries it. `ok` and `blocked` mean
# "open it and see"; the rest mean the link did not reach the posting, which is
# what `flows.py` demotes on.
UNUSABLE = frozenset({INDEX, DEAD})


@dataclass(frozen=True)
class UrlCheck:
    url: str
    status: str
    http_status: int = 0
    final_url: str = ""
    note: str = ""
    # The `datePosted` the page publishes about itself, ISO, when it has one.
    # Free: the bytes were fetched to answer "is it there?" anyway, and the
    # employer's own date beats a date inferred from a search snippet.
    posted_at: str = ""

    @property
    def is_fabricated(self) -> bool:
        return self.status == DEAD


def classify(http_status: int) -> str:
    if 200 <= http_status < 300:
        return OK
    if http_status in {401, 403, 429}:
        return BLOCKED
    if http_status in {404, 410}:
        return DEAD
    # 5xx is the site's problem, not evidence either way.
    return ERROR


# Welcome to the Jungle sits behind AWS WAF, which answers this checker with a
# byte-identical 202 challenge for a live posting and for invented nonsense. It
# is the app's first-priority board, so that one blind spot covered ten of
# thirteen saved postings — five of which were 404s in a browser while the card
# read "link verified".
#
# The same platform white-labels employer career sites onto
# `<company>.welcomekit.co`, and those are not challenged. A live slug renders
# the posting there; a slug the site does not know falls back to the company's
# job index — the very page the root serves, so the two are the same page and
# their headlines match.
#
# It may only **confirm**, never condemn. Two things make the negative
# untrustworthy where the positive is solid: the mirror serves some live
# postings under a 404 status (saegus does, with the job rendered in the body),
# so its status code means nothing; and a company's own site need not carry
# every posting its Welcome to the Jungle page does. Seeing the posting proves
# it exists. Not seeing it proves nothing, so that case stays `blocked` — the
# honest answer rather than a guess dressed as one.
_WTTJ_HOST = "welcometothejungle.com"
_WTTJ_JOB = re.compile(r"/companies/([^/]+)/jobs/([^/?#]+)")
# `<company>.welcomekit.co` answers "No career website for …" and nothing else
# when the company never bought one. Anything that short is that.
_NO_MIRROR = 200


async def _second_opinion(client: httpx.AsyncClient, url: str) -> tuple[str, str] | None:
    """Ask the un-WAF'd mirror to confirm a challenged posting exists.

    Returns `(OK, note)` when the mirror shows the posting, and `None` — leave
    it `blocked` — in every other case, including when the mirror looks like it
    has never heard of the slug. See the note above on why the negative is not
    trusted.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").removeprefix("www.")
    if host != _WTTJ_HOST:
        return None
    match = _WTTJ_JOB.search(parsed.path)
    if match is None:
        return None

    company, slug = match.group(1), match.group(2)
    try:
        root = await client.get(f"https://{company}.welcomekit.co/")
        if len(root.content) < _NO_MIRROR:
            return None  # No white-label site — nothing here can answer.
        job = await client.get(f"https://{company}.welcomekit.co/jobs/{slug}")
    except Exception:
        logger.debug("Mirror check failed for %s", url, exc_info=True)
        return None

    # Ignore the status code — the mirror serves live postings under a 404 — and
    # read what the page actually is.
    if job_links.headline(job.text) == job_links.headline(root.text):
        # Fell back to the company's job index: the mirror does not know this
        # slug. Not proof the posting is gone, so leave the verdict alone.
        logger.debug("Mirror for %s fell back to its job index", url)
        return None
    return OK, f"confirmed on {company}'s own career site"


# What a landing verdict does to an otherwise-fine 2xx.
_LANDING_STATUS = {
    job_links.LOGIN: BLOCKED,
    job_links.GONE: DEAD,
    job_links.INDEX: INDEX,
}


def inspect_body(body: str) -> tuple[str, str] | None:
    """What the page says about itself, when that contradicts its status code.

    Returns `(status, note)`, or `None` when the body gives no reason to doubt
    the 2xx. This is the half a status code cannot see: five of the links this
    app had badged "link verified" were 404s in a browser, because the site
    answered the checker with a bot-protection page instead of the posting.
    """
    lowered = body.lower()
    for marker in _CHALLENGE_MARKERS:
        if marker in lowered:
            return (
                BLOCKED,
                "the site answered with a bot-protection page instead of the posting, "
                "so this link could not be checked",
            )

    gone = job_links.headline_says_gone(job_links.headline(body))
    if gone is not None:
        return DEAD, gone.reason
    return None


async def _fetch(client: httpx.AsyncClient, url: str, limit: int) -> tuple[httpx.Response, str]:
    """The response plus the first `limit` bytes of it, decoded."""
    # Some career sites reject HEAD outright, so GET — but stream it, because
    # the body is only wanted for its first few kilobytes.
    async with client.stream("GET", url) as response:
        chunks: list[bytes] = []
        if response.headers.get("content-type", "").startswith(_READABLE):
            size = 0
            async for chunk in response.aiter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size >= limit:
                    break
        return response, b"".join(chunks).decode("utf-8", "replace")


async def _check_one(
    client: httpx.AsyncClient,
    url: str,
    semaphore: asyncio.Semaphore,
    limit: int = _BODY_LIMIT,
) -> tuple[UrlCheck, str]:
    """One link, judged — and the page that judged it.

    The body comes back because `inspect` wants to *read* the posting the same
    fetch just proved exists. `check_urls` throws it away; keeping one function
    means the import path cannot drift into a second, laxer idea of what "this
    link opens the posting" means.
    """
    async with semaphore:
        try:
            response, body = await _fetch(client, url, limit)
        except Exception:
            logger.debug("URL check failed for %s", url, exc_info=True)
            return UrlCheck(url=url, status=ERROR), ""

        status = classify(response.status_code)
        final_url = str(response.url)
        note = ""
        if status == OK:
            # A 2xx only means *something* answered. Judge what — first by what
            # the page says it is, then by where the redirects put us.
            if response.status_code == 202:
                # "Accepted, processing." No site serves a job posting with it;
                # every one seen so far has been a WAF stalling for a challenge.
                status, note = BLOCKED, "the site answered 202 with an interstitial, not the posting"
            else:
                verdict = inspect_body(body)
                if verdict is not None:
                    status, note = verdict
        if status in {OK, ERROR}:
            # Also on ERROR: where a link *goes* does not depend on the
            # destination being healthy. careers.3ds.com redirects to the 3DS
            # careers index, which 500s about half the time — "this link does
            # not open the posting" is true and useful either way, where "the
            # site is down" is neither.
            landed = job_links.landing(url, final_url)
            if landed.kind in _LANDING_STATUS:
                status = _LANDING_STATUS[landed.kind]
                note = landed.reason
        if status == BLOCKED:
            # Bot protection is not an answer. Where a second source can give
            # one, take it rather than shrugging.
            second = await _second_opinion(client, url)
            if second is not None:
                status, note = second
        return (
            UrlCheck(
                url=url,
                status=status,
                http_status=response.status_code,
                final_url=final_url,
                note=note,
                # Read even from a page that failed its other checks: a `blocked`
                # posting still gets shown, and a date is worth having on it.
                posted_at=recency.from_page(body),
            ),
            body,
        )


async def check_urls(urls: list[str]) -> dict[str, UrlCheck]:
    targets = [u for u in dict.fromkeys(urls) if u and u.startswith("http")]
    if not targets:
        return {}

    semaphore = asyncio.Semaphore(_CONCURRENCY)
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, follow_redirects=True, headers=BROWSER_HEADERS, verify=True
    ) as client:
        results = await asyncio.gather(
            *(_check_one(client, url, semaphore) for url in targets)
        )
    checks = {check.url: check for check, _body in results}

    # Whatever is still `blocked` was never actually looked at: a board answered
    # the request with a challenge page instead of the posting. A real browser
    # runs the challenge and reads the page, so ask one — for those links only.
    # Imported here so a missing Playwright cannot break importing this module.
    from . import browser_check

    unsettled = [url for url, check in checks.items() if check.status == BLOCKED]
    if unsettled and browser_check.enabled():
        for url, (status, note) in (await browser_check.recheck(unsettled)).items():
            checks[url] = replace(checks[url], status=status, note=note)
    return checks


async def fetch_posting(url: str) -> tuple[UrlCheck, str]:
    """Check one link and hand back the page behind it.

    The pasted-link path in `services/job_intake.py` needs both, from one
    request: the verdict, so an invented or closed posting is refused before it
    reaches the Jobs page, and the bytes, so the Reader has the posting to read.
    Fetching twice would double the wait and — on a board that rate-limits —
    change the answer between the two.

    Unlike `check_urls` this does *not* fall back to a browser: a `blocked`
    verdict here means the caller has no text either, and it is the caller that
    knows whether opening Chromium is worth it. It also reads far more of the
    page, because the posting is what it is after, not the `<head>`.
    """
    if not url or not url.startswith("http"):
        return UrlCheck(url=url, status=ERROR, note="that is not an http(s) link"), ""

    semaphore = asyncio.Semaphore(1)
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, follow_redirects=True, headers=BROWSER_HEADERS, verify=True
    ) as client:
        return await _check_one(client, url, semaphore, limit=_READ_LIMIT)


async def verify_jobs(jobs: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Annotate each posting with its URL status and report the tally.

    Postings are annotated here, never deleted — deciding what to do with a bad
    link is `flows.py`'s job, and it needs the whole annotated list to decide.
    A `dead` or `index` posting that survives that decision is shown clearly
    marked, because the role may be real even when the link is not. What it
    must not do is masquerade as verified.
    """
    checks = await check_urls([str(job.get("url", "")) for job in jobs])
    tally: dict[str, int] = {}

    annotated: list[dict] = []
    for job in jobs:
        check = checks.get(str(job.get("url", "")))
        status = check.status if check else UNCHECKED
        tally[status] = tally.get(status, 0) + 1
        annotated.append(annotate(job, check))

    return annotated, tally


def annotate(job: dict, check: UrlCheck | None) -> dict:
    """One posting, stamped with what its link turned out to be.

    Split out of `verify_jobs` so the pasted-link path can annotate with the
    check it already has instead of fetching the page a second time — and so
    both paths say the same thing about a dead link, in the same words, in the
    data the candidate reads.
    """
    status = check.status if check else UNCHECKED
    url = str(job.get("url", ""))
    job = {**job, "url_status": status, "url_http_status": check.http_status if check else 0}
    # The page's own `datePosted` wins over whatever the Scout read off a
    # search snippet: one is what the employer published, the other is what
    # a model inferred from "3 days ago" next to a result. Only overwrite
    # when the page actually said something — a silent page must not erase
    # the date the snippet did carry.
    if check and check.posted_at:
        job["posted_at"] = check.posted_at
    # Keep the original URL. Following a redirect can land on a login wall
    # (huggingface.co/jobs → /login?next=…) or a generic careers index, and
    # storing that instead of the posting link is worse than useless. The
    # browser will follow the redirect itself, with the user's own session.
    if check and check.final_url and check.final_url != url:
        job["url_final"] = check.final_url
    if status == DEAD:
        # Say so in the data the user reads, not only in a status field.
        job["confidence"] = "low"
        job["risks"] = [
            (check.note if check and check.note else "This link returned 404")
            + " — the posting may have been invented or has closed. "
            "Search the company's careers page for the role before relying on it.",
            *(job.get("risks") or []),
        ]
    elif status == INDEX:
        job["confidence"] = "low"
        job["risks"] = [
            f"This link does not open the posting — {check.note if check else 'it lands elsewhere'}. "
            "The role may still be open: search for the title from that page.",
            *(job.get("risks") or []),
        ]
    elif status in {ERROR, UNCHECKED} and job.get("confidence") == "high":
        job["confidence"] = "medium"
    return job
