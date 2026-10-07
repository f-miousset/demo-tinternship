"""How many postings one Investigator run comes back with.

The count is the Jobs page slider. The prompts ask for it, but the guarantee is
in Python — `run_investigator` truncates the ranked list — so these tests pin
the clamp, the query budget derived from the target, and the fact that the
prompts actually carry the number they were built with.
"""

from __future__ import annotations

import pytest

from tinternship_backend.agents.investigator import (
    MAX_RESULTS,
    MIN_RESULTS,
    build_matcher,
    build_query_planner,
    build_scout,
    clamp_results,
    query_budget,
)
from tinternship_backend.config import get_settings


def test_default_comes_from_settings() -> None:
    assert clamp_results() == get_settings().results_per_run


@pytest.mark.parametrize(
    ("asked", "expected"),
    [(0, MIN_RESULTS), (1, MIN_RESULTS), (5, 5), (20, 20), (40, 40), (999, MAX_RESULTS)],
)
def test_clamp_keeps_the_target_in_range(asked: int, expected: int) -> None:
    assert clamp_results(asked) == expected


def test_query_budget_grows_with_the_target() -> None:
    small = query_budget(MIN_RESULTS)
    large = query_budget(MAX_RESULTS)
    assert small[0] < large[0]
    assert all(low < high for low, high in (small, large))


def test_query_budget_has_a_floor_and_a_ceiling() -> None:
    # A tiny run still needs enough queries to cover the priority platforms;
    # a huge one must not spend an unbounded number of grounded searches.
    assert query_budget(MIN_RESULTS)[0] == 10
    assert query_budget(MAX_RESULTS)[0] == 20


def test_default_target_reproduces_the_original_query_budget() -> None:
    # 12–16 was the hand-tuned budget before the slider existed; the default
    # must not silently change what a plain run does.
    assert query_budget(15) == (12, 16)


async def test_prompts_carry_the_target() -> None:
    class Ctx:
        state: dict[str, object] = {}

    planner = await build_query_planner(25).instruction(Ctx())
    assert "25 ranked postings" in planner
    low, high = query_budget(25)
    assert f"**{low}–{high}" in planner

    scout = await build_scout(25).instruction(Ctx())
    assert "at least 38 distinct real postings" in scout  # 1.5x the target

    matcher = await build_matcher(25).instruction(Ctx())
    assert "top 25" in matcher


async def test_no_placeholder_survives_into_a_prompt() -> None:
    """A `.format()` key left unfilled would reach the model as literal braces."""

    class Ctx:
        state: dict[str, object] = {}

    for text in (
        await build_query_planner(10).instruction(Ctx()),
        await build_scout(10).instruction(Ctx()),
        await build_matcher(10).instruction(Ctx()),
    ):
        for key in ("{results}", "{low}", "{high}", "{leads}", "{honesty}"):
            assert key not in text, (key, text[:200])
