"""The Interview Coach: the brief for one application that reached an interview round.

Two agents in sequence, for the same reason the HR Expert is split: the
researcher carries `google_search` and writes prose notes, the coach has no
tools and emits the validated `InterviewPrep`. Keeping them apart is what lets a
trace show the raw research separately from the conclusions drawn from it —
which is the only way to check whether "they raised a Series B in March" came
from a page or from the model.

The coach then goes through the same produce → critique → gate loop as the
résumé and the letter. It is the artifact with the most to lose from invention:
a fabricated line on a résumé is embarrassing, a fabricated fact about the
employer gets said out loud to someone who knows the answer.

## What it reads that nothing else does

The posting's `strengths` and `risks` — the app's own assessment, written when
the posting was discovered — are the spine of the brief. `strengths` become what
to lead with, `risks` become the questions to prepare for, and both are already
in `job_block`. On top of that it gets the résumé the Applying team produced for
this application, when there is one: its `keywords_missing` and `gap_analysis`
are a list of gaps somebody already did the work of finding, and the interview
is where they get asked about.
"""

from __future__ import annotations

from typing import Any

from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.tools.google_search_tool import GoogleSearchTool
from sqlmodel import select

from ..config import get_settings
from ..db.engine import session_scope
from ..db.models import ApplicationArtifact, ArtifactKind
from ..services.context_blocks import (
    compose,
    job_block,
    personalisation_block,
    playbook_block,
    profile_block,
)
from ..services.languages import DEFAULT_LANGUAGE, normalise_language
from .applying import FEEDBACK_NOTE
from .critic import reviewed
from .models import grounded, resolve
from .prompts import (
    HONESTY_RULES,
    INTERVIEW_PREP_INSTRUCTION,
    INTERVIEW_PREP_RESEARCH_INSTRUCTION,
    language_block,
)
from .rubrics import INTERVIEW_PREP_RUBRIC
from .schemas import InterviewPrep

RESEARCH_STATE_KEY = "interview_research_notes"
INTERVIEW_PREP_STATE_KEY = "interview_prep"


def package_gaps_block(application_id: int) -> str:
    """The gaps the résumé already admitted to, handed to the interview.

    `keywords_missing` and `gap_analysis` are written by the Resume agent under
    a rubric that scores it down for papering over a gap, so by the time an
    application reaches an interview this list is the honest one — and it is
    exactly what the interviewer is about to probe. Re-deriving it from the
    profile would produce a different list for no reason.

    Empty when no package was generated (an application the candidate wrote
    themselves and only tracked here), which `compose` then drops.
    """
    with session_scope() as session:
        resume = session.exec(
            select(ApplicationArtifact)
            .where(
                ApplicationArtifact.application_id == application_id,
                ApplicationArtifact.kind == ArtifactKind.RESUME,
            )
            .order_by(ApplicationArtifact.version.desc())
        ).first()
        content: dict[str, Any] = dict(resume.content or {}) if resume else {}

    missing = [str(item) for item in (content.get("keywords_missing") or [])]
    gaps = [str(item) for item in (content.get("gap_analysis") or [])]
    if not missing and not gaps:
        return ""

    lines = [
        "# What the résumé for this application already conceded",
        "",
        "The Resume agent wrote these when it tailored the CV they actually sent.",
        "They are the gaps the candidate is walking in with, and the interviewer",
        "has the same document in front of them — so these are the questions that",
        "get asked. Every one of them needs an honest answer in `gaps`.",
        "",
    ]
    if missing:
        lines += ["**Requirements the profile could not support**", ""]
        lines += [f"- {item}" for item in missing]
        lines.append("")
    if gaps:
        lines += ["**Gaps the résumé declared**", ""]
        lines += [f"- {item}" for item in gaps]
    return "\n".join(lines).strip()


def timeline_block(history: str) -> str:
    """Where this application has actually got to, in the candidate's own record."""
    if not history.strip():
        return ""
    return f"# This application's history\n\n{history.strip()}"


def build_interview_researcher(
    job_id: int, application_id: int, personalisation: str = ""
) -> LlmAgent:
    async def instruction(_ctx: ReadonlyContext) -> str:
        return compose(
            INTERVIEW_PREP_RESEARCH_INSTRUCTION.format(honesty=HONESTY_RULES),
            job_block(job_id),
            personalisation_block(personalisation),
            package_gaps_block(application_id),
            "## This step\n\nDo the research now. Run your searches, then write up what you "
            "found as detailed notes — findings first, each with the URL it came from, and "
            "each dated where the source gives a date. Do not produce the brief yet; a "
            "second pass will write it from your notes. Anything you leave out here is lost.",
        )

    return LlmAgent(
        name="interview_researcher",
        # Google Search is a Gemini server-side tool — see agents/models.py.
        model=resolve(grounded()),
        description="Researches the employer, the role and the interview process.",
        instruction=instruction,
        tools=[GoogleSearchTool(bypass_multi_tools_limit=True)],
        output_key=RESEARCH_STATE_KEY,
    )


def build_interview_coach(
    job_id: int,
    application_id: int,
    language: str = DEFAULT_LANGUAGE,
    personalisation: str = "",
    history: str = "",
) -> LlmAgent:
    settings = get_settings()

    async def instruction(ctx: ReadonlyContext) -> str:
        notes = ctx.state.get(RESEARCH_STATE_KEY, "")
        return compose(
            INTERVIEW_PREP_INSTRUCTION.format(honesty=HONESTY_RULES),
            language_block(language),
            f"# Research notes\n\n{notes}",
            # The playbook knows this domain's interview norms — how a lab
            # interviews versus how a consultancy does — which is judgement
            # nothing else in the app has.
            playbook_block(),
            profile_block(),
            job_block(job_id),
            package_gaps_block(application_id),
            personalisation_block(personalisation),
            timeline_block(history),
            "## This step\n\nWrite the brief from the notes above. Every claim about the "
            "employer must be supported by a URL that appears in the notes — if it is not "
            "in the notes, you did not read it, and citing it is fabrication. Put those URLs "
            "in `sources`. Drop any claim the research does not actually support.",
            FEEDBACK_NOTE,
        )

    return LlmAgent(
        name="interview_coach",
        model=resolve(settings.model_primary),
        description="Writes the interview brief from the research and the candidate's profile.",
        instruction=instruction,
        output_schema=InterviewPrep,
        output_key=INTERVIEW_PREP_STATE_KEY,
        # The researcher's raw search output is in the notes it wrote; replaying
        # the whole grounded conversation as well doubles the prompt and gives
        # the coach two versions of the same finding to disagree with.
        include_contents="none",
    )


def unsourced_company_claims(prep: dict) -> str:
    """The brief's one absolute: nothing about the employer without a source.

    Not left to the Critic for the same reason the résumé's page count is not —
    "did this cite anything" is a fact about the object, not a judgement about
    it, and a brief that describes a company it never looked up is the failure
    mode that costs the candidate the interview rather than a mark.

    It checks presence, not correctness: the Critic still has to decide whether
    the sources say what the brief claims they say.
    """
    sources = [
        source for source in (prep.get("sources") or []) if str((source or {}).get("url", "")).strip()
    ]
    if sources:
        return ""
    claimed = str(prep.get("company_brief") or "").strip()
    developments = prep.get("recent_developments") or []
    if not claimed and not developments:
        return ""
    return (
        "It describes the employer but cites no sources at all: `sources` is empty while "
        "`company_brief` and/or `recent_developments` make claims about the company. Either "
        "put the URLs you actually read into `sources`, or cut every claim you cannot "
        "source and say plainly in `company_brief` that the research found little about "
        "this employer. A brief the candidate cannot check is one they must not repeat."
    )


def build_interview_prep(
    job_id: int,
    application_id: int,
    language: str = DEFAULT_LANGUAGE,
    personalisation: str = "",
    history: str = "",
) -> SequentialAgent:
    """Research the employer, then write the brief behind the quality gate."""
    language = normalise_language(language)

    def critic_context(ctx: ReadonlyContext) -> str:
        # The Critic gets the notes too, because `truthfulness` here is exactly
        # the question "is this claim in the research", and it cannot answer
        # that without the research in front of it.
        notes = ctx.state.get(RESEARCH_STATE_KEY, "")
        return compose(
            profile_block(),
            job_block(job_id),
            package_gaps_block(application_id),
            personalisation_block(personalisation),
            f"# Research notes the brief had to work from\n\n{notes}",
            language_block(language),
        )

    return SequentialAgent(
        name="interview_prep",
        description="Researches the employer then writes the audited interview brief.",
        sub_agents=[
            build_interview_researcher(job_id, application_id, personalisation),
            reviewed(
                build_interview_coach(
                    job_id, application_id, language, personalisation, history
                ),
                rubric=INTERVIEW_PREP_RUBRIC,
                artifact_key=INTERVIEW_PREP_STATE_KEY,
                context_provider=critic_context,
                hard_check=unsourced_company_claims,
            ),
        ],
    )
