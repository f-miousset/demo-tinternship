"""The pluggable job-discovery interface.

Two kinds of source exist:

* **Model-native** — Gemini's Google Search grounding. There is no adapter for
  it here; the Scout agent simply carries the `google_search` tool. It is
  always available and needs no configuration.
* **Structured APIs** — Adzuna today, others later. These implement `JobSource`
  and are exposed to the Scout as a callable tool, but only when their
  credentials are present. A missing key disables the source silently rather
  than breaking the run.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class JobSource(Protocol):
    """A structured job-posting provider."""

    name: str

    def is_enabled(self) -> bool:
        """Whether this source has what it needs to run (credentials, config)."""
        ...

    async def search(
        self,
        *,
        query: str,
        location: str = "",
        max_results: int = 20,
        # `None` means "the app's configured window" — `POSTING_MAX_AGE_DAYS`,
        # which is what makes the default lean recent without every caller
        # having to know the number.
        max_days_old: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return raw postings as plain dicts. Never raises — errors come back
        as an empty list plus a logged warning, so one dead source cannot take
        the discovery stage down with it."""
        ...
