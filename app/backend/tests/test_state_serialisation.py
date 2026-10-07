"""A genai object in ADK session state has to survive `model_dump()`.

`google.genai` builds each of its several hundred models on first use rather
than at import (`defer_build=True`). A model that only ever arrives as a
*nested field* of a validated response — `types.GroundingMetadata` inside a
`Candidate`, say — is built by its parent's schema and never touches its own
class-level serializer, so the class keeps pydantic's `MockValSer` placeholder.

ADK puts exactly such an object into session state: `AgentTool` stashes the
sub-agent's grounding metadata under `temp:_adk_grounding_metadata`, and the
Scout is handed an `AgentTool` whenever `search_job_board` sits beside
`google_search`. `EventActions.state_delta` is a `dict[str, Any]`, so
pydantic-core serialises by inference, reaches the placeholder and raises
`TypeError: 'MockValSer' object is not an instance of 'SchemaSerializer'` —
which ADK's sanitising fallback re-raises, killing the run. It took investigator
run 81 down on 2026-09-06, on the turn where the Scout called both tools at once
and ADK merged the two response events.

`agents.runtime` builds every genai model at import to close this. These tests
fail if that is removed — the first for the type ADK actually stashes, the
second for the next one it decides to stash.
"""

from __future__ import annotations

import pydantic
from google.adk.events.event_actions import EventActions
from google.genai import types

# Importing the runtime is what performs the build; the assertions below all
# depend on that import having happened.
from tinternship_backend.agents import runtime


def _nested_grounding_metadata() -> types.GroundingMetadata:
    """Grounding metadata as ADK gets it: validated as part of its parent.

    Constructing `GroundingMetadata()` directly would build the class and hide
    the bug, which is the whole reason this failure was so hard to see.
    """
    candidate = types.Candidate.model_validate(
        {"groundingMetadata": {"webSearchQueries": ["stage data science paris"]}}
    )
    assert candidate.grounding_metadata is not None
    return candidate.grounding_metadata


def test_grounding_metadata_in_a_state_delta_serialises():
    actions = EventActions(
        state_delta={"temp:_adk_grounding_metadata": _nested_grounding_metadata()}
    )

    # The call ADK makes when it merges parallel function-response events.
    dumped = actions.model_dump(exclude_none=True, by_alias=True)

    assert dumped["stateDelta"]["temp:_adk_grounding_metadata"] == {
        "webSearchQueries": ["stage data science paris"]
    }


def test_no_genai_model_is_left_unbuilt():
    unbuilt = [
        value.__name__
        for value in vars(types).values()
        if isinstance(value, type)
        and issubclass(value, pydantic.BaseModel)
        and value.model_rebuild() is True
    ]

    assert unbuilt == [], f"{len(unbuilt)} genai models were left deferred: {unbuilt[:5]}"


def test_the_build_actually_had_work_to_do():
    # Guards the guard: if a future google-genai drops `defer_build`, the two
    # tests above pass for a reason that has nothing to do with this fix, and
    # the runtime import can go.
    assert runtime._built_genai_models > 0
