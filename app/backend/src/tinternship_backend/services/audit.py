"""Standalone auditing for artifacts that are not produced inside a critic loop.

The Applying agents are gated in-line by `agents.critic.reviewed`. The brief,
the playbook and the job ranking are advisory — they are scored and logged, but
never block — so they are audited here, after the fact, with the same Critic and
the same rubrics.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

from sqlmodel import col, select

from ..agents.critic import build_critic, weighted_overall
from ..agents.rubrics import Rubric, get_rubric
from ..agents.runtime import execute, user_message
from ..db.engine import session_scope
from ..db.models import AuditRecord
from ..observability.context import current_run

logger = logging.getLogger(__name__)


def audit_payload(record: AuditRecord | None) -> dict[str, Any] | None:
    """One stored verdict, in the shape every page renders it from."""
    if record is None:
        return None
    return {
        "overall": record.overall,
        "threshold": record.threshold,
        "verdict": record.verdict,
        "rubric": record.rubric,
        "fixes": record.fixes,
        "scores": record.scores,
        "revision": record.revision,
    }


def latest_verdicts(subject_kinds: Iterable[str]) -> dict[tuple[str, str], dict[str, Any]]:
    """The most recent verdict per subject, keyed `(subject_kind, subject_id)`.

    Both halves of the key matter: a prompt id and an artifact id are both small
    integers, so `subject_id` alone puts the brief's score on someone else's
    artifact. Oldest first, so a later audit of the same subject wins.
    """
    kinds = list(subject_kinds)
    if not kinds:
        return {}
    with session_scope() as session:
        records = session.exec(
            select(AuditRecord)
            .where(col(AuditRecord.subject_kind).in_(kinds), AuditRecord.subject_id != "")
            .order_by(AuditRecord.created_at)
        ).all()
        return {
            (record.subject_kind, record.subject_id): payload
            for record in records
            if (payload := audit_payload(record))
        }


async def audit_artifact(
    *,
    subject_kind: str,
    artifact: dict[str, Any],
    session_id: str,
    context: str = "",
    subject_id: str = "",
) -> dict[str, Any]:
    """Score one artifact and persist the verdict. Never raises."""
    rubric: Rubric | None = get_rubric(subject_kind)
    if rubric is None or not artifact:
        return {}

    artifact_key = f"_audit_subject_{subject_kind}"
    verdict_key = f"{artifact_key}_verdict"

    critic = build_critic(
        name=f"{subject_kind}_auditor",
        rubric=rubric,
        artifact_key=artifact_key,
        verdict_key=verdict_key,
        context_provider=(lambda _ctx: context) if context else None,
    )

    try:
        result = await execute(
            critic,
            kind="audit",
            session_id=session_id,
            label=f"audit:{subject_kind}",
            message=user_message(
                "Audit the artifact described in your instructions and return the verdict.\n\n"
                f"```json\n{json.dumps(artifact, ensure_ascii=False, default=str)[:60000]}\n```"
            ),
        )
    except Exception:
        logger.exception("Audit of %s failed", subject_kind)
        return {}

    verdict = result.state.get(verdict_key) or {}
    if isinstance(verdict, str):
        try:
            verdict = json.loads(verdict)
        except json.JSONDecodeError:
            verdict = {}
    if not isinstance(verdict, dict):
        return {}

    overall = weighted_overall(verdict, rubric)
    # `execute` above opened and closed its own run, so the ambient context is
    # gone by now; fall back to the run the Critic itself just executed under.
    run = current_run()
    run_id = run.run_id if run else result.run_id
    invocation_id = run.invocation_id if run else result.invocation_id
    try:
        with session_scope() as session:
            session.add(
                AuditRecord(
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    rubric=rubric.key,
                    scores={
                        "criteria": verdict.get("scores") or [],
                        "reasoning": verdict.get("reasoning", ""),
                    },
                    overall=overall,
                    threshold=0.0,
                    verdict=verdict.get("verdict") or "revise",
                    blocking=False,
                    fixes=list(verdict.get("fixes") or [])
                    + [f"[unsupported] {c}" for c in (verdict.get("unsupported_claims") or [])],
                    revision=0,
                    run_id=run_id,
                    invocation_id=invocation_id,
                )
            )
    except Exception:
        logger.exception("Failed to persist advisory AuditRecord for %s", subject_kind)

    return {**verdict, "overall": overall, "rubric": rubric.key}
