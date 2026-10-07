"""The Reader: one pasted posting → one posting on the list.

The Investigator is how postings are *found*. This is how one the candidate
found themselves gets in — a link from a friend, a LinkedIn post, a company
page they were already reading. Without it that posting either never reaches
the list or has to be re-discovered by a search run that has no reason to look
for it, and everything downstream (the fit score, the résumé, the tracker, the
follow-up) is keyed on a `JobPosting` row that does not exist.

Two ways in, because a link is not always what the candidate has. `build_reader`
reads a page the app fetched; `build_text_reader` reads text they pasted — out
of an email, a PDF, a message, or a board whose bot protection beat both the
HTTP client and the browser. Same schema, same Matcher, same destination; the
difference is that the pasted text may name no URL at all, and a posting with no
link is a normal outcome of it rather than a failure.

Two stages, for the same reason the Investigator has four — a different model
tier and a different failure mode each:

* **reader** — cheap model, no tools. The page is already fetched and in the
  prompt, so this is transcription, not judgement. Its failure mode is
  inventing a field the page never stated, which the prompt spends most of its
  length forbidding.
* **matcher** — the primary model, the same agent name and the same 0–10
  scale as the Investigator's last stage, because a score is only useful if it
  means the same thing as the scores next to it on the page. Its instruction
  differs in two ways: this posting is going on the list whatever it scores, so
  refusing to score it, or dropping it for being a weak match, is not an
  available answer — and it is scored against **the search brief alone**.

The lean context is deliberate (2026-09-23). The Investigator's matcher is also
handed the HR Expert's playbook, the master profile, the feedback digest and the
list of postings already saved, because it is choosing fifteen postings out of
dozens. A paste chooses nothing: the candidate already picked the posting, and
the score only has to say how well it fits what they are looking for. Those four
blocks cost a separate feedback-digest model call (~30k prompt tokens) plus
roughly doubling the scorer's own prompt, for a number that decides nothing
here. Dropping them made a paste one model call cheaper and a good deal faster.

The split also keeps the expensive model away from the page text. The Reader
reduces 400 KB of markup to a posting record; the Matcher scores that record.

Neither writes anything. `services/flows.py::import_link_stream` and
`::import_text_stream` verify whatever link there is, stamp the date, and
persist — the same rule as everywhere else here, so a model that forgets a tool
call cannot lose the work.
"""

from __future__ import annotations

import json

from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.agents.sequential_agent import SequentialAgent

from ..config import get_settings
from ..services.context_blocks import (
    brief_block,
    compose,
    platform_domains_block,
    recency_block,
)
from ..services.recency import with_age
from .models import resolve
from .prompts import (
    READ_PASTED_TEXT_INSTRUCTION,
    READ_POSTING_INSTRUCTION,
    SCORE_ONE_INSTRUCTION,
)
from .schemas import JobAssessment, NormalisedJob

READ_STATE_KEY = "read_posting"
ASSESSED_STATE_KEY = "posting_assessment"


def build_reader(url: str, page: str) -> LlmAgent:
    """Turns the fetched page into a posting record.

    The page arrives in the instruction rather than as a message because the
    agent runs with `include_contents="none"`: there is no conversation here,
    only one document to read, and excluding history is what keeps a second
    import in the same session from reading the first one's page.
    """
    settings = get_settings()

    async def instruction(_ctx: ReadonlyContext) -> str:
        return compose(
            READ_POSTING_INSTRUCTION,
            # The stage that turns "il y a 2 semaines" into a date needs today's.
            recency_block(),
            platform_domains_block(),
            # The brief is context, not a filter: the Reader records what the
            # page says either way. It is here so the summary it writes leans
            # towards what this candidate needs to know about the role.
            brief_block(),
            f"# The link the candidate pasted\n\n{url}",
            f"# The page behind that link\n\n{page}",
        )

    return LlmAgent(
        name="reader",
        model=resolve(settings.model_fast),
        description="Reads one fetched job page into a structured posting.",
        instruction=instruction,
        output_schema=NormalisedJob,
        output_key=READ_STATE_KEY,
        include_contents="none",
    )


def build_text_reader(text: str) -> LlmAgent:
    """Turns text the candidate pasted into a posting record.

    The same stage as `build_reader`, minus the page: no JSON-LD to trust, no
    URL to copy verbatim, and a much better chance that what arrived is a
    posting with an email signature stapled to it. Its instruction differs in
    the two places that matters — what to do about a link the text may or may
    not contain, and that an empty `posted_at` is the *expected* answer rather
    than the exception.

    `include_contents="none"` for the same reason: there is no conversation
    here, only one document, and history would let a second paste in the same
    session read the first one's text.
    """
    settings = get_settings()

    async def instruction(_ctx: ReadonlyContext) -> str:
        return compose(
            READ_PASTED_TEXT_INSTRUCTION,
            recency_block(),
            platform_domains_block(),
            brief_block(),
            f"# The text the candidate pasted\n\n{text}",
        )

    return LlmAgent(
        name="reader",
        model=resolve(settings.model_fast),
        description="Reads one pasted job posting into a structured posting.",
        instruction=instruction,
        output_schema=NormalisedJob,
        output_key=READ_STATE_KEY,
        include_contents="none",
    )


def build_scorer() -> LlmAgent:
    """Scores the posting the Reader produced, on the Investigator's scale.

    Against the search brief and nothing else — no playbook, profile, feedback
    digest or known postings. See this module's docstring for why.
    """
    settings = get_settings()

    async def instruction(ctx: ReadonlyContext) -> str:
        posting = ctx.state.get(READ_STATE_KEY, {})
        # Hand it the age rather than the arithmetic, exactly as the
        # Investigator's matcher is handed it: the ranking rule is written
        # against `posted_days_ago`, and date subtraction is a reliable source
        # of quiet model errors.
        aged = with_age([posting])[0] if isinstance(posting, dict) else posting
        rendered = json.dumps(aged, indent=2, ensure_ascii=False, default=str)
        return compose(
            SCORE_ONE_INSTRUCTION,
            recency_block(),
            brief_block(),
            f"# The posting to score\n\n```json\n{rendered}\n```",
        )

    return LlmAgent(
        name="matcher",
        model=resolve(settings.model_primary),
        description="Scores one posting the candidate pasted against the brief.",
        instruction=instruction,
        output_schema=JobAssessment,
        output_key=ASSESSED_STATE_KEY,
        include_contents="none",
    )


def build_link_intake(url: str, page: str) -> SequentialAgent:
    return SequentialAgent(
        name="link_intake",
        description="Reads a pasted job link and scores it against the brief.",
        sub_agents=[build_reader(url, page), build_scorer()],
    )


def build_text_intake(text: str) -> SequentialAgent:
    """The same two stages, over text instead of a fetched page.

    Deliberately the same agent *names* as the link path — `reader` then
    `matcher` — because `flows` maps an author name to the phase line the page
    shows, and a candidate watching a paste run has no interest in which of the
    two intakes they are in.
    """
    return SequentialAgent(
        name="text_intake",
        description="Reads a pasted job posting and scores it against the brief.",
        sub_agents=[build_text_reader(text), build_scorer()],
    )
