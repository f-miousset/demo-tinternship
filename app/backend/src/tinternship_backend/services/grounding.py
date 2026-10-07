"""Resolving Gemini grounding redirects to the pages they actually point at.

Google Search grounding returns citations as
`vertexaisearch.cloud.google.com/grounding-api-redirect/<opaque>` links. The
model faithfully cites those, but they are useless to a human: you cannot tell
whether the playbook is citing a government page or a content-farm listicle
without clicking through. Since the whole point of requiring sources is that
they can be checked, we follow the redirects once and store the real URLs.

For a *job posting* the same link is not merely unreadable, it is wrong. The
redirector expires after a few weeks, so a saved card would eventually open a
dead Google URL. `services/job_links.py` judges a link by the shape of its own
URL, and a redirect hides the site it points at, so a careers index behind one
sails through the check that is supposed to cost nothing. `job_links.site_name`
reports `vertexaisearch.cloud.google.com` as the posting's source. And a
posting that arrives without a company name is identified by its URL host in
`tools/persistence.py`, which every redirect shares — so two unrelated postings
with similar titles collapse onto one row. `resolve_jobs` therefore runs on a
ranked list before any of those look at it.

Failures are non-fatal here — an unresolvable link keeps its redirect form
rather than disappearing, because a link you can still click beats no link at
all. What happens to it next differs by caller: a citation keeps it, and
`job_links.classify` refuses a posting still wearing one, because a card
promises to open the posting weeks from now and that one will not.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

REDIRECT_HOST = "vertexaisearch.cloud.google.com"
_CONCURRENCY = 6
_TIMEOUT = 12.0


def is_grounding_redirect(url: str) -> bool:
    return REDIRECT_HOST in (url or "")


async def _resolve_one(client: httpx.AsyncClient, url: str, semaphore: asyncio.Semaphore) -> str:
    async with semaphore:
        try:
            response = await client.get(url)
            final = str(response.url)
            # If it still points at the redirector, we learned nothing.
            return url if is_grounding_redirect(final) else final
        except Exception:
            logger.debug("Could not resolve grounding redirect %s", url, exc_info=True)
            return url


async def resolve_urls(urls: list[str]) -> dict[str, str]:
    """Map each grounding-redirect URL to its final destination."""
    targets = [url for url in dict.fromkeys(urls) if is_grounding_redirect(url)]
    if not targets:
        return {}

    semaphore = asyncio.Semaphore(_CONCURRENCY)
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": "tinternship/0.1"}
    ) as client:
        resolved = await asyncio.gather(
            *(_resolve_one(client, url, semaphore) for url in targets)
        )
    return {original: final for original, final in zip(targets, resolved, strict=True)}


async def resolve_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rewrite a playbook's `sources` list in place-ish, returning a new list.

    Keeps the original redirect on the entry as `redirect_url` so the trace and
    the resolved citation can still be reconciled.
    """
    if not sources:
        return sources

    mapping = await resolve_urls([str(source.get("url", "")) for source in sources])
    if not mapping:
        return sources

    updated: list[dict[str, Any]] = []
    for source in sources:
        url = str(source.get("url", ""))
        final = mapping.get(url)
        if final and final != url:
            updated.append({**source, "url": final, "redirect_url": url})
        else:
            updated.append(source)
    return updated


# The fields on a ranked posting that hold a link somebody will click. Both,
# because `apply_url` is what the Apply button opens, and a model that cited a
# redirect for one has no reason to have copied a real URL into the other.
JOB_URL_FIELDS = ("url", "apply_url")


async def resolve_url(url: str) -> str:
    """One URL, followed to whatever it actually points at.

    Returned unchanged when it is not a grounding redirect — including when it
    is empty or nonsense — so a caller can hand it any link without asking
    first, and pays nothing for the ordinary case.
    """
    return (await resolve_urls([url])).get(url, url)


async def resolve_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rewrite a ranked list's posting links, returning a new list.

    Runs before `job_links.partition` in `services/flows.py`, which is the
    earliest point the whole list exists and the last point before its URLs are
    judged, saved and turned into identities.
    """
    if not jobs:
        return jobs

    mapping = await resolve_urls(
        [str(job.get(field, "")) for job in jobs for field in JOB_URL_FIELDS]
    )
    if not mapping:
        return jobs

    updated: list[dict[str, Any]] = []
    for job in jobs:
        changed: dict[str, str] = {}
        for field in JOB_URL_FIELDS:
            url = str(job.get(field, ""))
            final = mapping.get(url, url)
            if final != url:
                changed[field] = final
        if not changed:
            updated.append(job)
            continue
        if "url" in changed:
            # Keep the redirect the model actually returned, as `resolve_sources`
            # does, so the posting can still be reconciled with its trace.
            changed["redirect_url"] = str(job.get("url", ""))
        updated.append({**job, **changed})
    return updated
