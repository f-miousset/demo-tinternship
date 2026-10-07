"""The Contact Scout: who to write to about one posting, and what to say.

Two agents in sequence, for the same reason the Interview Coach is split: the
scout carries `google_search` and writes prose notes, the strategist has no
tools and emits the validated `ContactPlan`. A trace can then show the pages
that were actually read separately from the shortlist drawn from them, which is
the only way to answer "did it read that this person runs campus hiring, or did
it decide someone probably does".

## Why the schema has no links in it

`services/outreach.py` builds every search URL, in Python, from the employer's
name, the candidate's own schools and the posting's keywords. The strategist
writes *keywords*; it never writes a search link. That is the same rule as the
Matcher answering with an index rather than a posting, applied to the failure
that matters most here: a fabricated contact link sends the candidate to a
stranger, and a plausible one — `linkedin.com/in/firstname-lastname` — is the
easiest thing in the world for a model to produce.

The one URL the strategist may hand over is a profile it genuinely read off a
page, and even that is fetched afterwards and thrown away unless the page comes
back titled with that person's name.

## And a third agent, which runs on its own

`build_opener` writes the message to **one** person, when the candidate presses
the button beside their name. It is not part of the shortlist run and never was
after 2026-09-03: finding out who is worth writing to and deciding to write to
somebody are two decisions, and only the first one is worth eight answers.
"""

from __future__ import annotations

from typing import Any

from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.tools.google_search_tool import GoogleSearchTool
from google.genai import types

from ..config import get_settings
from ..services.context_blocks import (
    compose,
    job_block,
    personalisation_block,
    playbook_block,
    profile_block,
)
from ..services.languages import DEFAULT_LANGUAGE, normalise_language
from ..services.outreach import school_names
from .applying import FEEDBACK_NOTE
from .critic import reviewed
from .models import grounded, resolve
from .prompts import (
    CONTACTS_INSTRUCTION,
    CONTACTS_RESEARCH_INSTRUCTION,
    HONESTY_RULES,
    OPENING_LINE_INSTRUCTION,
    language_block,
)
from .rubrics import CONTACTS_RUBRIC
from .schemas import ContactPlan, OpeningMessage

RESEARCH_STATE_KEY = "contact_research_notes"
CONTACTS_STATE_KEY = "contacts"
OPENING_STATE_KEY = "opening_message"

# What one connection note may cost before the model is cut off. A 280-character
# message is under a hundred tokens; this leaves room for thinking and for a
# second attempt inside the same answer, and stops a model that starts
# enumerating from burning a minute doing it. The same bound, for the same
# reason, as `investigator.answer_budget` — see
# `documentation/decisions.md`.
OPENING_BUDGET = 2000


# What to do with the schools, which differs by who is reading. The scout and the
# strategist are looking for alumni; the message writer is *being* one.
_SCHOOLS_TO_SEARCH = """
A shared school is the strongest opening a stranger can have: it needs no
introduction beyond naming it, and alumni answer messages from students of their
own school at a rate nothing else comes close to. Search for people at this
employer who studied at these, by name and by any abbreviation or endonym they
are known by.
""".strip()

_SCHOOLS_TO_WRITE = """
A shared school is the strongest opening a stranger can have, and it needs no
introduction beyond naming it. If the person you are writing to went to one of
these, say so in the first clause — and only if the notes above actually say
they did.
""".strip()


def schools_block(*, to_search: bool = True) -> str:
    """The candidate's schools, named, because an alumnus answers.

    They are already inside the master profile's JSON, and that is exactly the
    problem: buried in an education array they read as biography. Pulled out and
    given a reason, they become the search the scout should run first. The same
    list drives `outreach.standard_angles`, so the agent and the app are looking
    for alumni of the same schools.

    `to_search=False` for the Message Writer, which is not looking for anybody:
    it has one person in front of it, and what it needs from this list is the
    sentence to open with. Told to "search for people at this employer" it would
    be reading an instruction meant for a different agent — the kind of stray
    line a model obeys by inventing a search it cannot run.
    """
    schools = school_names()
    if not schools:
        return ""
    listed = "\n".join(f"- {school}" for school in schools)
    purpose = _SCHOOLS_TO_SEARCH if to_search else _SCHOOLS_TO_WRITE
    return f"""
# The candidate's schools

{listed}

{purpose}
""".strip()


def build_contact_scout(job_id: int, personalisation: str = "") -> LlmAgent:
    async def instruction(_ctx: ReadonlyContext) -> str:
        return compose(
            CONTACTS_RESEARCH_INSTRUCTION.format(honesty=HONESTY_RULES),
            job_block(job_id),
            profile_block(),
            schools_block(),
            personalisation_block(personalisation),
            "## This step\n\nDo the research now. Run your searches, then write up what you "
            "found as notes — one entry per person, each with the URL of the page that named "
            "them, and the company's LinkedIn slug if you saw it. Do not produce the "
            "shortlist yet; a second pass writes that from your notes. Anything you leave "
            "out here is lost.",
        )

    return LlmAgent(
        name="contact_scout",
        # Google Search is a Gemini server-side tool — see agents/models.py.
        model=resolve(grounded()),
        description="Finds the people worth contacting about one posting.",
        instruction=instruction,
        tools=[GoogleSearchTool(bypass_multi_tools_limit=True)],
        output_key=RESEARCH_STATE_KEY,
    )


def build_contact_strategist(
    job_id: int, language: str = DEFAULT_LANGUAGE, personalisation: str = ""
) -> LlmAgent:
    settings = get_settings()

    async def instruction(ctx: ReadonlyContext) -> str:
        notes = ctx.state.get(RESEARCH_STATE_KEY, "")
        return compose(
            CONTACTS_INSTRUCTION.format(honesty=HONESTY_RULES),
            language_block(language),
            f"# Research notes\n\n{notes}",
            # The playbook knows how this domain is actually approached — whether
            # a lab answers cold messages, whether the graduate scheme runs
            # through the school — which is judgement nothing else here has.
            playbook_block(),
            profile_block(),
            schools_block(),
            job_block(job_id),
            personalisation_block(personalisation),
            "## This step\n\nWrite the shortlist from the notes above. Every person you name "
            "must have the URL of the page that named them in `evidence_url` — if it is not "
            "in the notes, you did not read it, and the app drops that person before the "
            "candidate sees them. Give `linkedin_url` only for a profile URL the notes "
            "actually contain.",
            FEEDBACK_NOTE,
        )

    return LlmAgent(
        name="contact_strategist",
        model=resolve(settings.model_primary),
        description="Writes the contact shortlist and the searches from the research.",
        instruction=instruction,
        output_schema=ContactPlan,
        output_key=CONTACTS_STATE_KEY,
        # The scout's raw search output is in the notes it wrote; replaying the
        # whole grounded conversation as well doubles the prompt and hands the
        # strategist two versions of every finding to disagree with.
        include_contents="none",
    )


def unsourced_people(plan: dict) -> str:
    """The one absolute: nobody is named without the page that names them.

    Not left to the Critic, for the reason the interview brief's citation check
    is not — "is there a URL behind this name" is a fact about the object, not a
    judgement about it. And it is the specific failure this feature would
    otherwise have: a shortlist of confident, plausible, entirely invented
    people is indistinguishable from a good one until the candidate writes to
    them.

    An empty shortlist passes. A small employer with no findable staff is an
    ordinary result, and forcing a citation out of that would only produce a
    fabricated one.
    """
    unsourced = [
        str((person or {}).get("name") or "?")
        for person in (plan.get("people") or [])
        if not str((person or {}).get("evidence_url") or "").strip().startswith("http")
    ]
    if not unsourced:
        return ""
    named = ", ".join(unsourced[:5])
    return (
        f"{len(unsourced)} of the people it names have no `evidence_url`: {named}. A name with "
        "no page behind it cannot be told apart from an invented one, and the candidate would "
        "message a stranger. Either give the URL of the page you actually read that names each "
        "of them, or drop them and say in `notes` that no named contact could be found — the "
        "searches the app builds still work without a single name."
    )


def build_contacts(
    job_id: int, language: str = DEFAULT_LANGUAGE, personalisation: str = ""
) -> SequentialAgent:
    """Research who to contact, then write the shortlist behind the quality gate."""
    language = normalise_language(language)

    def critic_context(ctx: ReadonlyContext) -> str:
        # The Critic gets the notes too: `truthfulness` here is exactly the
        # question "was this person on a page the scout read", which cannot be
        # answered without the pages in front of it.
        notes = ctx.state.get(RESEARCH_STATE_KEY, "")
        return compose(
            profile_block(),
            schools_block(),
            job_block(job_id),
            personalisation_block(personalisation),
            f"# Research notes the shortlist had to work from\n\n{notes}",
            language_block(language),
        )

    return SequentialAgent(
        name="contacts",
        description="Researches who to contact about a posting, then writes the audited shortlist.",
        sub_agents=[
            build_contact_scout(job_id, personalisation),
            reviewed(
                build_contact_strategist(job_id, language, personalisation),
                rubric=CONTACTS_RUBRIC,
                artifact_key=CONTACTS_STATE_KEY,
                context_provider=critic_context,
                hard_check=unsourced_people,
            ),
        ],
    )


def build_opener(
    job_id: int,
    person: dict[str, Any],
    *,
    language: str = DEFAULT_LANGUAGE,
    personalisation: str = "",
    approach: list[str] | None = None,
) -> LlmAgent:
    """Write the first message to one named person.

    Its own agent, and its own run, because writing to somebody is a decision
    the candidate makes about that person — not a by-product of finding out who
    they are. Until 2026-09-03 the strategist wrote a line for everybody on the
    shortlist in the same breath as the shortlist itself, which meant a run
    spent output on eight messages to send one, and the Critic spent a whole
    weighted criterion judging seven drafts nobody would read.

    No tools and no Critic loop. Everything true it can say is already in the
    instruction — the posting, the profile, this person's own `why` — and a
    280-character note is not an artifact worth a revision round: the candidate
    is looking at it, and *Write it again* costs one click.
    """
    settings = get_settings()

    async def instruction(_ctx: ReadonlyContext) -> str:
        return compose(
            OPENING_LINE_INSTRUCTION.format(honesty=HONESTY_RULES),
            language_block(language),
            person_block(person),
            approach_block(approach),
            job_block(job_id),
            profile_block(),
            schools_block(to_search=False),
            personalisation_block(personalisation),
        )

    return LlmAgent(
        name="message_writer",
        # The fast tier: this is two sentences from facts already in the prompt,
        # and the judgement — who is worth writing to at all — was made upstream
        # by the primary model.
        model=resolve(settings.model_fast),
        description="Writes the connection note to one person on the shortlist.",
        instruction=instruction,
        output_schema=OpeningMessage,
        output_key=OPENING_STATE_KEY,
        include_contents="none",
        generate_content_config=types.GenerateContentConfig(
            max_output_tokens=OPENING_BUDGET,
        ),
    )


def person_block(person: dict[str, Any]) -> str:
    """The one person this message is for.

    Only the fields that are true of them. `evidence_url` is included because it
    is the page the claim came off, and a writer that can see where "runs campus
    hiring" was read is one that can say it without hedging.
    """
    name = str(person.get("name") or "").strip()
    lines = [f"- **Name**: {name}"]
    for label, key in (
        ("Their own job title", "role"),
        ("What they are to this application", "category"),
        ("Why them, for this posting", "why"),
        ("The page this was read on", "evidence_url"),
    ):
        value = str(person.get(key) or "").strip()
        if value:
            lines.append(f"- **{label}**: {value}")
    listed = "\n".join(lines)
    return f"""
# The person you are writing to

{listed}

Write to **this** person and nobody else. Everything above was read on a page —
do not add a fact about them that is not in it, however plausible. If the reason
above is thin, a short honest message beats a padded one.
""".strip()


def approach_block(approach: list[str] | None) -> str:
    """How this employer is actually approached, as the shortlist recorded it."""
    lines = [str(item).strip() for item in (approach or []) if str(item).strip()]
    if not lines:
        return ""
    listed = "\n".join(f"- {line}" for line in lines[:6])
    return f"""
# How people at this employer are actually approached

{listed}

This came out of the research on this employer. Where it says something about
the first message — the channel, what to lead with, what this kind of employer
reacts badly to — the message you write follows it.
""".strip()
