"""Function tools that let agents write their results to the database."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse

from sqlmodel import select

from ..db.engine import session_scope
from ..db.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    JobPosting,
    utcnow,
)
from ..observability.context import current_run

logger = logging.getLogger(__name__)

# `url_status` values meaning the link does not reach the posting. The same set
# as `services/verification.UNUSABLE`, spelled out rather than imported so the
# persistence layer keeps its back to the service layer; `test_persistence.py`
# fails if the two ever disagree.
UNUSABLE_LINK = frozenset({"dead", "index"})

_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
# Titles vary far more than the role does; strip the noise before comparing.
# Applied *after* `_normalise`, so punctuation is already spaces — which is why
# the gender markers are written "h f" rather than "h/f".
_TITLE_NOISE = re.compile(
    r"\b(intern|internship|stage|stagiaire|alternance|apprenti\w*|praktikum|tirocinio|"
    r"h f|f h|m w d|w m d|20\d\d|summer|winter|spring|fall|automne|printemps|ete)\b"
)


def _normalise(text: str) -> str:
    text = _NON_ALNUM.sub(" ", (text or "").lower())
    return _WHITESPACE.sub(" ", text).strip()


def dedupe_key(title: str, company: str, url: str) -> str:
    """Stable identity for a posting.

    Aggregators re-host the same job under different URLs, and the same role is
    posted with slightly different titles, so identity is (company, de-noised
    title, url host) rather than the URL alone.
    """
    company_key = _normalise(company)
    title_key = _WHITESPACE.sub(" ", _TITLE_NOISE.sub(" ", _normalise(title))).strip()
    host = ""
    if url:
        try:
            host = (urlparse(url).hostname or "").removeprefix("www.")
        except ValueError:
            host = ""
    # A posting with no company name falls back to the host so unrelated
    # postings do not all collapse into one row.
    basis = f"{company_key or host}|{title_key}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:20]


# Words that carry no signal about *which* role this is.
_STOPWORDS = frozenset(
    "the a an de du des la le les et and or for in at of ingenieur engineer "
    "engineering junior senior open".split()
)


def title_tokens(title: str) -> frozenset[str]:
    cleaned = _WHITESPACE.sub(" ", _TITLE_NOISE.sub(" ", _normalise(title))).strip()
    return frozenset(t for t in cleaned.split() if t and t not in _STOPWORDS)


def same_role(title_a: str, title_b: str, threshold: float = 0.6) -> bool:
    """Fuzzy title match, for postings the exact dedupe key misses.

    The hash key requires identical de-noised titles, so the same LightOn role
    listed once as "Open Machine Learning Intern" and once as "Open Machine
    Learning Intern / Stage Machine Learning" produced two cards. Comparing
    token sets catches that: both de-noise to `{machine, learning}`.

    The overlap is measured against the **larger** set, which is the whole
    safety of this function. Until 2026-08-26 it was measured against the
    smaller one, on the theory that an appended translation should still match
    the short form — but that made every token of a short title a wildcard.
    `{ai}` matched `{ai, research}` at 100%, so "AI Intern" and "AI Research
    Intern" at one company were one posting, and merging is destructive: the
    match hands back the older row and the newer posting overwrites it in place.
    Re-running the Investigator therefore *replaced* postings the candidate
    already had, which is the opposite of what a second run is for.

    The cost of the stricter rule is a second card when a re-listing genuinely
    adds tokens ("… / Stagiaire Science des Données"). That is the right way to
    be wrong: a duplicate is a row the candidate can dismiss in one click, a bad
    merge is a posting they never learn existed.
    """
    a, b = title_tokens(title_a), title_tokens(title_b)
    if not a or not b:
        return False
    return len(a & b) / max(len(a), len(b)) >= threshold


def _find_similar(session, company: str, title: str) -> JobPosting | None:
    company_key = _normalise(company)
    if not company_key:
        return None
    for candidate in session.exec(select(JobPosting)).all():
        if _normalise(candidate.company) != company_key:
            continue
        if same_role(candidate.title, title):
            return candidate
    return None


def find_existing(session, title: str, company: str, url: str) -> JobPosting | None:
    """The row this posting would land on, or None if it is genuinely new.

    Exact `dedupe_key` first, then the fuzzy same-company/same-role fallback,
    because the hash misses re-listings that merely add tokens to a title.

    Extracted so `save_job_postings` and `partition_answered` cannot drift:
    a filter that decided a posting was new while the writer decided it was an
    update would drop postings on the floor, and the two answers have to be the
    same answer.
    """
    existing = session.exec(
        select(JobPosting).where(JobPosting.dedupe_key == dedupe_key(title, company, url))
    ).first()
    if existing is None:
        existing = _find_similar(session, company, title)
    return existing


# Query parameters that say where a click came from, never which posting it is.
# Everything else in a query is kept: Indeed's `jk=` *is* the posting.
_TRACKING_PARAM = re.compile(
    r"^(utm_\w+|ref|refid|ref_\w+|trk|trkinfo|trackingid|tracking_id|src|"
    r"gclid|fbclid|msclkid|lipi|originalsubdomain)$",
    re.IGNORECASE,
)


def posting_address(url: str) -> str:
    """A posting URL with everything that does not identify the posting removed.

    Scheme, `www.`, a trailing slash, the fragment and tracking parameters all
    vary between two copies of one link; the host, the path and any remaining
    query are what tell two postings apart. Empty for an empty or unparseable URL.
    """
    url = (url or "").strip()
    if not url:
        return ""
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host:
        return ""
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=False)
            if not _TRACKING_PARAM.match(key)
        )
    )
    address = f"{host}{parsed.path.rstrip('/')}"
    return f"{address}?{query}" if query else address


def paste_key(url: str, text: str = "") -> str:
    """The identity of a **pasted** posting: its link, or failing that its text.

    A search run identifies a posting by company and de-noised title, because
    the same role reaches it re-hosted on three boards. A paste cannot use that
    rule, and using it was a measured failure (2026-10-06): two postings at one
    company with near-identical titles — "Stage Data Scientist H/F" for two
    teams, "Data Science Intern — Paris" and "— Lyon" — are one row to
    `find_existing`, so the second paste *overwrote* the first, application and
    all, and the candidate was told it was "already saved". The candidate is
    pasting a specific posting; the link they pasted, or the words they pasted
    when there is no link, is the only identity that cannot conflate two.

    The cost is a second row when the same role is pasted once as a link and
    once as text, which is the cheap way to be wrong — see `same_role`.
    """
    address = posting_address(url)
    basis = f"url|{address}" if address else f"text|{_normalise(text)}"
    return "paste-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:20]


def find_pasted(session, key: str, url: str) -> JobPosting | None:
    """The row a pasted posting is *the same posting as*, or None.

    By `paste_key` first — a posting pasted before — then by link, which is how
    a paste finds the row a search run already saved for the very same URL.
    Never by title: that is the whole point of `paste_key`.
    """
    existing = session.exec(select(JobPosting).where(JobPosting.dedupe_key == key)).first()
    if existing is not None:
        return existing
    address = posting_address(url)
    if not address:
        return None
    for candidate in session.exec(select(JobPosting).where(JobPosting.url != "")).all():
        if posting_address(candidate.url) == address:
            return candidate
    return None


def track_posting(
    session, job_id: int, *, note: str, pinned: bool = False, language: str = ""
) -> tuple[Application, bool]:
    """Put a posting on the Tracker — the write behind saying yes to one.

    There are two ways to say yes now, and they have to produce the same row.
    The deck swipe is one: `POST /api/applications` from a right or an up swipe.
    Pasting a posting is the other — the candidate went and found this one, so
    the app takes that as the yes and does not ask again
    (`services/flows.py::_track_posting`). Two call sites assembling their own
    `Application` would drift, and a pasted posting would land on the board in a
    state no swipe can produce: no first event, or a status the Tracker's
    columns do not expect.

    Takes the caller's `session` rather than opening its own, because both
    callers have more to do in the same transaction — the endpoint serialises
    the row it gets back, the flow reports its id.

    Idempotent, and **an application already there comes out of the Tracker's
    trash**: validating a posting is a statement about it, not a duplicate call,
    and the same reasoning that lets a paste overrule a dismissal applies to an
    application the candidate threw away. `pinned` only ever goes on — a swipe
    up on something already tracked is "and this one first", never the reverse.

    `language` is the package language this application opens on, guessed from
    the posting by `services/language_check.posting_language` — you answer a
    posting in the language it was advertised in. It is set **on creation only**:
    an application that already exists may have been generated in a language the
    candidate chose by hand, and a re-guess would quietly overwrite that. The
    caller decides it rather than this function, because `tools/` does not import
    from `services/`; both call sites use the same function so they cannot
    disagree about it. Empty falls through to the column default.

    Returns `(application, created)`.
    """
    existing = session.exec(
        select(Application).where(Application.job_posting_id == job_id)
    ).first()
    if existing is not None:
        if pinned and not existing.pinned:
            existing.pinned = True
            existing.updated_at = utcnow()
            session.add(existing)
        if existing.trashed_at is not None:
            existing.trashed_at = None
            session.add(existing)
        session.flush()
        return existing, False

    application = Application(job_posting_id=job_id, pinned=pinned)
    if language:
        application.language = language
    session.add(application)
    session.flush()
    session.add(
        ApplicationEvent(
            application_id=application.id,
            to_status=ApplicationStatus.SAVED,
            note=note,
        )
    )
    session.flush()
    return application, True


def partition_answered(jobs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Split a ranked list into the postings still worth showing, and the answered ones.

    A posting the candidate dismissed, already turned into an application, or
    tracked and then threw away has been **answered**. Re-proposing it is worse
    than a duplicate: a dismissal is a verdict, an application is already on the
    Tracker, and one in the Tracker's trash is a verdict reached *after* they
    looked properly — so any of the three coming back means the run spent a slot
    re-asking a question that was settled.

    The three are tallied apart because they are three different answers, and
    the tally is what the Jobs page reports. In particular a trashed application
    is not an `applied` drop: calling it one would tell the candidate a run
    re-found something they are tracking, when they are not.

    `services/context_blocks.known_postings_block` asks three of the four agents
    not to return these. This is the promise behind that request — a prompt is a
    request, and a promise lives in Python. It is shaped like
    `services/job_links.partition` and called next to it for the same reason:
    dropping here, before the cut, frees the slot for one of the spares the
    matcher was asked for.

    Returns `(kept, drops)` where `drops` tallies by reason.
    """
    kept: list[dict[str, Any]] = []
    drops: dict[str, int] = {}
    if not jobs:
        return kept, drops

    with session_scope() as session:
        # Trashed applications are read here too, and that is the point: the
        # row still exists, so the posting behind it is still answered.
        applications = session.exec(select(Application)).all()
        applied_to = {application.job_posting_id for application in applications}
        thrown_away = {
            application.job_posting_id
            for application in applications
            if application.trashed_at is not None
        }
        for job in jobs:
            if not isinstance(job, dict):
                continue
            existing = find_existing(
                session,
                str(job.get("title", "")).strip(),
                str(job.get("company", "")).strip(),
                str(job.get("url", "")).strip(),
            )
            if existing is None:
                kept.append(job)
                continue
            if existing.dismissed:
                drops["dismissed"] = drops.get("dismissed", 0) + 1
                continue
            if existing.id in thrown_away:
                drops["trashed"] = drops.get("trashed", 0) + 1
                continue
            if existing.id in applied_to:
                drops["applied"] = drops.get("applied", 0) + 1
                continue
            # Already on the list, un-answered: still a legitimate result. It
            # updates its own row, which is how a re-found posting gets a fresh
            # score and a fresh link check.
            kept.append(job)

    return kept, drops


def _coerce_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def save_job_postings(
    jobs: list[dict[str, Any]], *, allow_missing_url: bool = False, pasted_as: str = ""
) -> dict[str, Any]:
    """Persist the ranked job postings so the user can browse them.

    Call this once, at the very end of ranking, with the complete ranked list.

    Args:
        jobs: The ranked postings. Each item must carry `title` and `url` — a
            posting with no link is skipped — plus `company` and the ranking
            fields `fit_score`, `fit_rationale`, `strengths`, `risks`,
            `keywords` and `confidence`.
        allow_missing_url: Save a posting that has no link at all. **Off by
            default and only ever turned on by `flows.import_text_stream`**,
            because for every other path a posting with no URL is a lead the
            candidate cannot read, check or apply to — a card that looks like
            the others and is worth nothing. Pasted text is the one case where
            they already have the posting: the text *is* it, and refusing to
            save it would throw away the thing they just gave us. A link the
            text happens to name is still fetched and proved like any other
            before it reaches here.
        pasted_as: The `paste_key` of the one posting being saved, set only by
            the two paste paths. It replaces the company-and-title match with
            `find_pasted`, so a paste updates only the posting it *is* — never
            a different role at the same company whose title happens to look
            alike — and becomes the new row's `dedupe_key`.

    Returns:
        A dict with counts of how many postings were created, updated and
        skipped for having no link.
    """
    run = current_run()
    created = 0
    updated = 0
    skipped = 0

    try:
        with session_scope() as session:
            for job in jobs or []:
                if not isinstance(job, dict):
                    continue
                title = str(job.get("title", "")).strip()
                company = str(job.get("company", "")).strip()
                url = str(job.get("url", "")).strip()
                # A posting with no link is not something the user can act on:
                # they cannot read it, cannot check it and cannot apply to it.
                # `services/job_links.py` drops these upstream; this is the
                # backstop, because the card is worse than the missing row.
                # The exemption is pasted text, where the candidate supplied the
                # posting itself and a missing link costs them nothing they had.
                if not title or (not url and not allow_missing_url):
                    skipped += 1
                    continue

                # Same for a link that does not reach the posting. The run drops
                # these too, so reaching here means something else called us —
                # and a 404 that got in once stays on the Jobs page forever.
                broken_link = str(job.get("url_status", "")) in UNUSABLE_LINK

                if pasted_as:
                    key = pasted_as
                    existing = find_pasted(session, pasted_as, url)
                else:
                    key = dedupe_key(title, company, url)
                    existing = find_existing(session, title, company, url)

                if broken_link and existing is None:
                    skipped += 1
                    continue

                posting = existing or JobPosting(dedupe_key=key, title=title, company=company)

                posting.title = title
                posting.company = company
                posting.location = str(job.get("location", ""))
                posting.remote = str(job.get("remote", "unknown"))
                posting.url = url
                posting.apply_url = str(job.get("apply_url", "") or url)
                posting.source = str(job.get("source", ""))
                posting.description = str(job.get("description", ""))
                posting.summary = str(job.get("summary", ""))
                posting.requirements = _coerce_list(job.get("requirements"))
                posting.nice_to_have = _coerce_list(job.get("nice_to_have"))
                posting.contract_type = str(job.get("contract_type", ""))
                posting.start_date = str(job.get("start_date", ""))
                posting.duration = str(job.get("duration", ""))
                posting.compensation = str(job.get("compensation", ""))
                posting.language = str(job.get("language", ""))
                posting.posted_at = str(job.get("posted_at", ""))
                # The ISO form `services/recency.py` parsed out of `posted_at`,
                # taken from the caller rather than re-derived here — same
                # reason as `UNUSABLE_LINK` above, this layer keeps its back to
                # the service layer. A run always annotates before saving; a
                # posting that arrives without it sorts as undated, which is
                # what an unparseable date means anyway.
                posting.posted_on = str(job.get("posted_on", ""))
                posting.deadline = str(job.get("deadline", ""))
                posting.fit_score = float(job.get("fit_score", 0) or 0)
                posting.fit_rationale = str(job.get("fit_rationale", ""))
                posting.strengths = _coerce_list(job.get("strengths"))
                posting.risks = _coerce_list(job.get("risks"))
                posting.keywords = _coerce_list(job.get("keywords"))
                posting.confidence = str(job.get("confidence", "medium"))
                posting.url_status = str(job.get("url_status", "unchecked"))
                posting.url_http_status = int(job.get("url_http_status", 0) or 0)
                if broken_link:
                    # A posting already on the page whose link has since broken.
                    # Dismissing rather than deleting keeps it one toggle away,
                    # and keeps this out of the business of destroying rows.
                    posting.dismissed = True
                if run is not None:
                    posting.run_id = run.run_id
                    posting.invocation_id = run.invocation_id

                session.add(posting)
                if existing:
                    updated += 1
                else:
                    created += 1
    except Exception as exc:
        logger.exception("save_job_postings failed")
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}", "saved": 0}

    if skipped:
        logger.warning("Skipped %s posting(s) with no title or no link", skipped)

    return {
        "status": "ok",
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "saved": created + updated,
    }
