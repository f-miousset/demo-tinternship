"""Does a link open the posting, or just the company's careers page?

`verification.py` asks "is anything there?" and answers with an HTTP status.
On its own that turned out to be the wrong question. Three links saved by a
real run all returned 200 and were badged *link verified*:

* `careers.3ds.com/jobs/<slug>` → settles on `www.3ds.com/careers`, a careers
  homepage with a search box.
* `jobs.sap.com/job/<slug>/` (the numeric requisition id dropped from the end)
  → settles on `jobs.sap.com/errorpage/`.
* the classic `jobs.lever.co/<company>` — a board landing page the model
  assembled from a pattern, which 200s happily because the company exists.

So this module asks the other question — *where does the link go* — at the two
moments the answer is available:

* **Before fetching**, `is_openable()` judges the URL's own shape. A board
  landing page, a company profile, a bare `/careers` root or a search page is
  not a posting, and no HTTP request is needed to know it.
* **After fetching**, `landing()` judges where the redirects settled. A deep
  link that ends on a careers index, an error page or a login wall did not
  survive, whatever the status code says.

Both are heuristics over URLs, so they are deliberately asymmetric. The shape
gate rejects only what it positively recognises as an index — an unfamiliar
`site.com/x/y` is assumed to be a posting, because a false reject silently
deletes a real job. The one place it is strict is a domain whose posting shape
we actually know: the priority platforms declare theirs, and the big ATSs are
listed below, because those are precisely the URLs a model reconstructs from
memory. The other strict case is a URL that names no site at all: a Gemini
grounding redirect, which `services/grounding.py` is meant to have resolved
before the run gets here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from ..tools.job_sources.platforms import PLATFORMS
from .grounding import is_grounding_redirect

# A page that renders "this posting is gone" while answering 200 — the soft
# 404. Matched against the title and first heading only: "not found" in a
# footer is not a verdict, and a posting whose own prose says "no longer
# accepting" is still a posting. Used on the HTML the checker fetched and on the
# title a real browser renders, so both paths judge by one rule.
GONE_MARKERS = (
    "404",
    "page not found",
    "not found",
    "page introuvable",
    "offre introuvable",
    "offre expir",
    "seite nicht gefunden",
    "no longer available",
    "no longer accepting",
    "n'est plus disponible",
    "position closed",
    "job closed",
    "expired",
)

# What a URL is.
POSTING = "posting"
INDEX = "index"
MISSING = "missing"
# A Google Search grounding redirect `services/grounding.py` could not follow.
# Its own kind rather than `MISSING`, because there *is* a link — it just names
# Google instead of the employer and stops working in a few weeks.
REDIRECT = "redirect"

# What a *landing* URL says about the link that reached it. `POSTING` here
# means "nothing suspicious"; the rest are reasons the posting is not there.
GONE = "gone"
LOGIN = "login"

_LOCALE = re.compile(r"^[a-z]{2}([-_][a-z]{2})?$", re.IGNORECASE)

# Path segments that name a *collection* of jobs rather than one job. A path
# made of nothing but these is an index however deep it goes: `/en/careers`,
# `/jobs/search`, `/careers/students`.
_INDEX_SEGMENTS = frozenset(
    """
    careers career carriere carrieres carrieres-emplois
    jobs job joblist job-list joboffers job-offers offers
    emploi emplois offre offres offres-emploi recrutement recrutements
    recruitment recruiting recrute nous-rejoindre rejoignez-nous
    join-us joinus work-with-us workwithus we-are-hiring hiring
    vacancies openings opportunities positions roles
    students student campus graduates graduate internships stages
    talent talents apply applications
    search results result all list browse find explore index home
    """.split()
)

# Segments that say the destination is an error page rather than a posting.
_ERROR_SEGMENTS = frozenset(
    """
    error errorpage error-page 404 not-found notfound nomatch no-match
    expired closed gone job-not-found jobnotfound no-longer-available
    """.split()
)

# Segments that say the destination is a login wall. Kept apart from the error
# set on purpose: a login wall means "we cannot see it", not "it is not there".
_LOGIN_SEGMENTS = frozenset(
    """
    login signin sign-in sign_in signup register auth authenticate authwall
    checkpoint sso session uas
    """.split()
)

# Domains whose posting URLs have a shape worth enforcing. Anything else on
# these hosts is a board landing page or a company profile — which is exactly
# what a model produces when it assembles a URL instead of copying one.
_ATS_SHAPES: tuple[tuple[re.Pattern[str], re.Pattern[str], str], ...] = (
    (
        re.compile(r"(^|\.)greenhouse\.io$"),
        re.compile(r"^/[^/]+/jobs/\d+"),
        "boards.greenhouse.io/<company>/jobs/<id>",
    ),
    (
        re.compile(r"(^|\.)lever\.co$"),
        re.compile(r"^/[^/]+/[0-9a-f]{8}-[0-9a-f-]+"),
        "jobs.lever.co/<company>/<uuid>",
    ),
    (
        re.compile(r"(^|\.)ashbyhq\.com$"),
        re.compile(r"^/[^/]+/[0-9a-f]{8}-[0-9a-f-]+"),
        "jobs.ashbyhq.com/<company>/<uuid>",
    ),
    (
        re.compile(r"(^|\.)smartrecruiters\.com$"),
        re.compile(r"^/[^/]+/\d{6,}"),
        "jobs.smartrecruiters.com/<Company>/<id>-<slug>",
    ),
    (
        re.compile(r"(^|\.)workable\.com$"),
        re.compile(r"^/[^/]+/j/[0-9A-F]{6,}"),
        "apply.workable.com/<company>/j/<hash>/",
    ),
    (
        re.compile(r"(^|\.)recruitee\.com$"),
        re.compile(r"^/o/[^/]+"),
        "<company>.recruitee.com/o/<slug>",
    ),
    (
        re.compile(r"(^|\.)teamtailor\.com$"),
        re.compile(r"^/jobs/\d+"),
        "<company>.teamtailor.com/jobs/<id>-<slug>",
    ),
    (
        re.compile(r"(^|\.)myworkdayjobs\.com$"),
        re.compile(r"/job/"),
        "<company>.myworkdayjobs.com/<site>/job/<location>/<title>_<req>",
    ),
    (
        re.compile(r"^jobs\.sap\.com$"),
        re.compile(r"^/job/[^/]+/\d+"),
        "jobs.sap.com/job/<slug>/<id>/",
    ),
)


@dataclass(frozen=True)
class LinkVerdict:
    """What a URL is, and a sentence saying why — for the log and the UI."""

    kind: str
    reason: str = ""

    def __bool__(self) -> bool:
        return self.kind == POSTING


def _segments(path: str) -> list[str]:
    """Path segments, lowercased, with leading locale segments dropped."""
    parts = [part.lower() for part in path.split("/") if part]
    while parts and _LOCALE.match(parts[0]):
        parts.pop(0)
    return parts


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def _ats_shape(host: str) -> tuple[re.Pattern[str], str] | None:
    for host_pattern, path_pattern, shape in _ATS_SHAPES:
        if host_pattern.search(host):
            return path_pattern, shape
    return None


def _platform_shape(host: str) -> tuple[re.Pattern[str], str] | None:
    """The declared posting shape of a known board serving this host.

    Subdomains count: Welcome to the Jungle white-labels employer boards onto
    `<company>.welcomekit.co`, and those carry the same URL shape. A platform's
    `domains` entry may include a path (`linkedin.com/jobs`); only the host part
    selects the platform, and the path is left to the pattern.
    """
    for platform in PLATFORMS.values():
        for domain in platform.domains:
            domain_host = domain.split("/", 1)[0].lower()
            if host == domain_host or host.endswith(f".{domain_host}"):
                return platform.posting_path, platform.url_shape
    return None


def classify(url: str) -> LinkVerdict:
    """Judge a URL on its shape alone. No network."""
    url = (url or "").strip()
    if not url:
        return LinkVerdict(MISSING, "the posting came back with no link at all")

    try:
        parsed = urlparse(url)
    except ValueError:
        return LinkVerdict(MISSING, f"{url!r} is not a URL")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return LinkVerdict(MISSING, f"{url!r} is not an http(s) URL")

    # A grounding redirect hides the site it points at, so every judgement
    # below would be about Google rather than about the posting — and the link
    # itself expires within weeks of the run that found it. `services/flows.py`
    # resolves these before a run reaches here, so one still wearing its
    # redirect is one that could not be followed.
    if is_grounding_redirect(url):
        return LinkVerdict(
            REDIRECT,
            "this is a Google search redirect rather than the posting's own link — "
            "it hides the site it opens and stops working after a few weeks",
        )

    host = _host(url)
    path = parsed.path or "/"
    known = _platform_shape(host) or _ats_shape(host)
    if known is not None:
        pattern, shape = known
        # LinkedIn's domain entry carries a path (`linkedin.com/jobs`), so match
        # the pattern anywhere in the path rather than anchoring every shape.
        if not pattern.search(path):
            return LinkVerdict(
                INDEX, f"{host} postings live at `{shape}` — this is not one of them"
            )
        return LinkVerdict(POSTING)

    segments = _segments(path)
    if not segments:
        return LinkVerdict(INDEX, "this is a site root, not a posting")
    if all(segment in _INDEX_SEGMENTS for segment in segments):
        return LinkVerdict(INDEX, "this is a careers or job-search page, not one posting")
    return LinkVerdict(POSTING)


def is_openable(url: str) -> bool:
    """Whether this URL, by its shape, opens one specific posting."""
    return classify(url).kind == POSTING


def site_name(url: str) -> str:
    """What to call the site a link is on — a board's own name, or its host.

    `source` is a field the candidate reads and the feedback digest counts by,
    so "Welcome to the Jungle" beats `welcometothejungle.com` and both beat the
    empty string a model leaves when it does not recognise the site. The
    pasted-link path fills it from here when the Reader left it blank.
    """
    host = _host(url)
    if not host:
        return ""
    for platform in PLATFORMS.values():
        for domain in platform.domains:
            domain_host = domain.split("/", 1)[0].lower()
            if host == domain_host or host.endswith(f".{domain_host}"):
                return platform.label
    return host


def _redirected_upward(url: str, final_url: str) -> bool:
    """True when the redirect climbed the same site's tree, e.g. /careers/job/7 → /careers."""
    if _host(url) != _host(final_url):
        return False
    before, after = _segments(urlparse(url).path), _segments(urlparse(final_url).path)
    return len(after) < len(before) and before[: len(after)] == after


def landing(url: str, final_url: str) -> LinkVerdict:
    """Judge where the redirects settled.

    `POSTING` means the destination gives no reason to doubt the link. The
    other kinds each mean the posting is not at the end of it — for a different
    reason, which is why they are not one flag.
    """
    if not final_url or final_url == url:
        return LinkVerdict(POSTING)

    destination = _segments(urlparse(final_url).path)
    if any(segment in _LOGIN_SEGMENTS for segment in destination):
        return LinkVerdict(LOGIN, f"the link redirects to a sign-in page ({final_url})")
    if any(segment in _ERROR_SEGMENTS for segment in destination):
        return LinkVerdict(GONE, f"the link redirects to an error page ({final_url})")

    arrival = classify(final_url)
    if arrival.kind != POSTING and classify(url).kind == POSTING:
        return LinkVerdict(INDEX, f"the link redirects to {final_url}, which is not the posting")
    if _redirected_upward(url, final_url):
        return LinkVerdict(INDEX, f"the link redirects up to {final_url}, which is not the posting")
    return LinkVerdict(POSTING)


def partition(jobs: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Split ranked postings into the openable ones and a tally of the rest.

    Shape only — this runs before verification, so a posting that cannot be
    opened never costs an HTTP request and never reaches the user.
    """
    kept: list[dict] = []
    dropped: dict[str, int] = {}
    for job in jobs:
        verdict = classify(str(job.get("url", "")))
        if verdict.kind == POSTING:
            kept.append(job)
        else:
            dropped[verdict.kind] = dropped.get(verdict.kind, 0) + 1
    return kept, dropped


def headline(html: str) -> str:
    """A page's title and first heading, tags stripped — what it calls itself."""
    parts = []
    for tag in ("title", "h1"):
        match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.IGNORECASE | re.DOTALL)
        if match:
            parts.append(re.sub(r"<[^>]+>", " ", match.group(1)))
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def headline_says_gone(text: str) -> LinkVerdict | None:
    """Whether a page's own title admits the posting is not there.

    Given the rendered title and heading rather than HTML — the HTTP checker
    passes `headline(body)`, the browser checker passes what Chromium rendered.
    """
    lowered = (text or "").lower()
    for marker in GONE_MARKERS:
        if marker in lowered:
            return LinkVerdict(GONE, f"the page it opens is titled {text.strip()[:70]!r}")
    return None
