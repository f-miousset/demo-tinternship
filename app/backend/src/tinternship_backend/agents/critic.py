"""The quality gate.

`reviewed(...)` wraps any producer agent in a three-step loop:

    LoopAgent[ producer → critic → gate ]

* **producer** writes its artifact to `state[output_key]`.
* **critic** scores it against the artifact's rubric and writes a
  `CriticVerdict` to `state[verdict_key]`.
* **gate** is deterministic Python, not a model: it recomputes the weighted
  overall from the criterion scores (so the Critic cannot fudge the arithmetic),
  writes an `AuditRecord`, and escalates to end the loop when the artifact
  passes or the revision budget is spent.

The gate being a separate agent matters — by the time it runs, the critic's
`output_key` delta has been committed to session state, which is not guaranteed
inside the critic's own callbacks.

**The loop keeps the best attempt, not the last one.** A producer's `output_key`
write replaces the artifact wholesale, so a revision that comes back partial —
answering the critique with only the fields it changed, which is exactly what
`FEEDBACK_NOTE` asks it not to do — would otherwise destroy a good first draft
and get saved anyway once the revision budget ran out. The gate remembers the
highest-scoring attempt and restores it before the loop ends. Scores decide,
not size: a résumé is often *meant* to get shorter under critique.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Sequence
from typing import Any

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.loop_agent import LoopAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events.event import Event, EventActions
from google.genai import types
from pydantic import PrivateAttr

from ..config import get_settings
from ..db.engine import session_scope
from ..db.models import AuditRecord
from ..observability.context import current_run
from .models import resolve
from .prompts import CRITIC_INSTRUCTION
from .rubrics import Rubric

logger = logging.getLogger(__name__)

REVISION_KEY_TEMPLATE = "_revisions_{key}"
BEST_KEY_TEMPLATE = "_best_{key}"
BEST_SCORE_KEY_TEMPLATE = "_best_score_{key}"
GATE_INVOCATION_KEY_TEMPLATE = "_gate_invocation_{key}"


def _as_dict(value: Any) -> dict[str, Any]:
    """State values arrive as dicts, JSON strings or pydantic models depending on path."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"raw": value}
        return parsed if isinstance(parsed, dict) else {"raw": value}
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return {"raw": str(value)}


def weighted_overall(verdict: dict[str, Any], rubric: Rubric) -> float:
    """Recompute the overall from criterion scores using the rubric's weights.

    Falls back to the Critic's own `overall` only if no criterion scores came
    back. The `truthfulness` cap is applied here so it cannot be talked around.
    """
    scores = verdict.get("scores") or []
    by_name = {
        str(item.get("criterion", "")).strip().lower(): float(item.get("score", 0) or 0)
        for item in scores
        if isinstance(item, dict)
    }
    if not by_name:
        return float(verdict.get("overall", 0) or 0)

    total_weight = 0.0
    total = 0.0
    for criterion in rubric.criteria:
        score = by_name.get(criterion.name.lower())
        if score is None:
            continue
        total += score * criterion.weight
        total_weight += criterion.weight
    overall = (total / total_weight) if total_weight else float(verdict.get("overall", 0) or 0)

    # A fabricated claim is disqualifying regardless of how good the rest is.
    if verdict.get("unsupported_claims"):
        overall = min(overall, 4.0)
    truthfulness = by_name.get("truthfulness")
    if truthfulness is not None and truthfulness < 5:
        overall = min(overall, truthfulness)

    return round(overall, 2)


def build_critic(
    *,
    name: str,
    rubric: Rubric,
    artifact_key: str,
    verdict_key: str,
    context_provider: Any = None,
) -> LlmAgent:
    """A Critic specialised to one rubric."""
    settings = get_settings()

    async def instruction(ctx: ReadonlyContext) -> str:
        artifact = ctx.state.get(artifact_key)
        extra = ""
        if context_provider is not None:
            extra = await _maybe_await(context_provider, ctx)
        return "\n\n".join(
            part
            for part in (
                CRITIC_INSTRUCTION,
                rubric.render(),
                extra,
                "## Artifact under review\n\n```json\n"
                + json.dumps(_as_dict(artifact), indent=2, ensure_ascii=False, default=str)
                + "\n```",
                f"Set `subject_kind` to `{rubric.subject_kind}`.",
            )
            if part
        )

    from .schemas import CriticVerdict  # local import to avoid a cycle at module load

    return LlmAgent(
        name=name,
        model=resolve(settings.model_fast),
        description=f"Audits the {rubric.subject_kind} against rubric {rubric.key}.",
        instruction=instruction,
        output_schema=CriticVerdict,
        output_key=verdict_key,
        include_contents="none",
    )


async def _maybe_await(provider: Any, ctx: ReadonlyContext) -> str:
    result = provider(ctx)
    if hasattr(result, "__await__"):
        return await result
    return result or ""


class QualityGate(BaseAgent):
    """Deterministic loop controller: score, persist the audit, decide whether to stop."""

    _rubric: Rubric = PrivateAttr()
    _artifact_key: str = PrivateAttr()
    _verdict_key: str = PrivateAttr()
    _subject_id_key: str = PrivateAttr()
    _threshold: float = PrivateAttr()
    _max_revisions: int = PrivateAttr()
    _hard_check: Any = PrivateAttr()

    def __init__(
        self,
        *,
        name: str,
        rubric: Rubric,
        artifact_key: str,
        verdict_key: str,
        subject_id_key: str = "",
        threshold: float | None = None,
        max_revisions: int | None = None,
        hard_check: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, description=f"Quality gate for {rubric.subject_kind}.", **kwargs)
        settings = get_settings()
        self._rubric = rubric
        self._artifact_key = artifact_key
        self._verdict_key = verdict_key
        self._subject_id_key = subject_id_key
        self._threshold = settings.audit_pass_threshold if threshold is None else threshold
        self._max_revisions = (
            settings.audit_max_revisions if max_revisions is None else max_revisions
        )
        # A constraint the artifact must satisfy no matter what the Critic said:
        # returns "" when it holds, otherwise the reason. For the résumé that is
        # "fits one page at 11pt" — a fact, measurable in Python, and the Critic
        # has already been observed scoring it 7/10 when told to cap it at 2.
        self._hard_check = hard_check

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        verdict = _as_dict(state.get(self._verdict_key))
        revision_key = REVISION_KEY_TEMPLATE.format(key=self._artifact_key)
        best_key = BEST_KEY_TEMPLATE.format(key=self._artifact_key)
        best_score_key = BEST_SCORE_KEY_TEMPLATE.format(key=self._artifact_key)
        invocation_key = GATE_INVOCATION_KEY_TEMPLATE.format(key=self._artifact_key)

        # The ADK session is reused across generations for the same job, so this
        # bookkeeping outlives the run that wrote it. Left alone, the second
        # generation starts with its revision budget already spent — the Critic's
        # feedback is never acted on — and could restore a previous run's
        # artifact over this one. Anything from another invocation is not ours.
        fresh = state.get(invocation_key) != ctx.invocation_id
        revision = 0 if fresh else int(state.get(revision_key, 0) or 0)

        attempt_score = weighted_overall(verdict, self._rubric)
        current = _as_dict(state.get(self._artifact_key))

        # Keep whichever attempt scored highest. `>=` so the newest of two equal
        # attempts wins: the later one has at least seen the critique.
        previous_best = None if fresh else state.get(best_key)
        previous_score = 0.0 if fresh else float(state.get(best_score_key, 0.0) or 0.0)
        # A hard-check failure disqualifies the attempt outright, so it must not
        # be banked as "best" and win a rollback later.
        attempt_violation = self._violation(current)
        previous_violation = self._violation(_as_dict(previous_best)) if previous_best else ""
        if attempt_violation and not previous_violation and previous_best is not None:
            rolled_back = True
        elif previous_violation and not attempt_violation:
            rolled_back = False
        else:
            rolled_back = previous_best is not None and attempt_score < previous_score

        kept = _as_dict(previous_best) if rolled_back else current
        overall = previous_score if rolled_back else attempt_score
        violation = previous_violation if rolled_back else attempt_violation

        passed = (
            overall >= self._threshold
            and not violation
            and (rolled_back or verdict.get("verdict") != "fail")
        )
        budget_spent = revision + 1 >= self._max_revisions
        stop = passed or budget_spent or not self._rubric.blocking

        subject_id = str(state.get(self._subject_id_key, "")) if self._subject_id_key else ""
        # The audit describes the artifact we are keeping, not the one we threw away.
        self._persist(verdict, overall, revision, passed, subject_id, violation)

        if stop:
            reason = (
                "passed"
                if passed
                else ("revision budget exhausted" if budget_spent else "advisory-only rubric")
            )
            summary = (
                f"Audit {self._rubric.subject_kind}: {overall:.1f}/10 "
                f"(threshold {self._threshold}) — {reason}."
            )
            if rolled_back:
                logger.warning(
                    "Revision %s of the %s scored %.2f, below the %.2f its previous "
                    "attempt scored — keeping the better attempt.",
                    revision + 1,
                    self._rubric.subject_kind,
                    attempt_score,
                    previous_score,
                )
                summary += (
                    f" The revision scored {attempt_score:.1f} and was discarded in "
                    "favour of the earlier attempt."
                )
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                branch=ctx.branch,
                content=types.Content(role="model", parts=[types.Part(text=summary)]),
                actions=EventActions(
                    escalate=True,
                    state_delta={
                        # `revisions` on the saved artifact is read off this, so
                        # it has to be this run's count, not a leftover.
                        revision_key: revision,
                        invocation_key: ctx.invocation_id,
                        # Restoring the winner has to be a state delta: the
                        # producer overwrote `artifact_key` when it revised.
                        **({self._artifact_key: kept} if rolled_back else {}),
                    },
                ),
            )
            return

        fixes = verdict.get("fixes") or []
        unsupported = verdict.get("unsupported_claims") or []
        if violation:
            headline = (
                f"Your {self._rubric.subject_kind} breaks a hard requirement. "
                "Nothing else matters until it does not:"
            )
        else:
            headline = (
                f"Your {self._rubric.subject_kind} scored {overall:.1f}/10, below the bar of "
                f"{self._threshold}. Revise it. Address every point:"
            )
        feedback_lines = [headline]
        if violation:
            feedback_lines.append(f"- {violation}")
        feedback_lines += [f"- {fix}" for fix in fixes]
        if unsupported:
            feedback_lines.append("Remove or substantiate these unsupported claims:")
            feedback_lines += [f"- {claim}" for claim in unsupported]
        feedback = "\n".join(feedback_lines)

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(role="model", parts=[types.Part(text=feedback)]),
            actions=EventActions(
                state_delta={
                    revision_key: revision + 1,
                    invocation_key: ctx.invocation_id,
                    f"{self._artifact_key}_feedback": feedback,
                    # Bank this attempt before the producer overwrites it.
                    best_key: kept,
                    best_score_key: overall,
                }
            ),
        )

    def _violation(self, artifact: dict[str, Any]) -> str:
        if self._hard_check is None or not artifact:
            return ""
        try:
            return self._hard_check(artifact) or ""
        except Exception:
            # A broken check must not take the run down with it.
            logger.exception("Hard check for %s raised", self._rubric.subject_kind)
            return ""

    def _persist(
        self,
        verdict: dict[str, Any],
        overall: float,
        revision: int,
        passed: bool,
        subject_id: str,
        violation: str = "",
    ) -> None:
        run = current_run()
        try:
            with session_scope() as session:
                session.add(
                    AuditRecord(
                        subject_kind=self._rubric.subject_kind,
                        subject_id=subject_id,
                        rubric=self._rubric.key,
                        scores={
                            "criteria": verdict.get("scores") or [],
                            "reasoning": verdict.get("reasoning", ""),
                        },
                        overall=overall,
                        threshold=self._threshold,
                        # A hard-check failure is never a pass, whatever the
                        # Critic wrote — otherwise the UI shows a green badge on
                        # an artifact that broke a non-negotiable requirement.
                        verdict=(
                            "pass"
                            if passed
                            else ("fail" if violation else (verdict.get("verdict") or "revise"))
                        ),
                        blocking=self._rubric.blocking,
                        fixes=([f"[hard requirement] {violation}"] if violation else [])
                        + list(verdict.get("fixes") or [])
                        + [f"[unsupported] {c}" for c in (verdict.get("unsupported_claims") or [])],
                        revision=revision,
                        run_id=run.run_id if run else None,
                        invocation_id=run.invocation_id if run else "",
                    )
                )
        except Exception:
            logger.exception("Failed to persist AuditRecord for %s", self._rubric.subject_kind)


def reviewed(
    producer: LlmAgent,
    *,
    rubric: Rubric,
    artifact_key: str,
    subject_id_key: str = "",
    context_provider: Any = None,
    hard_check: Any = None,
    name: str | None = None,
    then: Sequence[BaseAgent] = (),
) -> LoopAgent:
    """Wrap a producer in the produce → critique → gate loop.

    `then` runs between the producer and the Critic, inside the loop, and exists
    for one caller: the letter's Humaniser and the merge behind it. Inside
    rather than after, because whatever it does to the artifact is what ships —
    so it is what the Critic must score and what the gate's hard checks must
    measure. Anything it breaks is caught, and a revision re-runs it.
    """
    settings = get_settings()
    base = name or f"{producer.name}_reviewed"
    verdict_key = f"{artifact_key}_verdict"

    critic = build_critic(
        name=f"{producer.name}_critic",
        rubric=rubric,
        artifact_key=artifact_key,
        verdict_key=verdict_key,
        context_provider=context_provider,
    )
    gate = QualityGate(
        name=f"{producer.name}_gate",
        rubric=rubric,
        artifact_key=artifact_key,
        verdict_key=verdict_key,
        subject_id_key=subject_id_key,
        hard_check=hard_check,
    )
    return LoopAgent(
        name=base,
        description=f"Produces and audits the {rubric.subject_kind}.",
        max_iterations=max(1, settings.audit_max_revisions),
        sub_agents=[producer, *then, critic, gate],
    )
