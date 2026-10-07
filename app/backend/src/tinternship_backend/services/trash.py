"""Deleting postings forever, from either trash.

Both trashes are reversible by design — swiping left and giving up on an
application keep everything, so either can be undone. This is the step past
that, for a pile that has grown into clutter: the posting's content, its
application, the application's timeline, every generated document and the files
exported from them are erased.

**Except the posting's identity.** A deleted posting stays *answered*, because
an answered posting never comes back (`documentation/triage.md`). With no row
at all, `partition_answered` would have nothing to match the next Investigator
run's result against, and the posting the candidate threw away twice would be
back in the deck. So the row survives as a tombstone: `dedupe_key`, `title`,
`company`, `url` and `discovered_at`, `dismissed` set, `purged_at` stamped, and
every other field back to its default. Every list hides it; the agents still
see it as `[rejected]`; pasting it again brings it back, as a paste does out of
either trash.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlmodel import col, delete, select

from ..config import get_settings
from ..db.engine import session_scope
from ..db.models import Application, ApplicationArtifact, ApplicationEvent, JobPosting, utcnow

logger = logging.getLogger(__name__)

# What a tombstone keeps: enough for `find_existing`, `find_pasted` and
# `known_postings_block` to recognise the posting, and nothing else.
TOMBSTONE_KEEPS = frozenset(
    {"id", "dedupe_key", "title", "company", "url", "discovered_at", "dismissed", "purged_at"}
)


class NotInTrash(ValueError):
    """The posting or application is not in a trash, so it cannot be deleted."""


def _purge(session, posting: JobPosting) -> list[str]:
    """Erase one posting down to its tombstone. Returns the files to remove."""
    files: list[str] = []
    application_ids = [
        application.id
        for application in session.exec(
            select(Application).where(Application.job_posting_id == posting.id)
        ).all()
    ]
    if application_ids:
        artifacts = session.exec(
            select(ApplicationArtifact).where(
                col(ApplicationArtifact.application_id).in_(application_ids)
            )
        ).all()
        files += [artifact.rendered_path for artifact in artifacts if artifact.rendered_path]
        # Children before parents, as SQL statements rather than ORM deletes:
        # there are no relationships declared, so the unit of work would not
        # know to order them, and foreign keys are enforced.
        session.exec(
            delete(ApplicationArtifact).where(
                col(ApplicationArtifact.application_id).in_(application_ids)
            )
        )
        session.exec(
            delete(ApplicationEvent).where(col(ApplicationEvent.application_id).in_(application_ids))
        )
        session.exec(delete(Application).where(col(Application.id).in_(application_ids)))

    for name, field in JobPosting.model_fields.items():
        if name not in TOMBSTONE_KEEPS:
            setattr(posting, name, field.get_default(call_default_factory=True))
    posting.dismissed = True
    posting.purged_at = utcnow()
    session.add(posting)
    return files


def _remove_files(paths: list[str]) -> int:
    """Delete exported files, but only ones inside the exports directory."""
    root = get_settings().artifacts_path.resolve()
    removed = 0
    for raw in paths:
        path = Path(raw).resolve()
        if not path.is_relative_to(root):
            logger.warning("Not deleting %s: outside %s", path, root)
            continue
        try:
            path.unlink()
            removed += 1
        except FileNotFoundError:
            pass
    return removed


def _finish(posting_ids: list[int], files: list[str]) -> dict[str, int]:
    return {"deleted": len(posting_ids), "files": _remove_files(files)}


def _in_deck_trash(session, posting: JobPosting) -> bool:
    """Dismissed, not yet purged, and not carrying an application still in play."""
    if not posting.dismissed or posting.purged_at is not None:
        return False
    live = session.exec(
        select(Application).where(
            Application.job_posting_id == posting.id,
            col(Application.trashed_at).is_(None),
        )
    ).first()
    return live is None


def delete_job(job_id: int) -> dict[str, int]:
    """Delete one posting from the deck's trash. `LookupError` / `NotInTrash`."""
    with session_scope() as session:
        posting = session.get(JobPosting, job_id)
        if posting is None or posting.purged_at is not None:
            raise LookupError(f"No job {job_id}")
        if not _in_deck_trash(session, posting):
            raise NotInTrash("Only a posting in the trash can be deleted forever.")
        files = _purge(session, posting)
    return _finish([job_id], files)


def empty_deck_trash() -> dict[str, int]:
    """Delete every posting in the deck's trash."""
    files: list[str] = []
    ids: list[int] = []
    with session_scope() as session:
        for posting in session.exec(select(JobPosting).where(JobPosting.dismissed == True)).all():  # noqa: E712
            if _in_deck_trash(session, posting):
                files += _purge(session, posting)
                ids.append(int(posting.id or 0))
    return _finish(ids, files)


def delete_application(application_id: int) -> dict[str, int]:
    """Delete one application from the Tracker's trash, and its posting with it."""
    with session_scope() as session:
        application = session.get(Application, application_id)
        if application is None:
            raise LookupError(f"No application {application_id}")
        if application.trashed_at is None:
            raise NotInTrash("Only an application in the trash can be deleted forever.")
        posting = session.get(JobPosting, application.job_posting_id)
        if posting is None:
            raise LookupError(f"No job {application.job_posting_id}")
        files = _purge(session, posting)
        job_id = int(posting.id or 0)
    return _finish([job_id], files)


def empty_tracker_trash() -> dict[str, int]:
    """Delete every application in the Tracker's trash, and their postings."""
    files: list[str] = []
    ids: list[int] = []
    with session_scope() as session:
        trashed = session.exec(
            select(Application).where(col(Application.trashed_at).is_not(None))
        ).all()
        for posting_id in {application.job_posting_id for application in trashed}:
            posting = session.get(JobPosting, posting_id)
            if posting is not None:
                files += _purge(session, posting)
                ids.append(posting_id)
    return _finish(ids, files)
