"""The Investigator: discover → normalise → rank.

A `SequentialAgent` of three specialists rather than one agent doing everything,
because each stage wants a different model tier and a different failure mode:

* **scout** — expensive model, tools on, deliberately high recall.
* **normaliser** — cheap model, no tools, mechanical cleanup and dedup.
* **matcher** — expensive model, no tools, the judgement call that actually
  matters.

The first two stages also carry the priority platforms
(`tools/job_sources/platforms.py`): the planner must open its list with queries
against them, and the Scout must run those first. That is the entire wiring —
these boards have no API worth depending on, so "search here first" is a prompt
contract, kept honest by the fact that every URL still has to come back from a
real search result.

All four carry `recency_block()`, because a model does not know what day it is
and every stage here depends on that: which season to search for, what `3 days
ago` resolves to, whether a posting is stale. The block is one policy stated
once, so the four cannot disagree about it — and `services/recency.py` re-sorts
the ranking on the same numbers afterwards, because a prompt is a request and
"the freshest of two equal matches wins" is a promise.

Three of them also carry `known_postings_block()` — the postings already on the
candidate's page. A run adds to that list rather than rebuilding it, and every
run works from the same brief, so without it the planner writes the queries that
already worked, the Scout finds the postings those return, and the matcher
spends the run's slots re-ranking rows that exist. Naming them sends the run
after what is missing instead. It is a request, though: the promise that nothing
already saved is lost lives in `tools/persistence.py`, which never deletes a
posting.

Those same three carry `focus_block()` when the candidate used the chat on the
Jobs page to ask for something in particular — a company, a kind of role, a
city. The brief is written once and reused by every run; this is the layer on
top of it, and it rides the deciding stages rather than the ranking alone
because a posting the searches never went after cannot be ranked into the list
afterwards. The block is absent on an ordinary run, so the button starts exactly
the run it always has.

The matcher is handed the normalised postings **numbered**, and answers with a
number and a verdict rather than a copy of the posting (`schemas.ScoredPosting`).
`merge_scores` puts the two back together, so `ranked_jobs` still holds whole
postings and nothing downstream knows the difference. A stage with no facts to
add is not asked to retype eighteen fields it was handed — which is what one did
until it looped inside a `deadline` string on 2026-08-27 and ran a whole run out
of output tokens.

Persistence is done in Python by the service layer after the run, not by a tool
the matcher has to remember to call. Joining is the same rule: agents produce,
Python assembles.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.tools.google_search_tool import GoogleSearchTool
from google.genai import types

from ..config import get_settings
from ..services.context_blocks import (
    SearchFocus,
    brief_block,
    compose,
    feedback_block,
    focus_block,
    known_postings_block,
    platform_block,
    platform_domains_block,
    playbook_block,
    profile_block,
    recency_block,
)
from ..services.recency import with_age
from ..tools.job_sources.registry import search_job_board, source_names
from . import salvage
from .models import grounded, resolve
from .prompts import (
    DISCOVERY_INSTRUCTION,
    NORMALISE_INSTRUCTION,
    QUERY_PLANNER_INSTRUCTION,
    RANK_INSTRUCTION,
)
from .schemas import MAX_SCOREABLE, NormalisedJobList, ScoredJobList

logger = logging.getLogger(__name__)

QUERY_PLAN_STATE_KEY = "search_queries"
DISCOVERY_STATE_KEY = "discovery_leads"
NORMALISED_STATE_KEY = "normalised_jobs"
RANKED_STATE_KEY = "ranked_jobs"

# How many postings one run may be asked for. The floor is not politeness: a
# run that returns two postings has told you almost nothing about the market,
# and the ceiling keeps a mis-drag on the slider from launching forty grounded
# searches.
MIN_RESULTS = 5
MAX_RESULTS = 40


def clamp_results(target: int | None = None) -> int:
    """The result target for a run, defaulting to `RESULTS_PER_RUN` in `.env`."""
    if target is None:
        target = get_settings().results_per_run
    return max(MIN_RESULTS, min(MAX_RESULTS, int(target)))


def rank_target(target_results: int) -> int:
    """How many postings the matcher is asked for — more than the user gets.

    A posting whose link is dead, or opens the company's careers page instead of
    the job, is dropped rather than shown. That only helps if something takes
    its place, so the ranking is asked for spares: half again, floored at five.
    The floor is what a small run needs; the proportion is what a real run
    measured — seven of thirteen links in one saved run did not reach a posting.

    `investigator_stream` still returns exactly `target_results`. This is the
    margin it spends on links that turn out to be broken.
    """
    return target_results + max(5, round(target_results * 0.5))


def query_budget(target_results: int) -> tuple[int, int]:
    """How many queries to plan for a given result target.

    The floor matters more than the target: the priority platforms alone want
    two queries each, and below about ten queries the Scout stops surfacing
    anything the first page of a generic search would not. The ceiling exists
    because grounded searches are the expensive part of a run — past twenty
    queries the marginal one mostly returns postings the others already found.
    """
    low = max(10, min(20, round(target_results * 0.8)))
    return low, low + 4


def build_query_planner(
    target_results: int, focus: SearchFocus | None = None
) -> LlmAgent:
    """Writes the queries, so the Scout has no excuse to answer from memory.

    Splitting this out matters: given the brief and the playbook in one prompt,
    the Scout would happily confabulate a plausible list of postings without
    searching at all. Handing it an explicit query list turns "find some jobs"
    into "run these searches and report what came back".
    """
    settings = get_settings()
    low, high = query_budget(target_results)

    async def instruction(_ctx: ReadonlyContext) -> str:
        return compose(
            QUERY_PLANNER_INSTRUCTION.format(results=target_results, low=low, high=high),
            focus_block(focus),
            recency_block(),
            platform_block(),
            brief_block(),
            playbook_block(),
            known_postings_block(),
        )

    return LlmAgent(
        name="query_planner",
        model=resolve(settings.model_fast),
        description="Writes the search queries the Scout will run.",
        instruction=instruction,
        output_key=QUERY_PLAN_STATE_KEY,
    )


def build_scout(target_results: int, focus: SearchFocus | None = None) -> LlmAgent:
    # Over-collect: the normaliser drops duplicates and junk, and the matcher
    # filters on fit, so the Scout has to hand over more than the target. Half
    # again is the most a realistic query budget can actually surface — asking
    # for double invites the padding the rest of the prompt spends its length
    # forbidding.
    lead_target = round(target_results * 1.5)
    tools: list[Any] = [GoogleSearchTool(bypass_multi_tools_limit=True)]
    if source_names():
        tools.append(search_job_board)

    async def instruction(ctx: ReadonlyContext) -> str:
        available = source_names()
        source_note = (
            f"Structured job boards available via `search_job_board`: {', '.join(available)}."
            if available
            else "No structured job board is configured — google_search is your only source."
        )
        plan = ctx.state.get(QUERY_PLAN_STATE_KEY, "")
        return compose(
            DISCOVERY_INSTRUCTION.format(leads=lead_target),
            focus_block(focus),
            recency_block(),
            f"## Query plan — run every one of these\n\n{plan}",
            platform_block(),
            brief_block(),
            known_postings_block(),
            f"## Sources\n\n{source_note}",
        )

    return LlmAgent(
        name="scout",
        # Google Search is a Gemini server-side tool — see agents/models.py.
        model=resolve(grounded()),
        description="Searches the web and job boards for candidate postings.",
        instruction=instruction,
        tools=tools,
        output_key=DISCOVERY_STATE_KEY,
    )


def build_normaliser() -> LlmAgent:
    settings = get_settings()

    async def instruction(ctx: ReadonlyContext) -> str:
        leads = ctx.state.get(DISCOVERY_STATE_KEY, "")
        return compose(
            NORMALISE_INSTRUCTION,
            # This stage is the one that turns "3 days ago" into a date, so it
            # needs today's date more than any of the others.
            recency_block(),
            platform_domains_block(),
            brief_block(),
            f"# Raw leads from the Scout\n\n{leads}",
        )

    return LlmAgent(
        name="normaliser",
        model=resolve(settings.model_fast),
        description="Cleans and de-duplicates raw leads into structured postings.",
        instruction=instruction,
        output_schema=NormalisedJobList,
        output_key=NORMALISED_STATE_KEY,
        include_contents="none",
        # This one writes the longest list in the pipeline — every lead the
        # Scout found, in full — so it is the other stage that can run out of
        # output tokens mid-posting. Twelve clean postings beat a lost run.
        after_model_callback=salvage.keep_what_arrived("jobs"),
    )


def numbered(state: Any) -> list[dict[str, Any]]:
    """The normalised postings as the matcher is shown them: aged, and numbered.

    The number is the whole join. A posting is identified to the matcher by its
    `index` and comes back carrying that index and nothing else of itself, which
    is what keeps a stage that has no facts to add from re-typing eighteen
    fields it was handed — see `schemas.ScoredPosting`.

    It is a *string*, matching the enum the matcher answers from, so the token
    it copies is the token it was shown. And the list is cut at `MAX_SCOREABLE`,
    because that enum has to be written down in advance: a posting past the end
    of it would be one the matcher has no way to name. Sixty is as long as a
    real run's list gets, so the cut is headroom being enforced rather than a
    limit being hit.
    """
    jobs = state.get(NORMALISED_STATE_KEY, {}) if hasattr(state, "get") else {}
    listed = jobs.get("jobs") if isinstance(jobs, dict) else None
    if not isinstance(listed, list):
        return []
    postings = [job for job in listed if isinstance(job, dict)]
    if len(postings) > MAX_SCOREABLE:
        logger.warning(
            "Normaliser returned %d postings; scoring the first %d",
            len(postings), MAX_SCOREABLE,
        )
        postings = postings[:MAX_SCOREABLE]
    # Hand the matcher the age rather than the arithmetic. Asking a model to
    # subtract dates across a list is a reliable source of quiet errors, and
    # this is the number its ranking rule is written against.
    return [{"index": str(index), **job} for index, job in enumerate(with_age(postings))]


def merge_scores(
    postings: list[dict[str, Any]], scored: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Put each verdict back on the posting it judged, in the matcher's order.

    The counterpart of `numbered()`, and the reason the matcher may answer with
    scores alone. A verdict whose `index` names no posting — or names one a
    previous verdict already claimed — is dropped and logged rather than
    guessed at: a score attached to the wrong posting is worse than a posting
    that quietly did not make the list, because it reads as a considered answer.
    """
    merged: list[dict[str, Any]] = []
    claimed: set[int] = set()
    for verdict in scored:
        if not isinstance(verdict, dict):
            continue
        try:
            index = int(verdict.get("index", -1))
        except (TypeError, ValueError):
            index = -1
        if not 0 <= index < len(postings):
            logger.warning(
                "Matcher scored posting %r, which is not one of the %d it was given",
                verdict.get("index"), len(postings),
            )
            continue
        if index in claimed:
            logger.warning("Matcher scored posting %d twice; keeping the first verdict", index)
            continue
        claimed.add(index)
        posting = {key: value for key, value in postings[index].items() if key != "index"}
        merged.append({**posting, **{k: v for k, v in verdict.items() if k != "index"}})
    return merged


def _rejoin(callback_context: CallbackContext) -> None:
    """Turn the matcher's scores back into postings, in session state.

    `output_key` has just written the scores to `ranked_jobs`; this overwrites
    them with the merged rows before the run moves on, so `ranked_jobs` means
    what it has always meant — `RankedJobList`, postings with their verdict —
    and nothing downstream of the agent layer knows the matcher answers in
    numbers. Python does the joining, exactly as it does the persisting.
    """
    state = callback_context.state
    scored = state.get(RANKED_STATE_KEY) or {}
    if not isinstance(scored, dict):
        return
    merged = merge_scores(numbered(state), scored.get("jobs") or [])
    state[RANKED_STATE_KEY] = {
        "jobs": merged,
        "strategy_notes": str(scored.get("strategy_notes") or ""),
    }


def answer_budget(target_results: int) -> int:
    """How long the matcher's answer may run before the model is cut off.

    Not a guess at the right length — a bound on the wrong one. A verdict costs
    about eighty tokens, so even sixty postings is under five thousand and this
    leaves roughly five times that, thinking included. What it buys is the
    difference between a model that derails and burns 65 537 tokens over 356
    seconds, as one did on 2026-08-27, and one that is stopped early with most
    of its list intact — `salvage.keep_what_arrived` keeps whatever closed
    before the cut.
    """
    return 4000 + 400 * target_results


def build_matcher(
    target_results: int,
    feedback: dict[str, Any] | None = None,
    focus: SearchFocus | None = None,
) -> LlmAgent:
    settings = get_settings()

    async def instruction(ctx: ReadonlyContext) -> str:
        rendered = json.dumps(numbered(ctx.state), indent=2, ensure_ascii=False, default=str)
        return compose(
            RANK_INSTRUCTION.format(results=target_results),
            focus_block(focus),
            recency_block(),
            brief_block(),
            playbook_block(),
            profile_block(),
            feedback_block(feedback),
            known_postings_block(),
            f"# Postings to score\n\n```json\n{rendered}\n```",
        )

    return LlmAgent(
        name="matcher",
        model=resolve(settings.model_primary),
        description="Scores each posting against the brief and the candidate.",
        instruction=instruction,
        output_schema=ScoredJobList,
        output_key=RANKED_STATE_KEY,
        include_contents="none",
        generate_content_config=types.GenerateContentConfig(
            max_output_tokens=answer_budget(target_results),
        ),
        # A ranking that ran out of output tokens still ranked most of the list.
        after_model_callback=salvage.keep_what_arrived("jobs"),
        after_agent_callback=_rejoin,
    )


def build_investigator(
    feedback: dict[str, Any] | None = None,
    target_results: int | None = None,
    focus: SearchFocus | None = None,
) -> SequentialAgent:
    target = clamp_results(target_results)
    return SequentialAgent(
        name="investigator",
        description="Finds, cleans and ranks internship postings for the brief.",
        sub_agents=[
            build_query_planner(target, focus),
            build_scout(target, focus),
            build_normaliser(),
            # Asked for more than the user gets: the extras are what replace
            # postings whose link turns out not to reach the posting.
            build_matcher(rank_target(target), feedback, focus),
        ],
    )
