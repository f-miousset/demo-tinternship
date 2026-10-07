"""Turns the application tracker's history into guidance for the Investigator."""

from __future__ import annotations

import json
from typing import Any

from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from ..config import get_settings
from ..services.context_blocks import brief_block, compose
from .models import resolve
from .prompts import FEEDBACK_INSTRUCTION
from .schemas import FeedbackDigest

DIGEST_STATE_KEY = "feedback_digest"


def build_feedback_analyst(history: list[dict[str, Any]], stats: dict[str, Any]) -> LlmAgent:
    settings = get_settings()

    async def instruction(_ctx: ReadonlyContext) -> str:
        return compose(
            FEEDBACK_INSTRUCTION,
            brief_block(),
            "# Outcome statistics\n\n```json\n"
            + json.dumps(stats, indent=2, ensure_ascii=False, default=str)
            + "\n```",
            "# Application history\n\n```json\n"
            + json.dumps(history, indent=2, ensure_ascii=False, default=str)
            + "\n```",
        )

    return LlmAgent(
        name="feedback_analyst",
        model=resolve(settings.model_fast),
        description="Reads application outcomes and tells the Investigator what to change.",
        instruction=instruction,
        output_schema=FeedbackDigest,
        output_key=DIGEST_STATE_KEY,
        include_contents="none",
    )
