"""Account-based history of sent search queries for the Jobs chat (Ask the agents)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import delete, select

from ..db.engine import session_scope
from ..db.models import AgentRun, RunKind, SearchQuery, utcnow

logger = logging.getLogger(__name__)

MAX_HISTORY_ITEMS = 50


def serialise_query(query: SearchQuery) -> dict[str, Any]:
    """Wire format for search history items, compatible with frontend SearchHistoryItem."""
    return {
        "id": str(query.id),
        "text": query.text,
        "created_at": query.created_at.isoformat(),
        "updated_at": query.updated_at.isoformat(),
        "timestamp": int(query.updated_at.timestamp() * 1000),
    }


def list_history(limit: int = MAX_HISTORY_ITEMS) -> list[SearchQuery]:
    """Return past search queries, freshest first."""
    with session_scope() as session:
        items = list(
            session.exec(
                select(SearchQuery).order_by(SearchQuery.updated_at.desc()).limit(limit)
            ).all()
        )
        for item in items:
            session.expunge(item)
        return items


def record_query(
    text: str,
    *,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> SearchQuery | None:
    """Record a search query.

    Case-insensitively deduplicates by bringing an existing query to the top with
    an updated timestamp. Prunes stored items to MAX_HISTORY_ITEMS.
    """
    trimmed = text.strip()
    if not trimmed:
        return None

    now = utcnow()
    eff_created = created_at or now
    eff_updated = updated_at or eff_created

    with session_scope() as session:
        existing = session.exec(
            select(SearchQuery).where(func.lower(SearchQuery.text) == trimmed.lower())
        ).first()

        if existing:
            existing.text = trimmed
            existing.updated_at = eff_updated
            session.add(existing)
            target_id = existing.id
        else:
            new_item = SearchQuery(
                text=trimmed,
                created_at=eff_created,
                updated_at=eff_updated,
            )
            session.add(new_item)
            session.flush()
            target_id = new_item.id

        # Prune to MAX_HISTORY_ITEMS
        all_ids = list(
            session.exec(
                select(SearchQuery.id).order_by(SearchQuery.updated_at.desc())
            ).all()
        )
        if len(all_ids) > MAX_HISTORY_ITEMS:
            stale_ids = all_ids[MAX_HISTORY_ITEMS:]
            session.exec(delete(SearchQuery).where(SearchQuery.id.in_(stale_ids)))

        session.flush()
        target = session.get(SearchQuery, target_id)
        if target is not None:
            session.expunge(target)
        return target


def delete_query(query_id: int) -> bool:
    """Remove a specific search query by ID."""
    with session_scope() as session:
        item = session.get(SearchQuery, query_id)
        if not item:
            return False
        session.delete(item)
        return True


def clear_history() -> int:
    """Wipe all search queries."""
    with session_scope() as session:
        count = session.exec(select(func.count(SearchQuery.id))).one()
        if count:
            session.exec(delete(SearchQuery))
        return count


def backfill_from_runs() -> int:
    """Seed search_query from past investigator runs if search_query is empty."""
    with session_scope() as session:
        count = session.exec(select(func.count(SearchQuery.id))).one()
        if count > 0:
            return 0

        runs = session.exec(
            select(AgentRun)
            .where(AgentRun.kind == RunKind.INVESTIGATOR)
            .order_by(AgentRun.id.asc())
        ).all()

        added = 0
        seen: dict[str, tuple[str, datetime]] = {}
        for run in runs:
            payload = run.input
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}
            if isinstance(payload, dict):
                focus = payload.get("focus")
                if isinstance(focus, str) and focus.strip():
                    t = focus.strip()
                    seen[t.lower()] = (t, run.started_at)

        for t, started_at in seen.values():
            session.add(
                SearchQuery(
                    text=t,
                    created_at=started_at,
                    updated_at=started_at,
                )
            )
            added += 1

        if added > 0:
            session.flush()
            all_ids = list(
                session.exec(
                    select(SearchQuery.id).order_by(SearchQuery.updated_at.desc())
                ).all()
            )
            if len(all_ids) > MAX_HISTORY_ITEMS:
                stale_ids = all_ids[MAX_HISTORY_ITEMS:]
                session.exec(delete(SearchQuery).where(SearchQuery.id.in_(stale_ids)))
            logger.info("Backfilled %d search queries from past investigator runs", added)
        return added
