"""Offline quality harness — `make eval`.

Runs the Critic over the golden cases and checks it still catches what it is
supposed to catch. This guards the audit itself: prompts drift, models change,
and a Critic that has quietly started rubber-stamping everything is worse than
no Critic at all.

Exits non-zero if any case fails, so it can gate a commit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass

from ..config import get_settings
from ..db.engine import init_db
from ..observability.tracing import setup_tracing
from ..services import runtime_config
from ..services.audit import audit_artifact
from .cases import CASES, EvalCase


@dataclass
class CaseResult:
    case: EvalCase
    overall: float
    verdict: str
    failures: list[str]

    @property
    def passed(self) -> bool:
        return not self.failures


def _haystack(result: dict) -> str:
    parts = [
        *(result.get("fixes") or []),
        *(result.get("unsupported_claims") or []),
        result.get("reasoning", ""),
    ]
    return " ".join(str(part) for part in parts).lower()


async def run_case(case: EvalCase) -> CaseResult:
    verdict = await audit_artifact(
        subject_kind=case.subject_kind,
        artifact=case.artifact,
        session_id=f"eval-{case.name}",
        context=case.context,
        subject_id=f"eval:{case.name}",
    )
    if not verdict:
        return CaseResult(case, 0.0, "error", ["the Critic returned nothing"])

    overall = float(verdict.get("overall", 0) or 0)
    failures: list[str] = []

    if overall > case.max_overall:
        failures.append(f"scored {overall:.1f}, expected at most {case.max_overall}")
    if overall < case.min_overall:
        failures.append(f"scored {overall:.1f}, expected at least {case.min_overall}")
    if case.expect_unsupported and not verdict.get("unsupported_claims"):
        failures.append("did not flag any unsupported claims")

    if case.must_flag:
        haystack = _haystack(verdict)
        if not any(term in haystack for term in case.must_flag):
            failures.append(f"never mentioned any of {case.must_flag}")

    return CaseResult(case, overall, str(verdict.get("verdict", "")), failures)


async def main_async(selected: list[str] | None) -> int:
    settings = get_settings()
    if not settings.google_api_key:
        print("GOOGLE_API_KEY is not set — evals need a live model. Add it to .env.")
        return 2

    init_db()
    # Evals should score the models the app is actually running, not the ones
    # .env happens to name — the Settings page can have changed them.
    runtime_config.apply()
    setup_tracing()

    cases = [case for case in CASES if not selected or case.name in selected]
    if not cases:
        print(f"No cases matched {selected}")
        return 2

    print(f"Running {len(cases)} eval case(s) against {settings.model_fast}\n")

    # No wrapping `tracked_run` here: each `audit_artifact` opens its own run,
    # which would shadow an outer one and leave it with zero events — an empty
    # parent run in the traces UI is worse than no parent run.
    results: list[CaseResult] = []
    for case in cases:
        result = await run_case(case)
        results.append(result)
        mark = "PASS" if result.passed else "FAIL"
        print(f"  [{mark}] {case.name:<38} {result.overall:>4.1f}/10  ({result.verdict})")
        for failure in result.failures:
            print(f"         ↳ {failure}")

    failed = [result for result in results if not result.passed]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")

    if failed:
        print("\nFailing cases:")
        for result in failed:
            print(f"  {result.case.name}: {'; '.join(result.failures)}")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the agent quality evals.")
    parser.add_argument("--case", action="append", help="Run only this case (repeatable).")
    parser.add_argument("--list", action="store_true", help="List the available cases.")
    args = parser.parse_args()

    if args.list:
        print(json.dumps([case.name for case in CASES], indent=2))
        return

    sys.exit(asyncio.run(main_async(args.case)))


if __name__ == "__main__":
    main()
