"""How old a posting is, and what that age costs it in the ranking.

An internship posting is perishable. The role is filled, the cohort closes, the
requisition is pulled — and none of that changes the page, so a four-month-old
posting reads exactly like yesterday's. The candidate finds out by applying into
a closed pipeline, which is the same wasted application this app exists to
prevent. Fit tells you whether a job is worth wanting; recency tells you whether
it is still there to be had.

So age is a ranking input, and it is enforced here rather than asked for in a
prompt. The matcher is told to weight recency and does; but "the freshest of two
equal matches wins" is a promise to the user, and `agents/investigator.py` says
why a promise lives in Python: a prompt is a request, and a request is not a
guarantee.

Three jobs, in the order the pipeline needs them:

* **`parse`** turns whatever a posting claims about its date — ISO, `12 août
  2026`, `3 days ago`, `il y a 2 semaines` — into a real date. Search snippets
  and job boards each have their own dialect, and the Scout copies them
  verbatim, which is what it should do.
* **`from_page`** reads the date out of the posting's own HTML. Every link is
  fetched anyway by `services/verification.py`, and most job pages carry a
  schema.org `datePosted`, so the authoritative answer is already on the wire.
  A date the employer published beats a date a model inferred from a snippet.
* **`freshness`** turns an age into the multiplier that reorders the ranking.

Nothing here deletes a posting. Age demotes; it never condemns — a six-month-old
posting that is still open is a real job, and the sort already buries it behind
anything fresher. It only survives to be shown when nothing fresher exists,
which is exactly when the candidate wants to see it.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ..config import get_settings

# What an undated posting is worth, as an age in days. Most grounded-search
# leads carry no date at all, so this number decides a lot: too low and every
# undated posting is buried under anything with a timestamp, too high and a
# missing date becomes a way to launder a stale job into the top slot. Sitting
# it just under the default half-life says the honest thing — an undated posting
# must not outrank one known to be days old, and must not be buried under one
# known to be months old.
UNKNOWN_AGE_DAYS = 20

# How far the multiplier can fall. Age discounts a match; it does not annul it,
# and a 9/10 posting from last spring should still outrank a 3/10 from today.
FLOOR = 0.30

# Age past which the matcher is told to treat a posting as stale and say so in
# its risks, as a multiple of the half-life. At the default 21 days that is nine
# weeks — comfortably past the point where an internship requisition that is
# still open is the exception rather than the rule.
STALE_MULTIPLE = 3


def half_life_days() -> float:
    """Days for a posting to lose half its freshness. Read live — it is a knob."""
    return max(1.0, float(get_settings().posting_half_life_days))


def stale_days() -> int:
    return round(half_life_days() * STALE_MULTIPLE)


def today() -> date:
    return datetime.now(UTC).date()


# ---------------------------------------------------------------------------
# Parsing what a posting says about its own date
# ---------------------------------------------------------------------------

_MONTHS = {
    "january": 1, "jan": 1, "janvier": 1, "janv": 1, "januar": 1,
    "february": 2, "feb": 2, "février": 2, "fevrier": 2, "févr": 2, "fevr": 2, "februar": 2,
    "march": 3, "mar": 3, "mars": 3, "märz": 3, "marz": 3,
    "april": 4, "apr": 4, "avril": 4, "avr": 4,
    "may": 5, "mai": 5,
    "june": 6, "jun": 6, "juin": 6, "juni": 6,
    "july": 7, "jul": 7, "juillet": 7, "juil": 7, "juli": 7,
    "august": 8, "aug": 8, "août": 8, "aout": 8, "aoû": 8,
    "september": 9, "sep": 9, "sept": 9, "septembre": 9,
    "october": 10, "oct": 10, "octobre": 10, "oktober": 10,
    "november": 11, "nov": 11, "novembre": 11,
    "december": 12, "dec": 12, "décembre": 12, "decembre": 12, "déc": 12, "dezember": 12,
}

# Days per unit, for a relative phrase. Deliberately coarse: "2 months ago" is
# not a claim about 61 days, it is a claim about being old.
_UNITS = {
    "minute": 0, "minutes": 0, "min": 0, "minuten": 0,
    "hour": 0, "hours": 0, "hr": 0, "hrs": 0, "heure": 0, "heures": 0, "stunde": 0, "stunden": 0,
    "day": 1, "days": 1, "jour": 1, "jours": 1, "tag": 1, "tage": 1, "tagen": 1,
    "week": 7, "weeks": 7, "semaine": 7, "semaines": 7, "woche": 7, "wochen": 7,
    "month": 30, "months": 30, "mois": 30, "monat": 30, "monate": 30, "monaten": 30,
    "year": 365, "years": 365, "an": 365, "ans": 365, "année": 365, "annee": 365,
    "jahr": 365, "jahre": 365, "jahren": 365,
}

# A relative phrase has to *say* it is relative. Without this, "6 months" in a
# sloppily-filled field reads as "posted six months ago" when the posting meant
# its own duration — which would bury a live job on the strength of a typo.
_RELATIVE_MARKERS = ("ago", "il y a", "depuis", "vor ", "posted", "publi", "seit", "il-y-a")

_TODAY_WORDS = ("today", "aujourd'hui", "aujourdhui", "heute", "just posted", "just now", "à l'instant")
_YESTERDAY_WORDS = ("yesterday", "hier", "gestern")

# No trailing `\b` on the day: an ISO *timestamp* runs the day straight into
# its time (`2026-08-12T09:30:00Z`), which is a boundary between two word
# characters and therefore no boundary at all — so anchoring here quietly
# matched `2026-08` and read every timestamp as the first of the month.
_ISO = re.compile(r"\b(\d{4})-(\d{2})(?:-(\d{2}))?")
_DMY = re.compile(r"\b(\d{1,2})[ ./,-]+([A-Za-zÀ-ÿ]{3,10})\.?[ ./,-]+(\d{4})\b")
_MDY = re.compile(r"\b([A-Za-zÀ-ÿ]{3,10})\.?[ ./,-]+(\d{1,2})(?:st|nd|rd|th)?[ ./,-]+(\d{4})\b")
_SLASHED = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_RELATIVE = re.compile(r"(\d{1,3})\s*\+?\s*([A-Za-zÀ-ÿ]{1,8})")


def _month(name: str) -> int | None:
    return _MONTHS.get(name.strip(".").lower())


def _safe(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse(value: Any, *, on: date | None = None) -> date | None:
    """The date a posting string refers to, or `None` when it says nothing.

    Handles the four dialects that actually reach us: ISO from structured job
    boards, written-out dates from posting pages, `3 days ago` from search
    snippets, and the French and German forms of both — the Scout copies a
    result verbatim, and it should.

    A future date is a mistake somewhere (a start date filed as a posting date,
    a locale-swapped day and month), so it is refused rather than treated as
    infinitely fresh.
    """
    text = str(value or "").strip().lower()
    if not text:
        return None
    now = on or today()

    if any(word in text for word in _TODAY_WORDS):
        return now
    if any(word in text for word in _YESTERDAY_WORDS):
        return now - timedelta(days=1)

    found: date | None = None

    match = _ISO.search(text)
    if match:
        year, month, day = match.group(1), match.group(2), match.group(3)
        # A bare `2026-08` is the month, not the day it happens to be parsed as.
        # The 1st is the conservative read: it makes the posting look older, and
        # overstating age costs a slot while understating it costs the candidate
        # an application.
        found = _safe(int(year), int(month), int(day or 1))

    if found is None:
        match = _DMY.search(text)
        if match and (month := _month(match.group(2))):
            found = _safe(int(match.group(3)), month, int(match.group(1)))

    if found is None:
        match = _MDY.search(text)
        if match and (month := _month(match.group(1))):
            found = _safe(int(match.group(3)), month, int(match.group(2)))

    if found is None:
        match = _SLASHED.search(text)
        if match:
            first, second = int(match.group(1)), int(match.group(2))
            # Day-first is the French and British convention and the one these
            # postings are written in; fall back to month-first only when the
            # first number cannot be a month.
            day, month = (first, second) if second <= 12 else (second, first)
            found = _safe(int(match.group(3)), month, day)

    if found is None and any(marker in text for marker in _RELATIVE_MARKERS):
        for amount, unit in _RELATIVE.findall(text):
            days = _UNITS.get(unit.strip(".").lower())
            if days is not None:
                found = now - timedelta(days=int(amount) * days)
                break

    if found is None or found > now:
        return None
    return found


def from_page(html: str) -> str:
    """The posting date the page itself publishes, as ISO, or `""`.

    Most job pages — every major ATS, and the boards that want their postings in
    Google's job results — carry a schema.org `JobPosting` with a `datePosted`.
    That is the employer's own answer, and `services/verification.py` already
    has the bytes in hand, so it costs nothing to ask.

    Reads only the first slice of the page that the checker fetched, which is
    where `<head>` metadata lives. A page that buries its JSON-LD past that
    simply returns nothing, the same as a page that carries none.
    """
    # The JSON-LD is sometimes HTML-escaped into an attribute, so accept both
    # quote forms rather than only the literal one.
    for pattern in (
        r'"datePosted"\s*:\s*"([^"]{4,40})"',
        r"&quot;datePosted&quot;\s*:\s*&quot;([^&]{4,40})&quot;",
        r'property=["\']article:published_time["\']\s+content=["\']([^"\']{4,40})["\']',
        r'content=["\']([^"\']{4,40})["\']\s+property=["\']article:published_time["\']',
    ):
        match = re.search(pattern, html or "", re.IGNORECASE)
        if match:
            found = parse(match.group(1))
            if found is not None:
                return found.isoformat()
    return ""


# ---------------------------------------------------------------------------
# What an age is worth
# ---------------------------------------------------------------------------


def age_days(value: Any, *, on: date | None = None) -> int | None:
    """How many days old the posting claims to be, or `None` if it does not say."""
    posted = parse(value, on=on)
    if posted is None:
        return None
    return max(0, ((on or today()) - posted).days)


def freshness(age: int | None) -> float:
    """The multiplier an age applies to a fit score — 1.0 today, `FLOOR` eventually.

    Exponential decay rather than buckets: two postings a day apart should never
    swap places because one of them crossed a threshold overnight. At the
    default 21-day half-life a posting is worth ~0.65 of itself after three
    weeks, ~0.42 after two months and ~0.36 after three, which is heavy enough
    that a stale posting only reaches the user when nothing fresher matched.
    """
    if age is None:
        age = UNKNOWN_AGE_DAYS
    return FLOOR + (1.0 - FLOOR) * 0.5 ** (max(0, age) / half_life_days())


def score(fit_score: float, age: int | None) -> float:
    """The ordering key: the match, discounted by how likely it is to be gone."""
    return round(float(fit_score or 0.0) * freshness(age), 4)


def with_age(jobs: list[dict[str, Any]], *, on: date | None = None) -> list[dict[str, Any]]:
    """Stamp each posting with the date it was published and how old that makes it.

    `posted_at` is left exactly as the posting gave it — it is what the candidate
    reads, and "3 days ago" is friendlier than an ISO date. The parsed form goes
    alongside it in `posted_on` so nothing downstream has to parse prose twice,
    and `posted_days_ago` is the number the matcher's ranking rule is written
    against, computed here rather than asked of a model.
    """
    on = on or today()
    aged: list[dict[str, Any]] = []
    for job in jobs:
        posted = parse(job.get("posted_at"), on=on)
        aged.append(
            {
                **job,
                "posted_on": posted.isoformat() if posted else "",
                "posted_days_ago": None if posted is None else max(0, (on - posted).days),
            }
        )
    return aged


def annotate(jobs: list[dict[str, Any]], *, on: date | None = None) -> list[dict[str, Any]]:
    """`with_age`, plus the ordering key the ranking is re-sorted on."""
    return [
        {**job, "recency_score": score(job.get("fit_score", 0.0), job["posted_days_ago"])}
        for job in with_age(jobs, on=on)
    ]


def rank(jobs: list[dict[str, Any]], *, on: date | None = None) -> list[dict[str, Any]]:
    """Annotated postings, freshest-best first.

    The tie-break is the raw fit score, so two postings the same age are still
    ordered by how good a match they are — recency reorders the ranking, it does
    not replace it.
    """
    return sorted(
        annotate(jobs, on=on),
        key=lambda job: (job["recency_score"], float(job.get("fit_score", 0.0) or 0.0)),
        reverse=True,
    )


def tally(jobs: list[dict[str, Any]]) -> dict[str, int]:
    """How fresh a run's results are, in the buckets the Jobs page reports."""
    counts = {"week": 0, "month": 0, "quarter": 0, "older": 0, "undated": 0}
    for job in jobs:
        age = job.get("posted_days_ago")
        if age is None:
            counts["undated"] += 1
        elif age <= 7:
            counts["week"] += 1
        elif age <= 30:
            counts["month"] += 1
        elif age <= 90:
            counts["quarter"] += 1
        else:
            counts["older"] += 1
    return counts
