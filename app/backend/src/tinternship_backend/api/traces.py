"""The audit trail: runs, their decision logs, and quality scores.

This is the user-facing half of the "trace everything" requirement. Layer 2
(`TraceEvent`, written by `AuditPlugin`) is what these endpoints serve; layer 1
(raw OTel spans in `traces.db`) is exposed separately for the rare case where
you need the mechanical view.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import func
from sqlmodel import select

from ..config import get_settings
from ..db.engine import session_scope
from ..db.models import AgentRun, AuditRecord, TraceEvent

router = APIRouter(prefix="/api/traces", tags=["traces"])

# `make eval` scores deliberately-broken golden artifacts. Those verdicts are
# valuable as a regression signal but must not drag down the dashboard's view of
# how good the user's *actual* documents are — a fabricated eval résumé scoring
# 0.0 made real résumés read as mediocre. They are tagged `eval:<case>` in
# subject_id, so they are excluded here and shown only via ?include_evals=true.
EVAL_PREFIX = "eval:"


def _exclude_evals(statement):
    return statement.where(
        (AuditRecord.subject_id == "") | (~AuditRecord.subject_id.startswith(EVAL_PREFIX))
    )


def _serialise_run(run: AgentRun) -> dict[str, Any]:
    duration_ms = None
    if run.finished_at is not None:
        duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
    return {
        "id": run.id,
        "kind": run.kind,
        "label": run.label,
        "status": run.status,
        "session_id": run.session_id,
        "invocation_id": run.invocation_id,
        "input": run.input,
        "output": run.output,
        "error": run.error,
        "prompt_tokens": run.prompt_tokens,
        "output_tokens": run.output_tokens,
        "total_tokens": run.total_tokens,
        "llm_calls": run.llm_calls,
        "tool_calls": run.tool_calls,
        "cost_usd": round(run.cost_usd, 6),
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_ms": duration_ms,
    }


def _serialise_event(event: TraceEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "seq": event.seq,
        "phase": event.phase,
        "agent_name": event.agent_name,
        "model": event.model,
        "tool_name": event.tool_name,
        "summary": event.summary,
        "input_preview": event.input_preview,
        "output_preview": event.output_preview,
        "payload": event.payload,
        "prompt_tokens": event.prompt_tokens,
        "output_tokens": event.output_tokens,
        "total_tokens": event.total_tokens,
        "latency_ms": event.latency_ms,
        "error": event.error,
        "invocation_id": event.invocation_id,
        "prompt_version_id": event.prompt_version_id,
        "created_at": event.created_at.isoformat(),
    }


def _serialise_audit(record: AuditRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "subject_kind": record.subject_kind,
        "subject_id": record.subject_id,
        "rubric": record.rubric,
        "scores": record.scores,
        "overall": record.overall,
        "threshold": record.threshold,
        "verdict": record.verdict,
        "blocking": record.blocking,
        "fixes": record.fixes,
        "revision": record.revision,
        "run_id": record.run_id,
        "created_at": record.created_at.isoformat(),
    }


@router.get("/runs")
def list_runs(limit: int = 100, kind: str | None = None):
    with session_scope() as session:
        statement = select(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit)
        if kind:
            statement = statement.where(AgentRun.kind == kind)
        runs = session.exec(statement).all()
        counts = dict(
            session.exec(
                select(TraceEvent.run_id, func.count(TraceEvent.id)).group_by(TraceEvent.run_id)
            ).all()
        )
        return {
            "runs": [{**_serialise_run(run), "event_count": counts.get(run.id, 0)} for run in runs]
        }


@router.get("/runs/{run_id}")
def get_run(run_id: int):
    with session_scope() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"No run {run_id}")
        events = session.exec(
            select(TraceEvent).where(TraceEvent.run_id == run_id).order_by(TraceEvent.seq, TraceEvent.id)
        ).all()
        audits = session.exec(
            select(AuditRecord).where(AuditRecord.run_id == run_id).order_by(AuditRecord.created_at)
        ).all()
        return {
            "run": _serialise_run(run),
            "events": [_serialise_event(event) for event in events],
            "audits": [_serialise_audit(record) for record in audits],
        }


@router.get("/invocations/{invocation_id}")
def get_invocation(invocation_id: str):
    """Every decision recorded under one ADK invocation id."""
    with session_scope() as session:
        events = session.exec(
            select(TraceEvent)
            .where(TraceEvent.invocation_id == invocation_id)
            .order_by(TraceEvent.seq, TraceEvent.id)
        ).all()
        if not events:
            raise HTTPException(status_code=404, detail=f"No trace for invocation {invocation_id}")
        return {"events": [_serialise_event(event) for event in events]}


@router.get("/audits")
def list_audits(limit: int = 200, subject_kind: str | None = None, include_evals: bool = False):
    with session_scope() as session:
        statement = select(AuditRecord).order_by(AuditRecord.created_at.desc()).limit(limit)
        if subject_kind:
            statement = statement.where(AuditRecord.subject_kind == subject_kind)
        if not include_evals:
            statement = _exclude_evals(statement)
        return {"audits": [_serialise_audit(record) for record in session.exec(statement).all()]}


@router.get("/stats")
def stats():
    """Headline numbers for the audit dashboard."""
    with session_scope() as session:
        totals = session.exec(
            select(
                func.count(AgentRun.id),
                func.coalesce(func.sum(AgentRun.total_tokens), 0),
                func.coalesce(func.sum(AgentRun.cost_usd), 0.0),
                func.coalesce(func.sum(AgentRun.llm_calls), 0),
                func.coalesce(func.sum(AgentRun.tool_calls), 0),
            )
        ).one()
        run_count, tokens, cost, llm_calls, tool_calls = totals

        by_kind = session.exec(
            select(AgentRun.kind, func.count(AgentRun.id), func.coalesce(func.sum(AgentRun.cost_usd), 0.0))
            .group_by(AgentRun.kind)
        ).all()

        audit_rows = session.exec(
            _exclude_evals(
                select(
                    AuditRecord.subject_kind,
                    func.count(AuditRecord.id),
                    func.avg(AuditRecord.overall),
                )
            ).group_by(AuditRecord.subject_kind)
        ).all()
        passes = dict(
            session.exec(
                _exclude_evals(
                    select(AuditRecord.subject_kind, func.count(AuditRecord.id))
                ).where(AuditRecord.verdict == "pass")
                .group_by(AuditRecord.subject_kind)
            ).all()
        )

        event_count = session.exec(select(func.count(TraceEvent.id))).one()
        failed = session.exec(
            select(func.count(AgentRun.id)).where(AgentRun.status == "failed")
        ).one()

    return {
        "runs": run_count,
        "failed_runs": failed,
        "trace_events": event_count,
        "total_tokens": int(tokens),
        "total_cost_usd": round(float(cost), 4),
        "llm_calls": int(llm_calls),
        "tool_calls": int(tool_calls),
        "by_kind": [
            {"kind": kind, "runs": count, "cost_usd": round(float(kind_cost), 4)}
            for kind, count, kind_cost in by_kind
        ],
        "audit_by_kind": [
            {
                "subject_kind": subject_kind,
                "count": count,
                "passed": passes.get(subject_kind, 0),
                "mean_overall": round(float(mean or 0), 2),
            }
            for subject_kind, count, mean in audit_rows
        ],
    }


@router.get("/spans/{session_id}")
def spans(session_id: str):
    """Raw OpenTelemetry spans for a session — the mechanical view of layer 1."""
    from ..observability.tracing import get_span_exporter

    exporter = get_span_exporter()
    if exporter is None:
        return {"spans": [], "note": "OpenTelemetry export is not active."}
    try:
        raw = exporter.get_all_spans_for_session(session_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Span query failed: {exc}") from exc

    return {
        "db": str(get_settings().trace_db_path),
        "spans": [
            {
                "name": span.name,
                "start": span.start_time,
                "end": span.end_time,
                "duration_ms": int(((span.end_time or 0) - (span.start_time or 0)) / 1_000_000),
                "attributes": dict(span.attributes or {}),
            }
            for span in raw
        ],
    }
