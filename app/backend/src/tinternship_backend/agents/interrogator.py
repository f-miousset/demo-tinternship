"""The Interrogator: interviews the candidate, then writes the search brief.

Two agents rather than one. The chat agent talks in plain prose so the
conversation feels like a conversation; a separate finaliser then reads the
whole transcript and emits the schema-validated `SearchBrief`. Forcing
structured output on every chat turn would make the interview robotic and would
waste tokens re-emitting a half-empty brief after each answer.

The chat agent also decides when the interview is over, and says so with
`COMPLETION_MARKER` at the end of its closing turn. That is the whole handoff:
`services/flows.interview_stream` peels the marker off and turns it into a
`complete` event, and the Account page writes the brief — and researches the
playbook from it — without the candidate having to click anything.
"""

from __future__ import annotations

import re

from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from ..config import get_settings
from ..services.context_blocks import compose, profile_block
from ..services.profile_store import has_profile
from .models import resolve
from .prompts import (
    HONESTY_RULES,
    INTERROGATOR_FINALISE_INSTRUCTION,
    INTERROGATOR_INSTRUCTION,
)
from .schemas import SearchBrief

BRIEF_STATE_KEY = "search_brief"

COMPLETION_MARKER = "[[INTERVIEW_COMPLETE]]"

# Tolerant of what a model does to a literal it was asked to reproduce: wrapped
# in backticks, bolded, spelled with a space or a hyphen. Missing the marker
# costs nothing worse than the button the candidate used to have to press, but
# leaking one into a chat bubble reads as a bug, so recognise the variants.
_MARKER = re.compile(r"[`*_]*\[\[\s*INTERVIEW[ _-]?COMPLETE\s*\]\][`*_]*", re.IGNORECASE)


def split_completion(text: str) -> tuple[str, bool]:
    """Split a chat turn into the prose to show and "the interview is over".

    The marker is a signal to the app, not something the candidate should ever
    read, so it is stripped here — on the way to the browser *and* on the way
    out of the stored transcript, or reloading the page would put it back.
    """
    cleaned, found = _MARKER.subn("", text)
    return cleaned.strip(), bool(found)


def build_interrogator() -> LlmAgent:
    settings = get_settings()

    async def instruction(_ctx: ReadonlyContext) -> str:
        base = INTERROGATOR_INSTRUCTION.format(honesty=HONESTY_RULES)
        if has_profile():
            return compose(
                base,
                profile_block(),
                "The candidate has already uploaded a résumé — the profile above is what we "
                "know. Do not ask them to repeat anything that is already in it. Use it to ask "
                "sharper questions instead.",
            )
        return compose(
            base,
            "The candidate has not imported a profile, so you know nothing about their "
            "background. Ask about it as part of the interview, and mention once that "
            "uploading their base résumé in the Profile section above this conversation "
            "would let you skip those questions and would make everything downstream much "
            "better.",
        )

    return LlmAgent(
        name="interrogator",
        model=resolve(settings.model_primary),
        description="Interviews the candidate about the internship they want.",
        instruction=instruction,
    )


def build_brief_writer() -> LlmAgent:
    """Reads the interview transcript and emits the validated SearchBrief."""
    settings = get_settings()

    async def instruction(_ctx: ReadonlyContext) -> str:
        base = INTERROGATOR_FINALISE_INSTRUCTION.format(honesty=HONESTY_RULES)
        if has_profile():
            return compose(base, profile_block())
        return compose(
            base,
            "No master profile exists — the candidate imported nothing. The transcript is "
            "all you have; do not invent a background for them.",
        )

    return LlmAgent(
        name="brief_writer",
        model=resolve(settings.model_primary),
        description="Turns the interview into a structured search brief.",
        instruction=instruction,
        output_schema=SearchBrief,
        output_key=BRIEF_STATE_KEY,
    )
