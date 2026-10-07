"""Profile extraction and merging.

The extractor reads a document that arrives as an attachment on the user
message — the candidate's own .docx résumé, a résumé PDF, or a LinkedIn profile
export. Gemini reads PDFs natively, which matters here: designed résumés are
graphic-heavy multi-column layouts that text extraction mangles, and the
attachment path preserves the layout the model needs to keep content under the
right heading.
"""

from __future__ import annotations

import json
from typing import Any

from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from ..config import get_settings
from .models import resolve
from .prompts import PROFILE_EXTRACTION_INSTRUCTION, PROFILE_MERGE_INSTRUCTION
from .schemas import MasterProfile

EXTRACTED_STATE_KEY = "extracted_profile"
MERGED_STATE_KEY = "merged_profile"


def build_profile_extractor() -> LlmAgent:
    settings = get_settings()
    return LlmAgent(
        name="profile_extractor",
        model=resolve(settings.model_primary),
        description="Transcribes a résumé or profile document into structured data.",
        instruction=PROFILE_EXTRACTION_INSTRUCTION,
        output_schema=MasterProfile,
        output_key=EXTRACTED_STATE_KEY,
    )


def build_profile_merger(sources: list[dict[str, Any]]) -> LlmAgent:
    """Merge several independently-extracted profiles into one."""
    settings = get_settings()

    async def instruction(_ctx: ReadonlyContext) -> str:
        rendered = "\n\n".join(
            f"## Source {index + 1}: {source.get('label', 'document')} "
            f"({source.get('kind', 'unknown')})\n\n```json\n"
            + json.dumps(source.get("extracted", {}), indent=2, ensure_ascii=False, default=str)
            + "\n```"
            for index, source in enumerate(sources)
        )
        return f"{PROFILE_MERGE_INSTRUCTION}\n\n# Extracted sources\n\n{rendered}"

    return LlmAgent(
        name="profile_merger",
        model=resolve(settings.model_fast),
        description="Merges several extracted profiles into one master profile.",
        instruction=instruction,
        output_schema=MasterProfile,
        output_key=MERGED_STATE_KEY,
        include_contents="none",
    )
