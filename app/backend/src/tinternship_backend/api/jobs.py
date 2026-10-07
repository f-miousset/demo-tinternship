"""Job discovery and browsing."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import col, select

from ..agents.investigator import MAX_RESULTS, MIN_RESULTS
from ..db.engine import session_scope
from ..db.models import Application, JobPosting, utcnow
from ..services import flows, recency, search_history, trash
from ..services.context_blocks import SearchFocus
from ..tools.job_sources.registry import source_names
from .sse import sse_response

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def serialise_job(job: JobPosting, application_id: int | None = None) -> dict[str, Any]:
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "remote": job.remote,
        "url": job.url,
        "apply_url": job.apply_url,
        "source": job.source,
        "description": job.description,
        "summary": job.summary,
        "requirements": job.requirements,
        "nice_to_have": job.nice_to_have,
        "contract_type": job.contract_type,
        "start_date": job.start_date,
        "duration": job.duration,
        "compensation": job.compensation,
        "language": job.language,
        "posted_at": job.posted_at,
        "posted_on": job.posted_on,
        # Recomputed on every read rather than stored: a posting saved three
        # weeks ago is three weeks older than it was, and a cached age would
        # still be telling the candidate it went up yesterday.
        "posted_days_ago": recency.age_days(job.posted_on or job.posted_at),
        "deadline": job.deadline,
        "fit_score": job.fit_score,
        "fit_rationale": job.fit_rationale,
        "strengths": job.strengths,
        "risks": job.risks,
        "keywords": job.keywords,
        "confidence": job.confidence,
        "url_status": job.url_status,
        "url_http_status": job.url_http_status,
        "dismissed": job.dismissed,
        "deferred_at": job.deferred_at.isoformat() if job.deferred_at else None,
        "run_id": job.run_id,
        "invocation_id": job.invocation_id,
        "discovered_at": job.discovered_at.isoformat(),
        "application_id": application_id,
    }


# What each surface of the Jobs page is asking for. Defined once here rather
# than assembled from booleans at the call site, because "which postings does
# the deck show" is one rule and three flags would let two callers disagree
# about it.
JOB_VIEWS = ("deck", "discarded", "all")


@router.get("")
def list_jobs(
    view: str = Query(
        default="deck",
        description=(
            "deck — undecided postings, the swipe deck's queue. "
            "discarded — the trash. all — everything, answered included."
        ),
    ),
    limit: int = 200,
):
    if view not in JOB_VIEWS:
        raise HTTPException(status_code=400, detail=f"Unknown view {view!r}")

    with session_scope() as session:
        # Every application, trashed ones included. Throwing a tracked posting
        # away is a verdict on it, not an undo of the swipe that saved it — so
        # it must not reappear in the deck to be asked about a third time. The
        # trash it belongs to is the Tracker's, and that is where it comes back
        # from. See `documentation/triage.md`.
        applications = {
            application.job_posting_id: application.id
            for application in session.exec(select(Application)).all()
        }
        # A posting deleted forever is a tombstone, kept only so it stays
        # answered (`services/trash.py`) — never something to show.
        statement = (
            select(JobPosting)
            .where(col(JobPosting.purged_at).is_(None))
            .order_by(JobPosting.fit_score.desc())
        )
        if view == "deck":
            statement = statement.where(JobPosting.dismissed == False)  # noqa: E712
        elif view == "discarded":
            statement = statement.where(JobPosting.dismissed == True)  # noqa: E712
        jobs = session.exec(statement.limit(limit)).all()
        serialised = [
            serialise_job(job, applications.get(job.id))
            for job in jobs
            # A posting the candidate validated is on the Tracker, and the deck
            # only holds what is still undecided. Filtered here rather than in
            # SQL because the application lookup already happened above.
            if not (view == "deck" and job.id in applications)
        ]

    # SQL picks the rows; Python picks the order. The ordering key depends on
    # how old each posting is *today*, which SQLite cannot express over a text
    # date column — and the page reads top-down, so this is the ordering the
    # candidate actually experiences. Two hundred rows sort in microseconds.
    def by_match(job: dict[str, Any]) -> tuple[float, float]:
        return (
            recency.score(job["fit_score"], job["posted_days_ago"]),
            job["fit_score"],
        )

    # "Not now" means exactly that: a deferred posting goes behind every posting
    # that has not been swiped on, and the one deferred longest ago comes back
    # first. Two sorted lists concatenated rather than a flag folded into the
    # key, because the second list is ordered by something the first one does
    # not have.
    waiting = [job for job in serialised if not job["deferred_at"]]
    deferred = [job for job in serialised if job["deferred_at"]]
    waiting.sort(key=by_match, reverse=True)
    deferred.sort(key=lambda job: job["deferred_at"])
    return {"jobs": waiting + deferred, "sources": source_names()}


@router.get("/{job_id}")
def get_job(job_id: int):
    with session_scope() as session:
        job = session.get(JobPosting, job_id)
        if job is None or job.purged_at is not None:
            raise HTTPException(status_code=404, detail=f"No job {job_id}")
        application = session.exec(
            select(Application).where(Application.job_posting_id == job_id)
        ).first()
        return serialise_job(job, application.id if application else None)


class SearchRequest(BaseModel):
    """What the candidate typed into the Jobs chat, when they used it.

    The whole body is optional and so is every field in it: the "Run
    Investigator" button posts nothing at all, and a blank `focus` is the same
    unsteered run. `earlier` is the conversation so far, oldest first — context
    for resolving a follow-up like "and also in Berlin", never a second request.
    """

    focus: str = ""
    earlier: list[str] = []


@router.post("/search")
def search(
    target_results: int | None = Query(
        default=None,
        ge=MIN_RESULTS,
        le=MAX_RESULTS,
        description="How many ranked postings to come back with. Defaults to RESULTS_PER_RUN.",
    ),
    body: SearchRequest | None = None,
):
    """Stream the full Investigator pipeline: discover → normalise → rank → persist.

    Server-sent events rather than one long JSON response. The run takes minutes,
    and a proxy that sees no bytes for 100 seconds kills the request (Cloudflare
    answers 524) while the work carries on here — reporting a failure that never
    happened, over results that were already saved.
    """
    if body and body.focus and body.focus.strip():
        search_history.record_query(body.focus)
    focus = SearchFocus.of(body.focus, body.earlier) if body else None
    return sse_response(
        flows.investigator_stream(target_results=target_results, focus=focus)
    )


@router.get("/search/history")
def get_search_history(limit: int = 50):
    """List sent search query history for the current account, freshest first."""
    items = search_history.list_history(limit=limit)
    return {"items": [search_history.serialise_query(item) for item in items]}


class AddHistoryRequest(BaseModel):
    text: str


@router.post("/search/history")
def add_search_history(body: AddHistoryRequest):
    """Add a search query to history, deduplicating case-insensitively."""
    item = search_history.record_query(body.text)
    if not item:
        raise HTTPException(status_code=400, detail="Query text cannot be empty")
    return search_history.serialise_query(item)


class SyncHistoryItem(BaseModel):
    text: str
    timestamp: int | None = None


class SyncHistoryRequest(BaseModel):
    items: list[SyncHistoryItem]


@router.post("/search/history/sync")
def sync_search_history(body: SyncHistoryRequest):
    """Batch-import or sync queries into the account's search history."""
    from datetime import UTC, datetime

    for item in body.items:
        ts = (
            datetime.fromtimestamp(item.timestamp / 1000.0, UTC)
            if item.timestamp
            else None
        )
        search_history.record_query(item.text, created_at=ts, updated_at=ts)
    all_items = search_history.list_history()
    return {"items": [search_history.serialise_query(i) for i in all_items]}


@router.delete("/search/history/{query_id}")
def delete_search_history_item(query_id: int):
    """Remove one search query from history."""
    deleted = search_history.delete_query(query_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No query with id {query_id}")
    return {"deleted": True, "id": str(query_id)}


@router.delete("/search/history")
def clear_search_history():
    """Clear all search query history for this account."""
    count = search_history.clear_history()
    return {"deleted_count": count}


class ImportLink(BaseModel):
    url: str


@router.post("/import")
def import_link(body: ImportLink):
    """Stream the pasted-link pipeline: fetch → read → score → verify → persist.

    The other way onto this list. A posting the candidate found themselves goes
    through the same ending as a discovered one — link-checked, scored on the
    same scale, saved as a `JobPosting` — so applying, the tracker and the
    follow-up sweep work on it without knowing where it came from.

    Server-sent events for the same reason `/search` is: a fetch, a browser
    fallback and two model calls comfortably outlast the 100 seconds a silent
    proxied request gets.
    """
    return sse_response(flows.import_link_stream(body.url))


class ImportText(BaseModel):
    text: str


@router.post("/import-text")
def import_text(body: ImportText):
    """Stream the pasted-text pipeline: read → score → check any link → persist.

    The third way onto this list, and the one that works when the other two
    cannot: a posting that arrived as an email, a PDF or a message, or one on a
    board whose bot protection beats both our HTTP client and the browser. The
    candidate has the posting; this is how it gets in.

    Ends where the other two end — scored on the same scale, saved as a
    `JobPosting` — with one difference: the row may have no link at all, because
    pasted text is the one case where the candidate already holds the posting.
    Any URL the text *does* name is proved like every other link before it is
    kept. See `services/flows.py::import_text_stream`.

    Server-sent events for the same reason: two model calls and an audit
    outlast the 100 seconds a silent proxied request gets.
    """
    return sse_response(flows.import_text_stream(body.text))


@router.post("/{job_id}/defer")
def defer(job_id: int):
    """Send a posting to the back of the deck — the undecided swipe.

    Stamped rather than flagged so the deck can bring the longest-deferred
    posting back first, and written down rather than kept in the browser so a
    reload does not undo the swipe.
    """
    with session_scope() as session:
        job = session.get(JobPosting, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"No job {job_id}")
        job.deferred_at = utcnow()
        session.add(job)
        return {"id": job_id, "deferred_at": job.deferred_at.isoformat()}


@router.post("/{job_id}/dismiss")
def dismiss(job_id: int, dismissed: bool = True):
    with session_scope() as session:
        job = session.get(JobPosting, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"No job {job_id}")
        job.dismissed = dismissed
        session.add(job)
        return {"id": job_id, "dismissed": dismissed}


# Declared before `/{job_id}` so "trash" is never read as an id.
@router.delete("/trash")
def empty_trash():
    """Delete every posting in the deck's trash, forever. See `services/trash.py`."""
    return trash.empty_deck_trash()


@router.delete("/{job_id}")
def delete_job(job_id: int):
    """Delete one posting in the deck's trash, forever.

    409 for a posting that is not in the trash: deleting is the step past
    discarding, never a substitute for it. What survives is a tombstone that
    keeps the posting answered — see `services/trash.py`.
    """
    try:
        return trash.delete_job(job_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except trash.NotInTrash as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
