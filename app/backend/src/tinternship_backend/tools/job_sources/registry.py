"""Which structured job sources are live, and the tool that exposes them."""

from __future__ import annotations

import logging
from typing import Any

from ...config import get_settings
from .adzuna import AdzunaSource
from .base import JobSource

logger = logging.getLogger(__name__)


def enabled_sources() -> list[JobSource]:
    sources: list[JobSource] = []
    settings = get_settings()
    adzuna = AdzunaSource(settings.adzuna_country)
    if adzuna.is_enabled():
        sources.append(adzuna)
    return sources


def source_names() -> list[str]:
    return [source.name for source in enabled_sources()]


async def search_job_board(
    query: str, location: str = "", max_results: int = 20, max_days_old: int = 0
) -> dict[str, Any]:
    """Search structured job-board APIs for openings.

    Use this alongside google_search: it returns cleaner, better-structured
    postings (real company names, posting dates, salary bands) than search
    snippets do, but it only covers the boards this app is connected to. Every
    posting it returns carries a real publication date, which a search snippet
    usually does not — so prefer this source when you can.

    Args:
        query: Keywords to search for, e.g. "machine learning internship" or
            "stage data science". Keep it to a few words — this is a keyword
            search, not a natural-language question.
        location: City, region or country to search in, e.g. "Paris". Leave
            empty to search the whole country.
        max_results: How many postings to return, up to 50.
        max_days_old: Only return postings published within this many days.
            Leave at 0 for the app's configured window, which already favours
            recent postings. Narrow it — 7 or 14 — when you want this week's
            openings specifically.

    Returns:
        A dict with `postings` (a list of job postings, newest first),
        `sources_used` and `count`. An empty list means no structured source is
        configured or nothing matched — fall back to google_search in that case.
    """
    sources = enabled_sources()
    if not sources:
        return {
            "postings": [],
            "count": 0,
            "sources_used": [],
            "note": "No structured job-board API is configured; use google_search instead.",
        }

    postings: list[dict[str, Any]] = []
    used: list[str] = []
    for source in sources:
        try:
            results = await source.search(
                query=query,
                location=location,
                max_results=max_results,
                max_days_old=max_days_old or None,
            )
        except Exception:
            logger.exception("Job source %s failed", source.name)
            continue
        if results:
            used.append(source.name)
            postings.extend(results)

    return {"postings": postings, "count": len(postings), "sources_used": used}
