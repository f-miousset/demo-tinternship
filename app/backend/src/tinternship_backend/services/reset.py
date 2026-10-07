"""Wiping stored data so the app can be started over.

Two things make this less trivial than "delete from every table":

1. **Foreign keys.** `PRAGMA foreign_keys=ON` is set, and `JobPosting`,
   `ApplicationArtifact` and `AuditRecord` all reference `AgentRun`. Deleting
   traces while keeping jobs would be rejected, so cross-scope references are
   nulled out before the parent rows go.
2. **State outside the main database.** The interview transcript lives in ADK's
   own session store, uploaded documents and rendered exports live on disk, and OTel
   spans live in a third SQLite file. A reset that leaves the chat history
   behind is not a blank page.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import delete, func, select, update

from ..config import get_settings
from ..db.engine import session_scope
from ..db.models import (
    AgentPrompt,
    AgentRun,
    Application,
    ApplicationArtifact,
    ApplicationEvent,
    AuditRecord,
    JobPosting,
    Profile,
    ProfileSource,
    SearchQuery,
    TraceEvent,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Scope:
    key: str
    label: str
    description: str


SCOPES: tuple[Scope, ...] = (
    Scope(
        "profile",
        "Profile & imported documents",
        "Your master profile, all four base documents — the two résumés and the two "
        "cover letters — and every other document you imported.",
    ),
    Scope(
        "strategy",
        "Search brief & hiring playbook",
        "Both editable prompts and their full version history.",
    ),
    Scope(
        "jobs",
        "Job postings & applications",
        "Discovered postings, saved applications, their status history, and every "
        "generated résumé, cover letter, follow-up, interview brief and contact "
        "shortlist.",
    ),
    Scope(
        "conversations",
        "Agent conversations",
        "The interview transcript and every other stored agent session.",
    ),
    Scope(
        "traces",
        "Traces & audit history",
        "The decision log, quality scores, token and cost history.",
    ),
)

SCOPE_KEYS = frozenset(scope.key for scope in SCOPES)


def summary() -> dict[str, int]:
    """How much of each thing is currently stored, for the confirmation UI."""
    with session_scope() as session:

        def count(model) -> int:
            return int(session.exec(select(func.count(model.id))).one())

        return {
            "profile": count(Profile),
            "profile_sources": count(ProfileSource),
            "prompts": count(AgentPrompt),
            "jobs": count(JobPosting),
            "applications": count(Application),
            "artifacts": count(ApplicationArtifact),
            "runs": count(AgentRun),
            "trace_events": count(TraceEvent),
            "audits": count(AuditRecord),
            "search_queries": count(SearchQuery),
        }


def _clear_directory(path: Path) -> int:
    if not path.exists():
        return 0
    removed = 0
    for entry in path.iterdir():
        try:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
            removed += 1
        except OSError:
            logger.warning("Could not remove %s", entry, exc_info=True)
    return removed


def _clear_spans() -> int:
    """Truncate the OTel span database without dropping the file the exporter holds open."""
    settings = get_settings()
    if not settings.trace_db_path.exists():
        return 0
    try:
        connection = sqlite3.connect(str(settings.trace_db_path), timeout=10)
        try:
            removed = connection.execute("SELECT COUNT(*) FROM spans").fetchone()[0]
            connection.execute("DELETE FROM spans")
            connection.commit()
        finally:
            connection.close()
        return int(removed)
    except sqlite3.Error:
        logger.warning("Could not clear the OTel span database", exc_info=True)
        return 0


async def _clear_sessions() -> int:
    from ..agents.runtime import APP_NAME, DEFAULT_USER_ID, get_session_service

    service = get_session_service()
    try:
        listing = await service.list_sessions(app_name=APP_NAME, user_id=DEFAULT_USER_ID)
    except Exception:
        logger.warning("Could not list agent sessions", exc_info=True)
        return 0

    removed = 0
    for session in listing.sessions:
        try:
            await service.delete_session(
                app_name=APP_NAME, user_id=DEFAULT_USER_ID, session_id=session.id
            )
            removed += 1
        except Exception:
            logger.warning("Could not delete session %s", session.id, exc_info=True)
    return removed


async def reset(scopes: set[str]) -> dict[str, int]:
    """Delete the selected scopes. Returns a per-thing tally of what went."""
    unknown = scopes - SCOPE_KEYS
    if unknown:
        raise ValueError(f"Unknown reset scope(s): {sorted(unknown)}")
    if not scopes:
        raise ValueError("Nothing selected to delete.")

    settings = get_settings()
    deleted: dict[str, int] = {}

    with session_scope() as session:

        def wipe(model, name: str) -> None:
            count = int(session.exec(select(func.count(model.id))).one())
            if count:
                session.exec(delete(model))
            deleted[name] = count

        # Children before parents throughout — foreign keys are enforced.
        if "jobs" in scopes:
            wipe(SearchQuery, "search_queries")
            wipe(ApplicationArtifact, "artifacts")
            wipe(ApplicationEvent, "application_events")
            wipe(Application, "applications")
            wipe(JobPosting, "jobs")

        if "traces" in scopes:
            # Rows in surviving scopes point at AgentRun; release them first.
            if "jobs" not in scopes:
                session.exec(update(JobPosting).values(run_id=None))
                session.exec(update(ApplicationArtifact).values(run_id=None))
            wipe(AuditRecord, "audits")
            wipe(TraceEvent, "trace_events")
            wipe(AgentRun, "runs")

        if "profile" in scopes:
            wipe(ProfileSource, "profile_sources")
            wipe(Profile, "profile")

        if "strategy" in scopes:
            wipe(AgentPrompt, "prompts")

    # Files and the other two databases, once the rows referencing them are gone.
    if "profile" in scopes:
        deleted["uploaded_files"] = _clear_directory(settings.uploads_path)
    if "jobs" in scopes:
        deleted["rendered_files"] = _clear_directory(settings.artifacts_path)
    if "traces" in scopes:
        deleted["otel_spans"] = _clear_spans()
    if "conversations" in scopes:
        deleted["conversations"] = await _clear_sessions()

    logger.info("Reset %s -> %s", sorted(scopes), deleted)
    return deleted
