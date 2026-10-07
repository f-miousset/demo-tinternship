"""The platforms the Scout is told to search *first*.

These are deliberately not `JobSource` adapters. A `JobSource` is a structured
API we call ourselves (Adzuna), which needs credentials and can be off. A
`Platform` here is a **search target**: a public board that grounded search
already reaches through `site:` queries, so the only thing that makes it "wired
up" is that the Query Planner is required to write queries against it and the
Scout is required to run them before anything general.

That is the whole mechanism, and it is the right one for these three: Welcome
to the Jungle and Station F have no public API worth depending on, and scraping
LinkedIn breaches its terms (see documentation/integrations.md#linkedin). A `site:` query
against a board is exactly what a human would type, and it keeps every URL the
Scout reports something Google actually returned rather than a pattern the model
assembled.

Order and membership come from `PRIORITY_JOB_PLATFORMS` in `.env`, so a search
outside France can drop the France-specific entries without a code change.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from ...config import get_settings

logger = logging.getLogger(__name__)

WORLDWIDE = "worldwide"


@dataclass(frozen=True)
class Platform:
    """One board the Scout should lean on, and everything an agent needs to use it.

    `query_patterns` carry `{braces}` the Query Planner fills from the brief.
    They are patterns rather than finished queries because the useful part —
    the domain vocabulary — only exists once the candidate has been interviewed.

    `url_shape` and `posting_path` are the same statement twice: the prose goes
    into the Scout's prompt, the regex into `services/job_links.py`, which drops
    a URL on this domain that does not match it. Telling a model what a posting
    URL looks like is a request; the regex is what makes it a rule. Change one
    and you must change the other.
    """

    key: str
    label: str
    domains: tuple[str, ...]
    regions: tuple[str, ...]
    url_shape: str
    posting_path: re.Pattern[str]
    good_for: str
    query_patterns: tuple[str, ...]
    caveats: tuple[str, ...] = ()

    @property
    def region_note(self) -> str:
        return "worldwide" if self.regions == (WORLDWIDE,) else ", ".join(self.regions)


WELCOME_TO_THE_JUNGLE = Platform(
    key="welcome_to_the_jungle",
    label="Welcome to the Jungle",
    domains=("welcometothejungle.com", "welcomekit.co"),
    regions=("France (by far the strongest coverage)", "Spain", "Czechia", "Slovakia"),
    url_shape="welcometothejungle.com/<fr|en>/companies/<company>/jobs/<job-slug>",
    posting_path=re.compile(r"/companies/[^/]+/jobs/[^/]+"),
    good_for=(
        "The premier job board for the French tech ecosystem, and the best single "
        "source for well-funded scale-ups and corporate innovation labs in Paris. "
        "Postings carry unusually explicit detail on company culture, remote-work "
        "policy and technical stack, so the description and requirements fields "
        "come out richer here than from a search snippet."
    ),
    query_patterns=(
        'site:welcometothejungle.com/fr/companies "{role}" (stage OR alternance) {location}',
        'site:welcometothejungle.com "{role}" (stage OR internship OR alternance) {location} {season}',
        'site:welcometothejungle.com "{domain keyword}" stage {location}',
        'site:welcomekit.co "{role}" stage {location}',
    ),
    caveats=(
        "`welcomekit.co` subdomains are the same company's own careers site on "
        "Welcome to the Jungle's ATS (e.g. `station-f.welcomekit.co`) — same "
        "postings, employer-branded URL. Treat them as the same platform.",
        "A `/companies/<company>` page with no `/jobs/` segment is a company "
        "profile, not a posting.",
    ),
)

LINKEDIN = Platform(
    key="linkedin",
    label="LinkedIn (Boolean search)",
    domains=("linkedin.com/jobs",),
    regions=(WORLDWIDE,),
    url_shape="linkedin.com/jobs/view/<numeric id>",
    posting_path=re.compile(r"/jobs/view/\d+"),
    good_for=(
        "The way into corporate R&D: large-company internship requisitions and "
        "innovation-lab teams that never post to a public board. Boolean search "
        "is what makes it work — a targeted query reaches roles that plain "
        "keyword search buries."
    ),
    query_patterns=(
        'site:linkedin.com/jobs ("AI Governance" OR "Trustworthy AI" OR "GenAI") '
        'AND ("stage" OR "internship" OR "PFE") AND "Paris"',
        'site:linkedin.com/jobs ("{domain term 1}" OR "{domain term 2}" OR "{domain term 3}") '
        'AND ("stage" OR "internship" OR "PFE" OR "alternance") AND "{location}"',
        'site:linkedin.com/jobs ("{role}" OR "{role synonym}") AND ("{season}") AND "{location}"',
    ),
    caveats=(
        "The first pattern is a worked example, not a query to reuse verbatim — "
        "build each OR group from the brief's own vocabulary, three to five "
        "quoted terms per group. One generic term wastes the query.",
        "`PFE` (projet de fin d'études) is the French term for an end-of-studies "
        "internship and belongs in every French-language group, alongside "
        "`stage` and `alternance`.",
        "Google treats `AND` as implicit; write it anyway so the same string can "
        "be pasted straight into LinkedIn's own search box.",
        "Only `/jobs/view/<id>` is a posting. `/jobs/search`, `/jobs/collections` "
        "and feed posts are not.",
        "Logged-out fetches often hit a login wall, so URL verification may flag "
        "a posting that is genuinely live. When the same job also exists on the "
        "employer's own site, keep that URL instead.",
    ),
)

STATION_F = Platform(
    key="station_f",
    label="Station F Jobs",
    domains=("jobs.stationf.co",),
    regions=("France — Paris only",),
    url_shape="jobs.stationf.co/companies/<company>/jobs/<job-slug>_paris",
    posting_path=re.compile(r"/companies/[^/]+/jobs/[^/]+"),
    good_for=(
        "The board of the largest startup campus in Paris — around a thousand "
        "startups in one place. It carries technically foundational AI roles "
        "(AI engineers on multi-agent platforms, LLM automation) that show up "
        "here before, or instead of, the big boards."
    ),
    query_patterns=(
        'site:jobs.stationf.co "{role}" (stage OR internship)',
        'site:jobs.stationf.co ("stage" OR "internship" OR "PFE") "{domain keyword}"',
        'site:jobs.stationf.co "{role}" {season}',
    ),
    caveats=(
        "Paris-only. If the brief has no Paris / Île-de-France location, skip "
        "this platform entirely and say so.",
        "The board runs on Welcome to the Jungle, so the same posting frequently "
        "appears on both — expect duplicates across the two.",
        "`/startups`, `/search` and `/companies/<company>` are not postings.",
    ),
)

PLATFORMS: dict[str, Platform] = {
    platform.key: platform
    for platform in (WELCOME_TO_THE_JUNGLE, LINKEDIN, STATION_F)
}

DEFAULT_PRIORITY = "welcome_to_the_jungle,linkedin,station_f"


def priority_platforms() -> list[Platform]:
    """The configured platforms, in the configured order.

    Unknown keys are logged and skipped rather than raising: a typo in `.env`
    should cost one platform, not the whole run.
    """
    raw = get_settings().priority_job_platforms
    ordered: list[Platform] = []
    for key in (part.strip().lower() for part in raw.split(",")):
        if not key:
            continue
        platform = PLATFORMS.get(key)
        if platform is None:
            logger.warning(
                "Unknown platform %r in PRIORITY_JOB_PLATFORMS — known keys: %s",
                key,
                ", ".join(PLATFORMS),
            )
            continue
        if platform not in ordered:
            ordered.append(platform)
    return ordered


def priority_domains() -> list[str]:
    """Every domain that counts as a priority platform, for URL authority ranking."""
    return [domain for platform in priority_platforms() for domain in platform.domains]


def platform_labels() -> list[str]:
    return [platform.label for platform in priority_platforms()]
