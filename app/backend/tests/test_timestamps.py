"""Timestamps must survive the round-trip through SQLite as aware UTC.

SQLite stores no offset, so before `UTCDateTime` every timestamp came back
naive. That crashed an OAuth token expiry check with `TypeError: can't compare
offset-naive and offset-aware datetimes` — the integration that failed on it was
removed on 2026-08-28, but the trap it exposed is a property of every timestamp
column in the schema — and it silently shifted every timestamp the UI renders by
the viewer's UTC offset.

The subject here is `Profile`, chosen because it is an ordinary row with both a
`created_at` and an `updated_at`: any comparison of a stored timestamp against
`utcnow()` is the failing one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import text
from sqlmodel import select

from tinternship_backend.db.engine import get_engine, session_scope
from tinternship_backend.db.models import AgentRun, Profile, RunKind, utcnow


def _save_profile(**kwargs: Any) -> None:
    kwargs.setdefault("updated_at", utcnow())
    with session_scope() as session:
        session.add(Profile(full_name="Alex", **kwargs))


def _column(attr: str) -> Any:
    """Read one column back. Inside the scope: the row detaches on close."""
    with session_scope() as session:
        return getattr(session.exec(select(Profile)).one(), attr)


class TestRoundTrip:
    def test_reads_back_aware_and_comparable(self):
        _save_profile(updated_at=utcnow() + timedelta(hours=1))

        updated_at = _column("updated_at")
        assert updated_at.tzinfo is not None
        # The exact comparison that used to raise.
        assert updated_at > utcnow()

    def test_a_past_timestamp_still_compares(self):
        _save_profile(updated_at=utcnow() - timedelta(hours=1))

        assert _column("updated_at") <= utcnow()

    def test_isoformat_carries_the_offset(self):
        # Without this the browser's `new Date()` reads a UTC instant as local time.
        _save_profile()

        assert _column("created_at").isoformat().endswith("+00:00")

    def test_nullable_timestamp_stays_none(self):
        with session_scope() as session:
            session.add(AgentRun(kind=RunKind.APPLYING))

        with session_scope() as session:
            run = session.exec(select(AgentRun)).one()
            assert run.finished_at is None
            assert run.started_at.tzinfo is not None

    def test_non_utc_input_is_normalised(self):
        # +05:30 in, UTC out — same instant, one representation.
        moment = datetime(2026, 8, 14, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        _save_profile(updated_at=moment)

        stored = _column("updated_at")
        assert stored == moment
        assert stored == datetime(2026, 8, 14, 6, 30, tzinfo=UTC)


class TestExistingRows:
    def test_naive_rows_written_before_the_fix_read_back_as_utc(self):
        """Rows already in production hold a UTC wall clock with no offset."""
        _save_profile()
        with get_engine().begin() as connection:
            connection.execute(
                text("UPDATE profile SET updated_at = '2026-08-14 21:00:00.000000'")
            )

        assert _column("updated_at") == datetime(2026, 8, 14, 21, 0, tzinfo=UTC)

    def test_storage_format_is_unchanged(self):
        """No migration: the column still holds the same string it always did."""
        _save_profile(updated_at=datetime(2026, 8, 14, 21, 0, tzinfo=UTC))

        with get_engine().connect() as connection:
            raw = connection.execute(text("SELECT updated_at FROM profile")).scalar()
        assert raw == "2026-08-14 21:00:00.000000"


@pytest.mark.parametrize("column", ["created_at", "updated_at"])
def test_every_timestamp_column_is_aware(column: str):
    _save_profile()

    assert _column(column).tzinfo is UTC
