"""Helpers for opening and closing an `AgentRun` — the unit the traces UI groups by."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from ..db.engine import session_scope
from ..db.models import AgentRun, RunStatus, utcnow
from .context import RunContext, run_context


def create_run(kind: str, label: str = "", payload: dict[str, Any] | None = None) -> int:
    with session_scope() as session:
        run = AgentRun(kind=kind, label=label, input=payload or {})
        session.add(run)
        session.flush()
        return int(run.id)


def finish_run(
    run_id: int,
    *,
    status: str = RunStatus.SUCCEEDED,
    output: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    with session_scope() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            return
        run.status = status
        run.finished_at = utcnow()
        if output is not None:
            run.output = output
        if error:
            run.error = error
        session.add(run)


@contextmanager
def tracked_run(
    kind: str, label: str = "", payload: dict[str, Any] | None = None
) -> Iterator[RunContext]:
    """Open an AgentRun, expose it to `AuditPlugin`, and close it out on exit."""
    run_id = create_run(kind, label, payload)
    ctx = RunContext(run_id=run_id, kind=kind, label=label)
    try:
        with run_context(ctx):
            yield ctx
    except Exception as exc:
        finish_run(run_id, status=RunStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
        raise
    else:
        finish_run(run_id, status=RunStatus.SUCCEEDED)
