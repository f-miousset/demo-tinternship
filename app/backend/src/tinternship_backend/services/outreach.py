"""Who to contact about one posting — and links proved to open something real.

A cold application goes into a queue. A message to a recruiter, an alumnus of
the candidate's own school, or the person who will actually manage the role
skips it. This module is the half of that job that does not involve a model.

## The rule this module exists to enforce

Every link handed to the candidate is one of exactly two kinds, and neither of
them can be a plausible invention:

* **Constructed.** A LinkedIn people-search URL built here, in Python, from
  strings the app already knows — the employer's name, the candidate's school,
  the posting's own keywords. A search URL cannot 404: it opens a real search in
  the candidate's own logged-in session. The Contact Scout never writes one of
  these; it writes *keywords*, and `people_search()` turns them into a URL. Same
  reason the Matcher answers with an index rather than a posting.
* **Discovered, then proved.** A `linkedin.com/in/<slug>` or a page that names a
  person. It is kept **only if a fetch proved it live**, and for a profile only
  if the page turned out to be that person. Anything else is dropped and
  replaced by a constructed search for the same person, which lands the
  candidate one click away instead of on a 404.

Measured on 2026-08-29, which is what makes the second kind checkable at all:

| URL | Unauthenticated response |
| --- | --- |
| `/company/mistralai/` | 200, the real page |
| `/company/<invented>/` | **404** |
| `/in/satyanadella/` | 200, titled `Satya Nadella - Microsoft` |
| `/in/<invented>/` | **999** (LinkedIn's refusal) |
| `/school/<any>/` | 999 — never verifiable |
| `/company/<slug>/people/`, `/search/…` | redirect to the login wall |

So a profile page hands back the person's **name and current employer in its
title** — enough to prove not just that the slug exists but that it belongs to
the person the research claimed. 999 is LinkedIn refusing, which is also what it
does when rate-limiting, so it is never read as "this person does not exist" —
it is read as "not proved", and the URL is dropped either way. Prove it or fall
back to something that cannot be wrong.

School pages are 999 for everyone, so nothing here ever links to one.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote_plus, urlparse

import httpx

from . import job_links, verification
from .profile_store import profile_as_dict

logger = logging.getLogger(__name__)

LINKEDIN = "https://www.linkedin.com"
_TIMEOUT = 12.0
# LinkedIn answers a burst with 999. Four at a time keeps a run's handful of
# checks inside what one household IP is allowed, and a run never checks many:
# the people the research names, plus one company slug.
_CONCURRENCY = 4
# What one plan may ask to be fetched, whatever the model returned. A run that
# tried to check forty profiles would be rate-limited into reporting all of them
# unproved, which looks exactly like a run that found nothing.
MAX_CHECKS = 12

# Words that say what kind of contract a posting is, not what the work is. They
# are in almost every internship title and in almost no employee's job title, so
# searching for them finds nobody who works there.
_CONTRACT_WORDS = {
    "internship", "intern", "stage", "stagiaire", "alternance", "alternant",
    "apprenticeship", "apprenti", "graduate", "junior", "trainee", "vie",
    "h", "f", "m", "w", "d", "hf", "fh", "hfd", "cdi", "cdd", "summer",
    "placement", "student", "étudiant", "etudiant", "assistant",
}


# ---------------------------------------------------------------------------
# Building links that cannot be wrong
# ---------------------------------------------------------------------------


def phrase(text: str) -> str:
    """One search term, quoted when it is more than a word.

    LinkedIn treats an unquoted multi-word term as separate words, so
    `Nimbus Labs` matches everyone at Nimbus *and* everyone in a lab.
    """
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    # A term that is already quoted, or is a boolean group, is left alone.
    if cleaned.startswith(("\"", "(")):
        return cleaned
    return f'"{cleaned}"' if " " in cleaned else cleaned


def people_search(keywords: str) -> str:
    """A LinkedIn people search. The only kind of LinkedIn link that always works.

    It resolves to the login wall for us and to real results for the candidate,
    which is the whole point: this app is not logged in and their browser is.
    """
    query = " ".join((keywords or "").split())
    if not query:
        return ""
    return f"{LINKEDIN}/search/results/people/?keywords={quote_plus(query)}"


def company_url(slug: str) -> str:
    slug = (slug or "").strip().strip("/")
    return f"{LINKEDIN}/company/{quote_plus(slug)}/" if slug else ""


def company_people(slug: str, keywords: str = "") -> str:
    """The employee list on a company page — the best browse there is, when the
    slug has been proved. With `keywords` it becomes a search inside that
    company, which needs no company id and so cannot be built wrong."""
    base = company_url(slug)
    if not base:
        return ""
    if not keywords.strip():
        return f"{base}people/"
    return f"{base}people/?keywords={quote_plus(' '.join(keywords.split()))}"


def web_search(query: str) -> str:
    """The open web, for the profiles LinkedIn's own search hides from a free
    account. `site:linkedin.com/in` is how you find a person you cannot browse to."""
    query = " ".join((query or "").split())
    return f"https://www.google.com/search?q={quote_plus(query)}" if query else ""


def is_linkedin(url: str) -> bool:
    """Any of LinkedIn's hosts, country prefixes included.

    A profile found through search is cited as `fr.linkedin.com/in/…` about as
    often as `www.` — the country prefix is which edge served the page, not a
    different site — and treating those as "not LinkedIn" would send every
    French profile down the unproved path.
    """
    host = (urlparse((url or "").strip()).hostname or "").casefold()
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def profile_slug(url: str) -> str:
    """The `/in/<slug>` part of a LinkedIn profile URL, or "" if it is not one."""
    if not is_linkedin(url):
        return ""
    match = re.match(r"^/in/([^/?#]+)", urlparse(url.strip()).path)
    return match.group(1) if match else ""


def canonical_profile(url: str) -> str:
    """A profile URL rewritten to the one form we check and store."""
    slug = profile_slug(url)
    return f"{LINKEDIN}/in/{slug}" if slug else ""


# ---------------------------------------------------------------------------
# What the candidate brings to a search
# ---------------------------------------------------------------------------


def school_names(limit: int = 3) -> list[str]:
    """The schools on the master profile, most recent entry first.

    Read here rather than asked of a model: which schools the candidate attended
    is a fact the app already holds, and an alumni search built on a
    misremembered school name finds strangers.
    """
    profile = profile_as_dict() or {}
    names: list[str] = []
    for entry in profile.get("education") or []:
        if not isinstance(entry, dict):
            continue
        name = " ".join(str(entry.get("institution") or "").split())
        if name and name.lower() not in {existing.lower() for existing in names}:
            names.append(name)
    return names[:limit]


def role_terms(title: str, keywords: list[str] | None = None) -> str:
    """What to call this job when looking for the people who already do it.

    The posting's title is the wrong query: "Machine Learning Intern (H/F)"
    matches interns, and the people worth contacting are not interns. Stripping
    the contract vocabulary leaves the part that is also in a permanent
    employee's headline.
    """
    for keyword in keywords or []:
        term = " ".join(str(keyword).split())
        # A posting's own keyword is already the field's vocabulary, but only
        # a short one is a job-title-shaped query.
        if term and len(term.split()) <= 3 and term.lower() not in _CONTRACT_WORDS:
            return term
    words = [
        word
        for word in re.split(r"[^\w'\-]+", title or "")
        if word and word.lower().strip(".") not in _CONTRACT_WORDS and len(word) > 1
    ]
    return " ".join(words[:4])


@dataclass(frozen=True)
class Angle:
    """One way to search for people, and the link that runs it."""

    key: str
    label: str
    why: str
    keywords: str
    url: str

    def as_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "why": self.why,
            "keywords": self.keywords,
            "url": self.url,
        }


def standard_angles(
    company: str, title: str, keywords: list[str] | None = None, schools: list[str] | None = None
) -> list[Angle]:
    """The searches that exist whatever the research found.

    Built from the employer's name, the candidate's own schools and the
    posting's vocabulary — all of which the app already knows — so a run whose
    grounded research turned up nobody still hands the candidate six working
    searches rather than an empty page. Every one of these opens results in
    their own session; none of them can be a fabrication.
    """
    employer = phrase(company)
    if not employer:
        return []
    role = phrase(role_terms(title, keywords))
    angles: list[Angle] = []

    def add(key: str, label: str, why: str, query: str) -> None:
        angles.append(Angle(key, label, why, query, people_search(query)))

    for school in (schools or [])[:2]:
        add(
            "alumni",
            f"{company} people who went to {school}",
            "A shared school is the single strongest reason for a stranger to answer, "
            "and it needs no introduction beyond naming it.",
            f"{employer} {phrase(school)}",
        )
    add(
        "recruiters",
        f"Recruiters at {company}",
        "They own the requisition and can move an application out of the queue.",
        f'{employer} (recruiter OR "talent acquisition" OR recrutement OR "talent acquisition partner")',
    )
    add(
        "campus",
        f"Campus and early-careers at {company}",
        "Internships are usually filled by whoever runs the school programme, not by "
        "the general recruiting team.",
        f'{employer} ("campus" OR "early careers" OR "university relations" '
        f'OR "école" OR "stage" OR "alternance")',
    )
    if role:
        add(
            "team",
            f"People doing this work at {company}",
            "The team you would join. They know whether the role is really open and what "
            "it is actually about.",
            f"{employer} {role}",
        )
        add(
            "manager",
            f"Who probably manages this role at {company}",
            "The hiring manager decides. A short, specific message to them is worth more "
            "than a polished application to nobody.",
            f'{employer} ("head of" OR lead OR manager OR responsable) {role}',
        )
    for school in (schools or [])[:1]:
        if role:
            add(
                "alumni_field",
                f"{school} alumni doing this work anywhere",
                "Not for this posting — for the conversation that tells you what the field "
                "hires for. They almost always reply.",
                f"{phrase(school)} {role}",
            )
    return angles


def fallback_search(name: str, company: str) -> str:
    """How to find one named person when their profile URL could not be proved."""
    query = " ".join(part for part in (phrase(name), phrase(company)) if part)
    return people_search(query)


def open_web_search(name: str, company: str) -> str:
    query = " ".join(
        part for part in ("site:linkedin.com/in", phrase(name), phrase(company)) if part
    )
    return web_search(query)


# ---------------------------------------------------------------------------
# Proving a discovered link
# ---------------------------------------------------------------------------

LIVE = "live"
GONE = "gone"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class PageCheck:
    url: str
    verdict: str
    http_status: int = 0
    title: str = ""


async def _get(client: httpx.AsyncClient, url: str) -> PageCheck:
    """Fetch one page and say whether it is there, reading its own title.

    Deliberately *not* `verification.check_urls`: that answers "does this link
    open the job posting", and judges a URL against the shapes a posting has.
    A person's profile and the page that names them are neither postings nor
    indexes, so its `index` verdict would reject exactly the pages wanted here.
    What is shared is the browser identity and the "the title is the verdict"
    rule, both imported rather than restated.
    """
    try:
        async with client.stream("GET", url) as response:
            body = b""
            if response.headers.get("content-type", "").startswith("text/"):
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) >= 64 * 1024:
                        break
            text = body.decode("utf-8", "replace")
    except Exception:
        logger.debug("Contact link check failed for %s", url, exc_info=True)
        return PageCheck(url=url, verdict=UNKNOWN)

    title = job_links.headline(text)
    status = verification.classify(response.status_code)
    if status == verification.DEAD:
        return PageCheck(url, GONE, response.status_code, title)
    if status != verification.OK:
        # 999 from LinkedIn, a WAF's 403, a 5xx. Never read as "this person does
        # not exist" — LinkedIn answers 999 to a burst of perfectly good URLs.
        return PageCheck(url, UNKNOWN, response.status_code, title)
    if job_links.headline_says_gone(title) is not None:
        return PageCheck(url, GONE, response.status_code, title)
    return PageCheck(url, LIVE, response.status_code, title)


def _fold(text: str) -> str:
    """Casefolded and stripped of accents, so `Müller` matches `Muller`."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def name_matches(name: str, title: str) -> bool:
    """Whether a LinkedIn page's title is the person the research named.

    A profile page titles itself `Satya Nadella - Microsoft | LinkedIn`, so the
    fetch that proves the slug exists also proves *whose* it is. Both ends of
    the name must appear — first and last — because a slug that resolves to a
    different person with the same surname is the failure this check exists for,
    and because the login wall's own title contains neither.

    Middle names are ignored: research writes "Marie Claire Dubois" for a
    profile that says "Marie Dubois" often enough that requiring every token
    would throw away good matches.
    """
    tokens = [token for token in re.split(r"[^\w]+", _fold(name)) if len(token) > 1]
    if not tokens:
        return False
    haystack = _fold(title)
    wanted = {tokens[0], tokens[-1]}
    return all(token in haystack for token in wanted)


async def check_pages(urls: list[str]) -> dict[str, PageCheck]:
    targets = [
        url for url in dict.fromkeys(urls) if url and url.startswith("http")
    ][:MAX_CHECKS]
    if not targets:
        return {}

    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def one(url: str) -> PageCheck:
        async with semaphore:
            return await _get(client, url)

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers=verification.BROWSER_HEADERS,
        verify=True,
    ) as client:
        results = await asyncio.gather(*(one(url) for url in targets))
    return {check.url: check for check in results}


# ---------------------------------------------------------------------------
# The whole post-gate pass
# ---------------------------------------------------------------------------

# How many named people one plan may carry into the app. Past about this many
# the candidate stops writing messages and starts skimming a list, which is the
# thing they already had.
MAX_PEOPLE = 8

VERIFIED = "verified"
MISMATCH = "mismatch"
UNPROVED = "unproved"

# Why somebody did not make it onto the page. Recorded rather than swallowed: a
# list that silently shrank is indistinguishable from a search that found less,
# and "we dropped two people whose pages are gone" is information the candidate
# can act on — it usually means the team page moved.
MISMATCH_REASON = "their LinkedIn page turned out to belong to somebody else"
GONE_REASON = "the only page that named them is gone, and their profile could not be proved"
UNPROVED_REASON = "nothing that could be fetched actually names them"


def _person(entry: dict) -> dict:
    return {
        "name": " ".join(str(entry.get("name") or "").split()),
        "role": str(entry.get("role") or "").strip(),
        "category": str(entry.get("category") or "other").strip().lower(),
        "why": str(entry.get("why") or "").strip(),
        # Always present, always empty here. The message to send this person is
        # written on request, one at a time, by `flows.write_opening_line`,
        # which fills this key in place on the saved artifact — so the page can
        # read it without knowing whether it has been asked for yet.
        "opening_line": "",
        "confidence": str(entry.get("confidence") or "").strip().lower(),
        "linkedin_url": canonical_profile(str(entry.get("linkedin_url") or "")),
        "evidence_url": str(entry.get("evidence_url") or "").strip(),
    }


async def resolve(
    plan: dict,
    *,
    company: str,
    title: str,
    keywords: list[str] | None = None,
    schools: list[str] | None = None,
) -> dict:
    """Turn what the Contact Scout wrote into what the candidate is shown.

    Everything that can be checked is checked here, after the quality gate,
    because whether a URL resolves is a fact about the world rather than a
    judgement about the artifact — the same division as the résumé's page count
    and the interview brief's citations.

    Three things happen, in this order:

    1. **The searches are built.** `standard_angles` first — they exist whatever
       the research found — then the scout's own angles, which arrive as
       keywords and become URLs here.
    2. **Discovered links are proved.** Every profile URL and every page that
       names somebody is fetched. A profile survives only if the page is live
       *and* titled with that person's name.
    3. **Anybody left standing on nothing is dropped**, and why is recorded
       rather than swallowed: a list that silently shrank is indistinguishable
       from a search that found less.
    """
    schools = schools if schools is not None else school_names()
    people = [_person(entry) for entry in (plan.get("people") or []) if isinstance(entry, dict)]
    people = [person for person in people if person["name"]][:MAX_PEOPLE]
    slug = str(plan.get("company_linkedin_slug") or "").strip().strip("/")

    wanted: list[str] = []
    for person in people:
        wanted += [url for url in (person["linkedin_url"], person["evidence_url"]) if url]
    if slug:
        wanted.append(company_url(slug))
    checks = await check_pages(wanted)

    kept: list[dict] = []
    dropped: list[dict] = []
    for person in people:
        profile_status = ""
        if person["linkedin_url"]:
            check = checks.get(person["linkedin_url"])
            if check is None or check.verdict != LIVE:
                profile_status = "gone" if check and check.verdict == GONE else UNPROVED
            elif not name_matches(person["name"], check.title):
                profile_status = MISMATCH
            else:
                profile_status = VERIFIED
        if profile_status != VERIFIED:
            # Dropped, not shown with a warning: a link that opens the wrong
            # person costs exactly the time this feature exists to save, and the
            # search below finds them in one click.
            person["linkedin_url"] = ""

        evidence = checks.get(person["evidence_url"]) if person["evidence_url"] else None
        evidence_gone = evidence is not None and evidence.verdict == GONE
        if evidence_gone:
            person["evidence_url"] = ""

        person["profile_status"] = profile_status
        person["evidence_status"] = evidence.verdict if evidence else ""
        person["search_url"] = fallback_search(person["name"], company)
        person["web_url"] = open_web_search(person["name"], company)

        if profile_status == VERIFIED or person["evidence_url"]:
            kept.append(person)
        else:
            if profile_status == MISMATCH:
                reason = MISMATCH_REASON
            elif evidence_gone:
                reason = GONE_REASON
            else:
                reason = UNPROVED_REASON
            dropped.append(
                {"name": person["name"], "role": person["role"], "reason": reason}
            )

    # Verified profiles first: they are the ones the candidate can act on
    # without a search. Order is otherwise the scout's.
    kept.sort(key=lambda person: person["profile_status"] != VERIFIED)

    angles = [angle.as_dict() for angle in standard_angles(company, title, keywords, schools)]
    seen = {angle["keywords"].casefold() for angle in angles}
    for entry in plan.get("angles") or []:
        if not isinstance(entry, dict):
            continue
        query = " ".join(str(entry.get("keywords") or "").split())
        if not query or query.casefold() in seen:
            continue
        seen.add(query.casefold())
        angles.append(
            {
                "key": "scout",
                "label": str(entry.get("label") or query).strip(),
                "why": str(entry.get("why") or "").strip(),
                "keywords": query,
                "url": people_search(query),
            }
        )

    company_check = checks.get(company_url(slug)) if slug else None
    company_block: dict[str, str] = {}
    if company_check is not None and company_check.verdict == LIVE:
        # Proved, so the pages hanging off it are real too — they sit behind the
        # login wall for us and open for the candidate.
        company_block = {
            "slug": slug,
            "url": company_url(slug),
            "people_url": company_people(slug),
            "recruiters_url": company_people(slug, "recruiter talent acquisition"),
        }

    return {
        "people": kept,
        "dropped": dropped,
        "angles": angles,
        "company": company_block,
        "approach": [str(item) for item in (plan.get("approach") or [])],
        "notes": str(plan.get("notes") or "").strip(),
        "sources": [
            source
            for source in (plan.get("sources") or [])
            if isinstance(source, dict) and str(source.get("url") or "").strip()
        ],
        "checked": {
            "people_named": len(people),
            "profiles_verified": sum(1 for person in kept if person["profile_status"] == VERIFIED),
            "dropped": len(dropped),
            "searches": len(angles),
        },
    }
