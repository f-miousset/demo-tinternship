"""Adzuna adapter.

Free tier is roughly 1000 calls/month and covers France plus 15 other
countries, with structured company / salary / date fields that grounded search
cannot reliably give us. Enabled only when ADZUNA_APP_ID and ADZUNA_APP_KEY are
set; otherwise the tool is simply not offered to the agent.

The date field is why this source is worth more than its posting count suggests:
every result carries a real `created` timestamp, where a search snippet usually
carries nothing. `services/recency.py` ranks a dated posting above an undated
one of the same quality, so these arrive already knowing how fresh they are.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ...config import get_settings

logger = logging.getLogger(__name__)

API_ROOT = "https://api.adzuna.com/v1/api/jobs"
SUPPORTED_COUNTRIES = {
    "at", "au", "be", "br", "ca", "ch", "de", "es", "fr",
    "gb", "in", "it", "mx", "nl", "nz", "pl", "sg", "us", "za",
}


class AdzunaSource:
    name = "adzuna"

    def __init__(self, country: str | None = None) -> None:
        settings = get_settings()
        self._app_id = settings.adzuna_app_id
        self._app_key = settings.adzuna_app_key
        self._country = (country or settings.adzuna_country or "fr").lower()

    def is_enabled(self) -> bool:
        return bool(self._app_id and self._app_key and self._country in SUPPORTED_COUNTRIES)

    async def search(
        self,
        *,
        query: str,
        location: str = "",
        max_results: int = 20,
        max_days_old: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self.is_enabled():
            return []

        params: dict[str, Any] = {
            "app_id": self._app_id,
            "app_key": self._app_key,
            "results_per_page": max(1, min(max_results, 50)),
            "what": query,
            # Adzuna is the one source that can filter on age server-side, so
            # spend the window on the freshest end rather than paging through
            # postings the ranking would discount anyway. `sort_by=date` is safe
            # here precisely because `max_days_old` already bounds the set:
            # every result is both recent and keyword-matched.
            "max_days_old": max_days_old or get_settings().posting_max_age_days,
            "sort_by": "date",
            "content-type": "application/json",
        }
        if location:
            params["where"] = location

        url = f"{API_ROOT}/{self._country}/search/1"
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Adzuna returned %s for query %r: %s",
                exc.response.status_code,
                query,
                exc.response.text[:200],
            )
            return []
        except Exception:
            logger.exception("Adzuna request failed for query %r", query)
            return []

        return [self._to_posting(item) for item in payload.get("results", [])]

    def _to_posting(self, item: dict[str, Any]) -> dict[str, Any]:
        company = (item.get("company") or {}).get("display_name", "")
        location = (item.get("location") or {}).get("display_name", "")
        salary_min = item.get("salary_min")
        salary_max = item.get("salary_max")
        compensation = ""
        if salary_min or salary_max:
            currency = "€" if self._country in {"fr", "de", "es", "it", "nl", "be", "at"} else ""
            compensation = f"{currency}{int(salary_min or 0)}–{currency}{int(salary_max or 0)} /yr"

        return {
            "title": item.get("title", "").replace("<strong>", "").replace("</strong>", ""),
            "company": company,
            "location": location,
            "url": item.get("redirect_url", ""),
            "source": self.name,
            "source_ref": str(item.get("id", "")),
            "snippet": (item.get("description") or "")[:1200],
            "posted_at": item.get("created", ""),
            "contract_type": item.get("contract_time", "") or item.get("contract_type", ""),
            "category": (item.get("category") or {}).get("label", ""),
            "compensation": compensation,
        }
