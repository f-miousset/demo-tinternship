"""A model that runs out of output tokens must not take the run with it.

The failure this file is aimed at happened on 2026-08-27, in production, and is
recorded in `documentation/decisions.md`. The Matcher was asked to re-emit all
eighteen fields of twenty-three postings alongside its scores; inside the
`deadline` string of the *first* one it started repeating itself, ran to
`MAX_TOKENS` at 65 537 output tokens, and answered with 235 000 characters of
JSON that stops mid-string. ADK validated that against `RankedJobList`, pydantic
raised `Invalid JSON: EOF while parsing a string`, and the exception travelled
up through the `SequentialAgent` and `runtime.stream` — ending a six-minute run
that had already paid for a 149-second grounded search, and showing the
candidate an error naming a pydantic documentation URL.

It happened twice in one day, and the second time was the first fix's own
fault: with the Matcher answering `index` as an **integer**, the same
repetition pathology landed inside the join key, and a corrupt join key loses
the whole verdict where a corrupt `deadline` only spoiled one field. The key is
now an enum of the hundred index strings, which makes that unreachable rather
than unlikely — see `TestTheJoinKeyCannotRunAway`.

Four defences, tested here in the order they act:

* the Matcher answers with a **number and a verdict** rather than a copy of the
  posting, so there is roughly a tenth as much to say and none of it is a field
  it has anything to add to (`numbered` / `merge_scores`);
* a response that is cut off anyway is **salvaged** down to the postings that
  arrived whole (`agents/salvage.py`);
* a ranking that comes back empty with no explanation is **scored again** from
  the postings already in session state, rather than reported as "nothing
  found" (`flows._score_again`);
* and the whole answer is bounded, so a model that derails is stopped in
  seconds rather than after six minutes and 65 537 tokens (`answer_budget`).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from google.adk.utils._schema_utils import validate_schema
from google.genai import types

from tinternship_backend.agents import salvage
from tinternship_backend.agents.investigator import (
    NORMALISED_STATE_KEY,
    RANKED_STATE_KEY,
    _rejoin,
    answer_budget,
    merge_scores,
    numbered,
)
from tinternship_backend.agents.schemas import MAX_SCOREABLE, JobAssessment, ScoredJobList
from tinternship_backend.services import flows


def truncated_like_the_incident() -> str:
    """The shape of the real response: whole postings, then one cut mid-string."""
    whole = [
        {
            "index": str(index),
            "fit_score": 8.0,
            "fit_rationale": "cites specifics",
            "strengths": ["Python"],
            "risks": [],
            "keywords": ["Python"],
            "confidence": "high",
        }
        for index in range(3)
    ]
    body = ",\n".join(json.dumps(item) for item in whole)
    return '{\n  "jobs": [\n' + body + ',\n{"index": "3", "fit_rationale": "' + "loop " * 200


class TestSalvage:
    def test_keeps_every_element_that_arrived_whole(self) -> None:
        items = salvage.complete_items(truncated_like_the_incident(), "jobs")
        assert items is not None
        assert [item["index"] for item in items] == ["0", "1", "2"]

    def test_drops_the_element_that_was_cut_rather_than_closing_its_quotes(self) -> None:
        # Half a string is not a shorter answer, it is a wrong one: the model was
        # mid-word, and whatever it was writing would be saved as fact.
        repaired = salvage.repair(truncated_like_the_incident(), "jobs")
        assert repaired is not None
        assert "loop loop" not in repaired

    def test_the_salvaged_text_passes_the_validation_that_raised(self) -> None:
        # The exact call ADK makes on the way to `output_key`, and the one that
        # ended the run. It has to come back with data, not an exception.
        repaired = salvage.repair(truncated_like_the_incident(), "jobs")
        assert repaired is not None
        validated = validate_schema(ScoredJobList, repaired)
        assert len(validated["jobs"]) == 3

    def test_a_response_cut_inside_its_first_element_salvages_an_empty_list(self) -> None:
        # What actually happened: the loop was in posting one, so nothing
        # survives. An empty list is still a valid answer the run can act on —
        # `flows` scores the postings again rather than saving nothing.
        assert salvage.complete_items('{"jobs": [{"index": "0", "fit_rationale": "and on', "jobs") == []

    def test_brackets_and_escapes_inside_strings_are_not_structure(self) -> None:
        text = '{"jobs": [{"note": "a [bracket] and a \\"quote\\" and a }"}, {"note": "'
        items = salvage.complete_items(text, "jobs")
        assert items == [{"note": 'a [bracket] and a "quote" and a }'}]

    @pytest.mark.parametrize(
        "text",
        [
            "I could not find any postings.",
            '{"notes": "no list here"}',
            "",
        ],
    )
    def test_something_that_is_not_a_truncated_list_is_left_alone(self, text: str) -> None:
        # `None` is "keep the response as it was". Replacing a failure we do not
        # understand with an empty list would turn a loud error into a silent
        # wrong answer.
        assert salvage.repair(text, "jobs") is None

    def test_a_fenced_response_is_unwrapped_like_adk_unwraps_it(self) -> None:
        assert salvage.unfenced('```json\n{"jobs": []}\n```') == '{"jobs": []}'


class TestSalvageCallback:
    """`keep_what_arrived` as ADK calls it: an `after_model_callback`."""

    @staticmethod
    def response(text: str) -> Any:
        return SimpleNamespace(
            partial=False,
            finish_reason="MAX_TOKENS",
            content=types.Content(role="model", parts=[types.Part(text=text)]),
            model_copy=lambda update: SimpleNamespace(**{"content": update["content"]}),
        )

    @staticmethod
    def context() -> Any:
        return SimpleNamespace(agent_name="matcher")

    async def test_a_valid_response_is_untouched(self) -> None:
        callback = salvage.keep_what_arrived("jobs")
        assert await callback(
            callback_context=self.context(),
            llm_response=self.response('{"jobs": [{"index": "0"}], "strategy_notes": "fine"}'),
        ) is None

    async def test_a_truncated_response_comes_back_valid(self) -> None:
        callback = salvage.keep_what_arrived("jobs")
        altered = await callback(
            callback_context=self.context(),
            llm_response=self.response(truncated_like_the_incident()),
        )
        assert altered is not None
        text = "".join(part.text for part in altered.content.parts)
        assert len(json.loads(text)["jobs"]) == 3


class TestTheJoinKeyCannotRunAway:
    """The second incident, on the same day, in the field the first fix added.

    Asked for the join key as an integer, the model answered `"index": 8` and
    then wrote zeros for sixteen thousand characters — twice in three runs,
    `finish_reason: STOP` both times, so nothing was truncated and nothing was
    salvageable: the JSON was valid and every verdict in it named a posting
    that does not exist. Under constrained decoding an integer has no stopping
    rule, because one more digit is always still an integer.
    """

    def test_the_index_is_an_enum_of_values_and_not_a_number(self) -> None:
        field = ScoredJobList.model_json_schema()["$defs"]["ScoredPosting"]["properties"]["index"]
        # The grammar, not the prompt, is what stops it: after `"1` the decoder
        # may only close the quote or reach another listed value.
        assert field["type"] == "string"
        assert field["enum"] == [str(number) for number in range(MAX_SCOREABLE)]

    def test_every_posting_the_matcher_is_shown_has_a_name_it_can_answer_with(self) -> None:
        # The enum is written down in advance, so the list has to be cut to it:
        # a posting past the end would be one the matcher cannot name at all.
        crowded = [{"title": f"J{n}"} for n in range(MAX_SCOREABLE + 25)]
        listed = numbered({NORMALISED_STATE_KEY: {"jobs": crowded}})
        assert len(listed) == MAX_SCOREABLE

        schema = ScoredJobList.model_json_schema()["$defs"]["ScoredPosting"]
        allowed = set(schema["properties"]["index"]["enum"])
        assert {job["index"] for job in listed} <= allowed

    def test_the_answer_has_a_ceiling_that_grows_with_the_ask(self) -> None:
        # A bound on the wrong answer, not a guess at the right one: a verdict
        # costs about eighty tokens, so this is roughly five times a full list.
        assert answer_budget(15) == 10_000
        assert answer_budget(60) > answer_budget(15)


class TestTheVerdictIsNotOptional:
    """The third thing that day, and the quietest.

    With `index` as the only required field, the Matcher — given the real
    brief, the real playbook and ten real postings — returned ten indices in a
    well-judged order, wrote a `strategy_notes` citing the candidate's own
    projects, and left every `fit_score` at 0.0 and every `fit_rationale`
    empty. It had done the work and declined to write it down, because the
    schema allowed it to. Nothing would have raised: the deck would simply have
    shown ten postings scored zero.
    """

    def test_scoring_a_posting_means_filling_in_the_verdict(self) -> None:
        required = set(ScoredJobList.model_json_schema()["$defs"]["ScoredPosting"]["required"])
        assert required == {
            "index", "fit_score", "fit_rationale", "strengths", "risks", "keywords", "confidence",
        }

    def test_the_pasted_link_scorer_is_held_to_the_same_thing(self) -> None:
        # Same rule, same reason: `JobAssessment` is what the one-posting
        # scorer returns, and "never return an empty result" is a promise its
        # prompt makes that only the schema can keep.
        required = set(JobAssessment.model_json_schema()["required"])
        assert "fit_rationale" in required and "fit_score" in required


class TestScoresRejoinTheirPostings:
    postings = [
        {"title": "One", "company": "A", "url": "https://a.test/1", "posted_at": ""},
        {"title": "Two", "company": "B", "url": "https://b.test/2", "posted_at": ""},
        {"title": "Three", "company": "C", "url": "https://c.test/3", "posted_at": ""},
    ]

    def test_the_matcher_is_shown_a_numbered_list_with_the_age_worked_out(self) -> None:
        state = {NORMALISED_STATE_KEY: {"jobs": self.postings}}
        listed = numbered(state)
        # Strings, matching the enum the matcher answers from: the token it
        # copies is the token it was shown.
        assert [job["index"] for job in listed] == ["0", "1", "2"]
        # The ranking rule is written against this number, so it is computed
        # here rather than asked of a model.
        assert all("posted_days_ago" in job for job in listed)

    def test_a_verdict_lands_on_the_posting_its_index_names(self) -> None:
        merged = merge_scores(
            numbered({NORMALISED_STATE_KEY: {"jobs": self.postings}}),
            [{"index": "2", "fit_score": 9.0}, {"index": "0", "fit_score": 4.0}],
        )
        # In the matcher's order, carrying the posting's own facts — which it
        # never had to retype — and none of the join key.
        assert [job["title"] for job in merged] == ["Three", "One"]
        assert [job["fit_score"] for job in merged] == [9.0, 4.0]
        assert merged[0]["url"] == "https://c.test/3"
        assert "index" not in merged[0]

    @pytest.mark.parametrize(
        "verdicts",
        [
            [{"index": "7", "fit_score": 9.0}],
            [{"index": "-1", "fit_score": 9.0}],
            [{"fit_score": 9.0}],
            [{"index": "second", "fit_score": 9.0}],
            [{"index": "8" + "0" * 400, "fit_score": 9.0}],
        ],
        ids=["out of range", "negative", "missing", "not a number", "a digit that ran away"],
    )
    def test_a_verdict_that_names_no_posting_is_dropped(self, verdicts: list[dict]) -> None:
        # A score on the wrong posting reads as a considered answer, which is
        # worse than a posting that quietly did not make the list.
        assert merge_scores(numbered({NORMALISED_STATE_KEY: {"jobs": self.postings}}), verdicts) == []

    def test_two_verdicts_cannot_claim_one_posting(self) -> None:
        merged = merge_scores(
            numbered({NORMALISED_STATE_KEY: {"jobs": self.postings}}),
            [{"index": "1", "fit_score": 9.0}, {"index": "1", "fit_score": 2.0}],
        )
        assert [job["fit_score"] for job in merged] == [9.0]

    @pytest.mark.parametrize(
        "state",
        [{}, {NORMALISED_STATE_KEY: "not a dict"}, {NORMALISED_STATE_KEY: {"jobs": None}}],
    )
    def test_a_state_with_no_postings_renders_an_empty_list(self, state: dict) -> None:
        # `build_matcher` renders its instruction against whatever state exists,
        # including none at all — see `test_agent_wiring.py`.
        assert numbered(state) == []


    def test_the_agent_leaves_postings_in_state_not_scores(self) -> None:
        # `_rejoin` is where the two halves meet in a live run: ADK's
        # `output_key` has just written the matcher's scores to `ranked_jobs`,
        # and this replaces them with the merged rows before the run moves on,
        # so nothing downstream of the agent layer knows the matcher answers in
        # numbers.
        state = {
            NORMALISED_STATE_KEY: {"jobs": self.postings},
            RANKED_STATE_KEY: {
                "jobs": [{"index": "1", "fit_score": 7.5}],
                "strategy_notes": "one clear winner",
            },
        }
        _rejoin(SimpleNamespace(state=state))

        ranked = state[RANKED_STATE_KEY]
        assert ranked["strategy_notes"] == "one clear winner"
        assert [job["title"] for job in ranked["jobs"]] == ["Two"]
        assert ranked["jobs"][0]["fit_score"] == 7.5
        assert ranked["jobs"][0]["url"] == "https://b.test/2"
        assert "index" not in ranked["jobs"][0]


class TestScoringRunsAgainRatherThanSavingNothing:
    """The last defence: postings found, nothing scored, no reason given."""

    @staticmethod
    def _run(monkeypatch: pytest.MonkeyPatch, ranked: dict[str, Any], second: dict[str, Any]) -> dict:
        seen: dict[str, Any] = {"scored_again": 0}

        async def fake_stream(agent, **kwargs):
            yield ("run", {"run_id": 1, "session_id": "investigator", "kind": "investigator"})
            yield (
                "state",
                {
                    NORMALISED_STATE_KEY: {"jobs": [{"title": "One", "url": "https://a.test/1"}]},
                    RANKED_STATE_KEY: ranked,
                },
            )
            yield ("done", {"run_id": 1, "text": "", "invocation_id": "inv-1"})

        async def fake_execute(agent, **kwargs):
            seen["scored_again"] += 1
            seen["label"] = kwargs.get("label")
            return SimpleNamespace(state={RANKED_STATE_KEY: second}, run_id=2)

        async def fake_verify(jobs):
            return [{**job, "url_status": "ok"} for job in jobs], {}

        async def fake_nothing(*_args, **_kwargs):
            return {}

        monkeypatch.setattr(flows, "stream", fake_stream)
        monkeypatch.setattr(flows, "execute", fake_execute)
        monkeypatch.setattr(flows.verification, "verify_jobs", fake_verify)
        monkeypatch.setattr(flows, "build_digest", fake_nothing)
        monkeypatch.setattr(flows, "audit_artifact", fake_nothing)
        monkeypatch.setattr(flows, "save_job_postings", lambda jobs: {"saved": len(jobs)})
        return seen

    async def test_an_empty_ranking_with_no_explanation_is_scored_again(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._run(
            monkeypatch,
            ranked={"jobs": [], "strategy_notes": ""},
            second={"jobs": [{"title": "One", "url": "https://a.test/1", "fit_score": 8.0}]},
        )
        result = await flows.run_investigator(target_results=5)

        assert seen["scored_again"] == 1
        # And the run finishes normally on the second answer, rather than
        # reporting that the searches found nothing.
        assert [job["title"] for job in result["jobs"]] == ["One"]

    async def test_a_matcher_that_explains_itself_is_believed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # "All of these were already on your list" is an answer, not a failure.
        seen = self._run(
            monkeypatch,
            ranked={"jobs": [], "strategy_notes": "Both postings are already on the list."},
            second={"jobs": [{"title": "One", "url": "https://a.test/1"}]},
        )
        result = await flows.run_investigator(target_results=5)

        assert seen["scored_again"] == 0
        assert result["jobs"] == []

    async def test_a_second_failure_says_so_instead_of_saving_an_empty_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._run(monkeypatch, ranked={"jobs": []}, second={"jobs": []})

        with pytest.raises(flows.RunFailed, match="cut short"):
            await flows.run_investigator(target_results=5)
