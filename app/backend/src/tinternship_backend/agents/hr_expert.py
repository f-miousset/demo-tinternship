"""The HR Expert: researches how hiring works for this brief, writes the playbook.

Split into research and synthesis. The researcher carries `google_search` and
writes prose notes; the writer has no tools and emits the validated
`HiringPlaybook`. Keeping them apart means the traces show the raw research
separately from the conclusions drawn from it — which is exactly what you want
when auditing whether a claim in the playbook is actually supported.
"""

from __future__ import annotations

from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.tools.google_search_tool import GoogleSearchTool

from ..config import get_settings
from ..services.context_blocks import brief_block, compose, profile_block
from .models import grounded, resolve
from .prompts import HONESTY_RULES, HR_EXPERT_INSTRUCTION
from .schemas import HiringPlaybook

RESEARCH_STATE_KEY = "hr_research_notes"
PLAYBOOK_STATE_KEY = "hiring_playbook"


def build_hr_researcher() -> LlmAgent:
    async def instruction(_ctx: ReadonlyContext) -> str:
        return compose(
            HR_EXPERT_INSTRUCTION.format(honesty=HONESTY_RULES),
            brief_block(),
            profile_block(),
            "## This step\n\nDo the research now. Run your searches, then write up what you "
            "found as detailed notes — findings first, each with the URL it came from. Do not "
            "produce the final playbook yet; a second pass will do that from your notes. "
            "Anything you leave out here is lost, so be thorough.",
        )

    return LlmAgent(
        name="hr_researcher",
        # Google Search is a Gemini server-side tool — see agents/models.py.
        model=resolve(grounded()),
        description="Researches hiring norms and job-search craft for the brief.",
        instruction=instruction,
        tools=[GoogleSearchTool(bypass_multi_tools_limit=True)],
        output_key=RESEARCH_STATE_KEY,
    )


def build_playbook_writer() -> LlmAgent:
    settings = get_settings()

    async def instruction(ctx: ReadonlyContext) -> str:
        notes = ctx.state.get(RESEARCH_STATE_KEY, "")
        return compose(
            HR_EXPERT_INSTRUCTION.format(honesty=HONESTY_RULES),
            brief_block(),
            f"# Research notes\n\n{notes}",
            "## This step\n\nWrite the playbook from the notes above. Every `sources` entry "
            "must be a URL that appears in the notes — if it is not in the notes, you did not "
            "read it, and citing it is fabrication. Drop any advice the research does not "
            "actually support.",
        )

    return LlmAgent(
        name="playbook_writer",
        model=resolve(settings.model_primary),
        description="Synthesises research into the hiring playbook.",
        instruction=instruction,
        output_schema=HiringPlaybook,
        output_key=PLAYBOOK_STATE_KEY,
        include_contents="none",
    )


def build_hr_expert() -> SequentialAgent:
    return SequentialAgent(
        name="hr_expert",
        description="Researches the domain then writes the hiring playbook.",
        sub_agents=[build_hr_researcher(), build_playbook_writer()],
    )
