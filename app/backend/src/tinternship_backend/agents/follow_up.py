"""The Follow-up agent: one chase email for an application that has gone quiet.

Structurally the smallest of the writing agents — one producer behind one
quality gate, the same `reviewed()` loop the Applying team's three tracks use.
What is different is the length rule, which is a hard check rather than a
matter of taste.

**Why the word cap is arithmetic and not an opinion.** The résumé has the same
shape of problem and the same answer (`applying.py::one_page_violation`): the
Critic reads JSON, and a model asked to judge "is this short enough" against a
number it cannot measure scores the *impression* of brevity. A follow-up email
that runs 300 words is not a stylistic disagreement — it is an email that gets
skimmed to the last line and archived. So the count happens in Python, the
Critic is handed the measurement rather than asked for one, and the gate
rejects an over-long draft whatever it was scored.
"""

from __future__ import annotations

from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.loop_agent import LoopAgent
from google.adk.agents.readonly_context import ReadonlyContext

from ..config import get_settings
from ..services.context_blocks import compose, job_block, playbook_block, profile_block
from ..services.languages import DEFAULT_LANGUAGE, normalise_language
from .applying import FEEDBACK_NOTE
from .critic import reviewed
from .models import resolve
from .prompts import FOLLOW_UP_INSTRUCTION, HONESTY_RULES, language_block
from .rubrics import FOLLOW_UP_RUBRIC
from .schemas import FollowUpEmail

FOLLOW_UP_STATE_KEY = "follow_up_email"

# Where a chase email stops being read. Deliberately short: the reader is
# scanning an inbox, and the whole message has to fit on a phone screen without
# scrolling. It is the number the prompt states, the number the rubric states
# and the number the gate enforces — one policy, not three.
MAX_WORDS = 180


def word_count(email: dict) -> int:
    """Words in the body only.

    The greeting, sign-off and signature are fixed furniture that every email
    carries, so counting them would penalise a longer sign-off instead of a
    longer argument.
    """
    paragraphs = email.get("paragraphs") or []
    return sum(len(str(paragraph).split()) for paragraph in paragraphs)


def too_long(email: dict) -> str:
    """The email's hard requirement, as a fact rather than an opinion."""
    count = word_count(email)
    if count <= MAX_WORDS:
        return ""
    return (
        f"The body runs {count} words, {count - MAX_WORDS} over the {MAX_WORDS}-word limit. "
        "Cut it, do not compress it: drop the paragraph that only restates the cover letter, "
        "and reduce the rest to one sentence of reminder, one of substance and one question."
    )


def _length_report(email: dict) -> str:
    """Tell the Critic how long the email actually is.

    It reads JSON, which says nothing about length, so `brevity` was otherwise
    being scored on impressions — the same failure that made the résumé's
    `concision` unreliable until the renderer's measurement was handed over.
    """
    count = word_count(email)
    verdict = (
        f"It is {count} words. Within the limit."
        if count <= MAX_WORDS
        else f"It is **{count} words, {count - MAX_WORDS} over the {MAX_WORDS}-word limit**."
    )
    return f"""
## Measured length — counted, not estimated

The body of this email is {count} words across {len(email.get("paragraphs") or [])}
paragraph(s). {verdict}

Score `brevity` against that count, not your impression of the text:

- at or under {MAX_WORDS} words — judge `brevity` on redundancy alone.
- 1–40 words over — cap `brevity` at 4.
- more than 40 words over — cap `brevity` at 2.

Anything over the limit is rejected outright whatever you score it, so when it
overruns, `fixes` must name which sentences to cut.
""".strip()


def build_follow_up_agent(
    job_id: int, language: str = DEFAULT_LANGUAGE, history: str = ""
) -> LlmAgent:
    settings = get_settings()

    async def instruction(_ctx: ReadonlyContext) -> str:
        return compose(
            FOLLOW_UP_INSTRUCTION.format(honesty=HONESTY_RULES, max_words=MAX_WORDS),
            language_block(language),
            # The playbook knows this domain's follow-up norms — how long a lab
            # takes to answer, whether chasing is welcome — which is exactly the
            # judgement this email needs and nothing else in the app has.
            playbook_block(),
            profile_block(),
            job_block(job_id),
            history,
            FEEDBACK_NOTE,
        )

    return LlmAgent(
        name="follow_up_agent",
        model=resolve(settings.model_primary),
        description="Writes the follow-up email for an application that has gone quiet.",
        instruction=instruction,
        output_schema=FollowUpEmail,
        output_key=FOLLOW_UP_STATE_KEY,
    )


def build_follow_up_writer(
    job_id: int, language: str = DEFAULT_LANGUAGE, history: str = ""
) -> LoopAgent:
    """The producer behind its quality gate — the whole flow, in one agent."""
    language = normalise_language(language)

    def critic_context(ctx: ReadonlyContext) -> str:
        email = ctx.state.get(FOLLOW_UP_STATE_KEY)
        if not isinstance(email, dict):
            email = {}
        # The same ground truth the writer had, so the Critic can tell a fact
        # about this application from an invented one — including the timeline,
        # which is where "they said they would reply in March" would have to
        # come from if it is true at all.
        return compose(
            profile_block(),
            job_block(job_id),
            language_block(language),
            history,
            _length_report(email),
        )

    return reviewed(
        build_follow_up_agent(job_id, language, history),
        rubric=FOLLOW_UP_RUBRIC,
        artifact_key=FOLLOW_UP_STATE_KEY,
        context_provider=critic_context,
        hard_check=too_long,
    )
