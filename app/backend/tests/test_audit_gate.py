"""The quality gate's arithmetic.

`weighted_overall` is deliberately computed in Python rather than trusted from
the model, so these tests are the guarantee that a Critic cannot talk its way
past the bar.
"""

from __future__ import annotations

from tinternship_backend.agents.critic import weighted_overall
from tinternship_backend.agents.rubrics import RESUME_RUBRIC, get_rubric


def verdict(**scores: float) -> dict:
    return {
        "scores": [
            {"criterion": name, "score": score, "justification": ""}
            for name, score in scores.items()
        ],
        "overall": 9.9,  # deliberately wrong — the gate must ignore it
    }


def test_weights_are_applied_not_a_flat_mean():
    # truthfulness has weight 2.0, so a low score there must drag harder than
    # a low score on a weight-1.0 criterion would.
    low_truth = weighted_overall(
        verdict(
            truthfulness=6,
            targeting=10,
            keyword_coverage=10,
            bullet_quality=10,
            concision=10,
            completeness=10,
        ),
        RESUME_RUBRIC,
    )
    low_concision = weighted_overall(
        verdict(
            truthfulness=10,
            targeting=10,
            keyword_coverage=10,
            bullet_quality=10,
            concision=6,
            completeness=10,
        ),
        RESUME_RUBRIC,
    )
    assert low_truth < low_concision


def test_unsupported_claims_cap_the_score():
    payload = verdict(
        truthfulness=9,
        targeting=9,
        keyword_coverage=9,
        bullet_quality=9,
        concision=9,
        completeness=9,
    )
    payload["unsupported_claims"] = ["Claims a 40% speedup that is nowhere in the profile"]
    assert weighted_overall(payload, RESUME_RUBRIC) <= 4.0


def test_failing_truthfulness_caps_the_overall_at_its_own_score():
    payload = verdict(
        truthfulness=2,
        targeting=10,
        keyword_coverage=10,
        bullet_quality=10,
        concision=10,
        completeness=10,
    )
    assert weighted_overall(payload, RESUME_RUBRIC) <= 2.0


def test_model_supplied_overall_is_ignored_when_criteria_exist():
    payload = verdict(
        truthfulness=5,
        targeting=5,
        keyword_coverage=5,
        bullet_quality=5,
        concision=5,
        completeness=5,
    )
    assert weighted_overall(payload, RESUME_RUBRIC) == 5.0


def test_falls_back_to_model_overall_when_no_criteria_returned():
    assert weighted_overall({"overall": 6.25}, RESUME_RUBRIC) == 6.25


def test_criterion_names_match_case_insensitively():
    payload = {
        "scores": [{"criterion": "Truthfulness", "score": 8.0, "justification": ""}],
    }
    assert weighted_overall(payload, RESUME_RUBRIC) == 8.0


def test_every_rubric_is_registered_under_its_subject_kind():
    for kind in (
        "resume",
        "cover_letter",
        "interview_prep",
        "follow_up",
        "job_ranking",
        "brief",
        "playbook",
    ):
        rubric = get_rubric(kind)
        assert rubric is not None, kind
        assert rubric.subject_kind == kind
        assert rubric.criteria, kind


def test_generative_artifacts_are_blocking_and_advisory_ones_are_not():
    assert all(
        get_rubric(kind).blocking
        for kind in ("resume", "cover_letter", "interview_prep", "follow_up")
    )
    assert not any(get_rubric(kind).blocking for kind in ("job_ranking", "brief", "playbook"))


class TestKeepsTheBestAttempt:
    """A revision that comes back worse must not destroy the good draft.

    The producer's `output_key` write replaces the artifact wholesale, so a
    second attempt that answers the critique with only the fields it changed
    used to overwrite a complete first draft — and get saved, because by then
    the revision budget was spent. Observed live: every artifact with
    `revisions=1` came back gutted, every one with `revisions=0` was complete.
    """

    @staticmethod
    def _gate(**kwargs):
        from tinternship_backend.agents.critic import QualityGate

        return QualityGate(
            name="gate",
            rubric=RESUME_RUBRIC,
            artifact_key="resume",
            verdict_key="resume_verdict",
            threshold=7.0,
            max_revisions=2,
            **kwargs,
        )

    @staticmethod
    async def _run(gate, state: dict) -> list:
        from unittest.mock import MagicMock

        ctx = MagicMock()
        ctx.session.state = state
        ctx.invocation_id = "inv"
        ctx.branch = None
        return [event async for event in gate._run_async_impl(ctx)]

    async def test_a_worse_revision_is_discarded(self):
        good = {"full_name": "Alex", "experiences": [{"title": "Intern"}]}
        gutted = {"full_name": "Alex", "experiences": []}
        gate = self._gate()

        # Round one: scores 5.0, below the bar, so it banks the draft and asks
        # for a revision.
        state = {"resume": good, "resume_verdict": verdict(**dict.fromkeys(
            ("truthfulness", "targeting", "keyword_coverage", "bullet_quality",
             "concision", "completeness", "language"), 5.0))}
        events = await self._run(gate, state)
        state.update(events[-1].actions.state_delta)
        assert state["_best_resume"] == good

        # Round two: the producer returns a gutted artifact that scores worse.
        state["resume"] = gutted
        state["resume_verdict"] = verdict(**dict.fromkeys(
            ("truthfulness", "targeting", "keyword_coverage", "bullet_quality",
             "concision", "completeness", "language"), 1.0))
        events = await self._run(gate, state)
        state.update(events[-1].actions.state_delta)

        assert state["resume"] == good, "the better attempt must be restored"
        assert "discarded" in events[-1].content.parts[0].text

    async def test_a_better_revision_is_kept(self):
        weak = {"full_name": "Alex", "experiences": []}
        strong = {"full_name": "Alex", "experiences": [{"title": "Intern"}]}
        gate = self._gate()

        state = {"resume": weak, "resume_verdict": verdict(**dict.fromkeys(
            ("truthfulness", "targeting", "keyword_coverage", "bullet_quality",
             "concision", "completeness", "language"), 4.0))}
        events = await self._run(gate, state)
        state.update(events[-1].actions.state_delta)

        state["resume"] = strong
        state["resume_verdict"] = verdict(**dict.fromkeys(
            ("truthfulness", "targeting", "keyword_coverage", "bullet_quality",
             "concision", "completeness", "language"), 9.0))
        events = await self._run(gate, state)
        state.update(events[-1].actions.state_delta or {})

        assert state["resume"] == strong
        assert "discarded" not in events[-1].content.parts[0].text

    async def test_state_from_an_earlier_run_does_not_leak_in(self):
        """The ADK session is reused per job, so gate bookkeeping outlives its run.

        Left alone, a second generation starts with the revision budget already
        spent — no revision ever happens — and a stale `_best_` could restore an
        artifact produced by a completely different run.
        """
        stale = {"full_name": "From an earlier run", "experiences": [{"title": "Old"}]}
        current = {"full_name": "Alex", "experiences": [{"title": "New"}]}
        gate = self._gate()

        state = {
            "resume": current,
            "resume_verdict": verdict(**dict.fromkeys(
                ("truthfulness", "targeting", "keyword_coverage", "bullet_quality",
                 "concision", "completeness", "language"), 5.0)),
            # Everything below belongs to a previous invocation.
            "_gate_invocation_resume": "an-older-invocation",
            "_revisions_resume": 1,
            "_best_resume": stale,
            "_best_score_resume": 9.9,
        }
        events = await self._run(gate, state)
        delta = events[-1].actions.state_delta

        # Budget starts fresh, so a below-bar artifact still gets its revision.
        assert "discarded" not in (events[-1].content.parts[0].text or "")
        assert delta["_revisions_resume"] == 1
        assert delta["_best_resume"] == current, "must not resurrect the earlier run's artifact"
        assert delta["_gate_invocation_resume"] == "inv"


class TestHardCheck:
    """Some requirements are facts, not opinions. The Critic scored `concision`
    7/10 on a résumé it had just been told to cap at 2, so "fits one page" is
    decided in Python and cannot be scored around."""

    @staticmethod
    def _gate(hard_check):
        from tinternship_backend.agents.critic import QualityGate

        return QualityGate(
            name="gate",
            rubric=RESUME_RUBRIC,
            artifact_key="resume",
            verdict_key="resume_verdict",
            threshold=7.0,
            max_revisions=2,
            hard_check=hard_check,
        )

    @staticmethod
    async def _run(gate, state):
        from unittest.mock import MagicMock

        ctx = MagicMock()
        ctx.session.state = state
        ctx.invocation_id = "inv"
        ctx.branch = None
        return [event async for event in gate._run_async_impl(ctx)]

    def _excellent(self):
        return verdict(**dict.fromkeys(
            ("truthfulness", "targeting", "keyword_coverage", "bullet_quality",
             "concision", "completeness", "language"), 10.0))

    async def test_a_violation_blocks_a_pass_however_high_the_score(self):
        gate = self._gate(lambda artifact: "It runs 6 lines past one page.")
        state = {"resume": {"full_name": "Alex"}, "resume_verdict": self._excellent()}

        events = await self._run(gate, state)

        # Scored 10/10, still sent back — and the feedback leads with the reason.
        text = events[-1].content.parts[0].text
        assert "hard requirement" in text
        assert "6 lines past one page" in text

    async def test_no_violation_passes_normally(self):
        gate = self._gate(lambda artifact: "")
        state = {"resume": {"full_name": "Alex"}, "resume_verdict": self._excellent()}

        events = await self._run(gate, state)
        assert "passed" in events[-1].content.parts[0].text

    async def test_a_clean_earlier_attempt_beats_a_higher_scoring_violation(self):
        clean = {"full_name": "Fits"}
        overlong = {"full_name": "Too long"}
        gate = self._gate(lambda artifact: "" if artifact == clean else "6 lines over.")

        # Round one banks the clean draft at a mediocre score.
        state = {"resume": clean, "resume_verdict": verdict(**dict.fromkeys(
            ("truthfulness", "targeting", "keyword_coverage", "bullet_quality",
             "concision", "completeness", "language"), 5.0))}
        events = await self._run(gate, state)
        state.update(events[-1].actions.state_delta)

        # Round two scores better but overruns the page — it must not win.
        state["resume"] = overlong
        state["resume_verdict"] = self._excellent()
        events = await self._run(gate, state)
        state.update(events[-1].actions.state_delta or {})

        assert state["resume"] == clean

    async def test_a_raising_check_does_not_take_the_run_down(self):
        def boom(artifact):
            raise RuntimeError("measurement exploded")

        gate = self._gate(boom)
        state = {"resume": {"full_name": "Alex"}, "resume_verdict": self._excellent()}
        events = await self._run(gate, state)
        assert "passed" in events[-1].content.parts[0].text

    async def test_a_violation_is_never_recorded_as_a_pass(self):
        """Otherwise the UI shows a green badge on something that broke a
        non-negotiable requirement — the audit has to say what happened."""
        from unittest.mock import patch

        gate = self._gate(lambda artifact: "6 lines over.")
        gate._max_revisions = 1  # stop on the first pass, budget spent
        state = {"resume": {"full_name": "Alex"}, "resume_verdict": self._excellent()}

        with patch.object(type(gate), "_persist", autospec=True) as persist:
            await self._run(gate, state)

        _self, _verdict, _overall, _revision, passed, _subject, violation = persist.call_args.args
        assert passed is False
        assert violation == "6 lines over."
