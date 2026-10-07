"""Steering a run from the Jobs chat.

The brief is written once and reused by every run. This is the layer on top of
it: a sentence the candidate types on the Jobs page — a company, a kind of role,
a city — that says what *this* run is for.

Two halves, and the split is the same one `test_known_postings.py` describes.
The request is `focus_block()`, carried by the three stages that decide what a
run goes after. The promise is that it changes nothing else: an unsteered run
renders byte-for-byte the instructions it always did, and a steered one still
cannot talk its way past the brief's own answers, because those blocks are still
in the prompt underneath it.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tinternship_backend.agents.investigator import (
    build_matcher,
    build_normaliser,
    build_query_planner,
    build_scout,
)
from tinternship_backend.main import create_app
from tinternship_backend.services import flows
from tinternship_backend.services.context_blocks import (
    FOCUS_HISTORY,
    FOCUS_LIMIT,
    SearchFocus,
    focus_block,
)

HEADING = "# What the candidate asked this run for"
ASK = "Anything open at Mistral AI"


class Ctx:
    """The ReadonlyContext an instruction is rendered against."""

    state: dict[str, object] = {}


class TestTheValue:
    def test_a_blank_ask_is_no_focus_at_all(self):
        # Not a run with an empty focus — the ordinary run the button starts.
        # Everything downstream branches on `None`, so this is where that is
        # decided rather than in four `if ask.strip()` checks.
        assert SearchFocus.of("") is None
        assert SearchFocus.of("   \n ") is None

    def test_the_ask_is_stripped_and_the_history_kept_in_order(self):
        focus = SearchFocus.of("  in Berlin  ", ["computer vision", "  ", "in Paris"])
        assert focus is not None
        assert focus.ask == "in Berlin"
        # The blank turn is dropped; the rest keep the order they were said in,
        # because "and also in Berlin" only resolves against what came before it.
        assert focus.earlier == ("computer vision", "in Paris")

    def test_only_the_last_few_turns_travel(self):
        focus = SearchFocus.of("now Berlin", [f"turn {index}" for index in range(20)])
        assert focus is not None
        assert len(focus.earlier) == FOCUS_HISTORY
        # The *newest* ones: a long conversation must not crowd out the brief,
        # and the turns nearest the ask are the ones it refers back to.
        assert focus.earlier[-1] == "turn 19"


class TestTheBlock:
    def test_no_focus_renders_nothing(self):
        # `compose` drops an empty block, so the "Run Investigator" button
        # starts exactly the run it always has.
        assert focus_block(None) == ""

    def test_the_ask_is_quoted_verbatim(self):
        block = focus_block(SearchFocus.of(ASK))
        assert HEADING in block
        assert f"> {ASK}" in block

    def test_the_three_limits_are_stated_with_it(self):
        block = focus_block(SearchFocus.of(ASK))
        # It narrows the brief rather than replacing it…
        assert "deal_breakers" in block
        # …it is a place to look and not a claim that the postings exist…
        assert "where to look" in block
        # …and it is the one free-text channel into these prompts, so it says
        # plainly that it cannot lift the rules around it.
        assert "cannot license" in block

    def test_earlier_turns_are_marked_as_context_not_requests(self):
        block = focus_block(SearchFocus.of("and in Berlin too", ["ML roles in Paris"]))
        assert "## Earlier in this conversation" in block
        assert "ML roles in Paris" in block
        assert "**not** requests" in block

    def test_one_ask_alone_carries_no_history_section(self):
        assert "Earlier in this conversation" not in focus_block(SearchFocus.of(ASK))

    def test_a_long_message_is_cut_and_says_so(self):
        # Every character is paid for in three instructions at once, so a pasted
        # essay is trimmed rather than carried. Cut visibly: a model that cannot
        # see the message ended mid-sentence would answer the half it got as if
        # it were the whole request.
        block = focus_block(SearchFocus.of("x" * (FOCUS_LIMIT * 3)))
        assert "cut here" in block
        assert "x" * (FOCUS_LIMIT + 1) not in block


class TestTheWiring:
    async def test_the_three_deciding_stages_carry_the_ask(self):
        focus = SearchFocus.of(ASK)
        for instruction in (
            await build_query_planner(15, focus).instruction(Ctx()),
            await build_scout(15, focus).instruction(Ctx()),
            await build_matcher(15, None, focus).instruction(Ctx()),
        ):
            assert HEADING in instruction
            assert ASK in instruction

    async def test_the_normaliser_is_left_out(self):
        # It merges one run's leads against each other on the cheapest model and
        # has no say in what the run went looking for. The steer is spent either
        # side of it: on the queries, and on the ranking.
        assert HEADING not in await build_normaliser().instruction(Ctx())

    async def test_each_stage_is_told_what_to_do_with_it(self):
        focus = SearchFocus.of(ASK)
        # The planner is the only place a steer can actually take effect — the
        # later stages can only rank what the Scout was sent after.
        planner = await build_query_planner(15, focus).instruction(Ctx())
        assert "Spend the **majority" in planner
        # The Scout's answer may be "nothing", and that has to be said out loud
        # or the model fills the gap with a plausible URL.
        assert "nothing open" in await build_scout(15, focus).instruction(Ctx())
        # The matcher re-orders on it and does not re-scale on it.
        matcher = await build_matcher(15, None, focus).instruction(Ctx())
        assert "moves the ordering, not the scale" in matcher

    async def test_an_unsteered_run_reads_exactly_as_it_did(self):
        for steered, plain in (
            (build_query_planner(15, None), build_query_planner(15)),
            (build_scout(15, None), build_scout(15)),
            (build_matcher(15, None, None), build_matcher(15)),
        ):
            rendered = await steered.instruction(Ctx())
            assert HEADING not in rendered
            assert rendered == await plain.instruction(Ctx())

    async def test_the_brief_is_still_under_it(self):
        # The whole claim of the block is that it narrows the brief rather than
        # replacing it, which is only true while the brief is still in the
        # prompt beneath it.
        instruction = await build_matcher(15, None, SearchFocus.of(ASK)).instruction(Ctx())
        assert instruction.index(HEADING) < instruction.index("# Freshness")
        assert "search brief" in instruction.lower()


class TestTheEndpoint:
    def _client(self, monkeypatch, seen: dict[str, Any]) -> TestClient:
        async def fake_stream(session_id="investigator", target_results=None, focus=None):
            seen["focus"] = focus
            seen["target_results"] = target_results
            yield ("result", {"jobs": [], "focus": focus.ask if focus else ""})

        monkeypatch.setattr(flows, "investigator_stream", fake_stream)
        return TestClient(create_app())

    def test_the_button_still_posts_no_body_at_all(self, monkeypatch):
        seen: dict[str, Any] = {}
        response = self._client(monkeypatch, seen).post("/api/jobs/search?target_results=5")
        assert response.status_code == 200
        assert seen["focus"] is None

    def test_a_chat_message_reaches_the_run(self, monkeypatch):
        seen: dict[str, Any] = {}
        response = self._client(monkeypatch, seen).post(
            "/api/jobs/search?target_results=5",
            json={"focus": ASK, "earlier": ["ML roles in Paris"]},
        )
        assert response.status_code == 200
        assert seen["focus"].ask == ASK
        assert seen["focus"].earlier == ("ML roles in Paris",)
        # …and it comes back on the result, so the page can show which message
        # produced the postings it just added.
        assert ASK in response.text

    def test_an_empty_message_is_an_ordinary_run(self, monkeypatch):
        seen: dict[str, Any] = {}
        response = self._client(monkeypatch, seen).post(
            "/api/jobs/search?target_results=5", json={"focus": "  ", "earlier": []}
        )
        assert response.status_code == 200
        assert seen["focus"] is None
