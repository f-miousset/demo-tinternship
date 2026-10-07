"""Turns application outcomes into the digest that steers the next search."""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from sqlmodel import col, select

from ..agents.feedback_agent import DIGEST_STATE_KEY, build_feedback_analyst
from ..agents.runtime import execute, user_message
from ..db.engine import session_scope
from ..db.models import (
    INTERVIEW_STATUSES,
    Application,
    ApplicationEvent,
    ApplicationStatus,
    JobPosting,
)

logger = logging.getLogger(__name__)

# Statuses that mean the application actually went somewhere.
_POSITIVE = {*INTERVIEW_STATUSES, ApplicationStatus.OFFER}
_NEGATIVE = {ApplicationStatus.REJECTED, ApplicationStatus.GHOSTED}


def collect_history() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Everything the analyst needs: per-application outcomes plus the tallies.

    Applications in the Tracker's trash are left out. The digest is a reading of
    what happens to applications the candidate is actually pursuing — the
    response rate, the fit scores that got answers — and a trashed one has no
    outcome to contribute: its status froze wherever it was when they walked
    away, so counting it would only dilute both denominators with a question
    nobody asked the employer. Dismissed postings are already absent for the
    same reason, having never become applications at all.
    """
    history: list[dict[str, Any]] = []
    with session_scope() as session:
        applications = session.exec(
            select(Application)
            .where(col(Application.trashed_at).is_(None))
            .order_by(Application.created_at)
        ).all()
        for application in applications:
            job = session.get(JobPosting, application.job_posting_id)
            events = session.exec(
                select(ApplicationEvent)
                .where(ApplicationEvent.application_id == application.id)
                .order_by(ApplicationEvent.created_at)
            ).all()
            history.append(
                {
                    "company": job.company if job else "",
                    "title": job.title if job else "",
                    "location": job.location if job else "",
                    "source": job.source if job else "",
                    "contract_type": job.contract_type if job else "",
                    "fit_score": job.fit_score if job else 0,
                    "status": application.status,
                    "notes": application.notes,
                    "timeline": [
                        {
                            "to": event.to_status,
                            "note": event.note,
                            "at": event.created_at.isoformat(),
                        }
                        for event in events
                    ],
                }
            )

    status_counts = Counter(item["status"] for item in history)
    applied = [item for item in history if item["status"] != ApplicationStatus.SAVED]
    positive = [item for item in history if item["status"] in _POSITIVE]
    negative = [item for item in history if item["status"] in _NEGATIVE]

    stats = {
        "total_tracked": len(history),
        "total_applied": len(applied),
        "status_counts": dict(status_counts),
        "response_rate": round(len(positive) / len(applied), 3) if applied else 0.0,
        "mean_fit_score_positive": (
            round(sum(i["fit_score"] for i in positive) / len(positive), 2) if positive else 0.0
        ),
        "mean_fit_score_negative": (
            round(sum(i["fit_score"] for i in negative) / len(negative), 2) if negative else 0.0
        ),
        "companies_positive": sorted({i["company"] for i in positive if i["company"]}),
        "companies_negative": sorted({i["company"] for i in negative if i["company"]}),
        "sources_applied": dict(Counter(i["source"] for i in applied if i["source"])),
    }
    return history, stats


async def build_digest(session_id: str = "feedback") -> dict[str, Any]:
    """Run the analyst. Returns an empty digest when there is no history yet."""
    history, stats = collect_history()
    if not history:
        return {}
    # With nothing but saved postings there is no outcome signal to read.
    if stats["total_applied"] == 0:
        return {
            "summary": (
                f"{stats['total_tracked']} postings saved but none applied to yet — "
                "no outcome signal to learn from."
            ),
            "what_works": [],
            "what_fails": [],
            "search_adjustments": [],
            "playbook_amendments": [],
        }

    try:
        result = await execute(
            build_feedback_analyst(history, stats),
            kind="feedback",
            session_id=session_id,
            label="feedback digest",
            message=user_message("Analyse the application history and produce the digest."),
        )
    except Exception:
        logger.exception("Feedback digest failed")
        return {}

    digest = result.state.get(DIGEST_STATE_KEY) or {}
    return digest if isinstance(digest, dict) else {}
