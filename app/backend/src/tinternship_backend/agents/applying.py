"""The Applying team: the candidate's own documents for one posting, filled in.

Which documents is the run's choice, not this module's: a plan is the request,
`None` is "not this time". The default package is the résumé alone; the cover
letter joins it when the candidate ticks the box, and can be run on its own to
add one later. When both lanes run they run in parallel — they do not depend on
each other — and each is wrapped in its own produce → critique → gate loop, so a
weak result gets revised without holding up the other one.

**Both lanes are the same operation on two different documents.** The
résumé track changed shape twice: on 2026-08-28 it stopped *writing* a résumé
from the master profile into a fixed template and started editing the
candidate's own .docx; on 2026-08-29 it stopped editing and started filling the
blanks they left in it. On 2026-09-09 the cover letter followed, for the same
four reasons and one of its own:

* the generated document was never the candidate's document — the layout they
  had already balanced was reproduced by a renderer, not preserved;
* a model asked to re-emit an entire document re-emits an entire document, and
  every regeneration quietly moved facts around;
* even "re-word this line, but only a little" is a rule someone has to police
  every run, and every check is a place their own sentence comes back subtly
  different. Filling a blank is not a smaller version of that — it is an
  operation with nothing to police, because the code slices around the
  placeholder and copies the rest;
* French packages kept arriving with English in them, because a model writing
  eight hundred words of prose surrounded by English instructions drifts. A
  model writing a few short strings into an already-French document has nowhere
  to drift to — and what it does return is checked word by word by
  `services/language_check.py`;
* and for the letter specifically: its nine fields *were* its layout, so a
  candidate who wanted their own letterhead, their own address block and their
  own sign-off had nowhere to put them.

The gate that remains is about the things filling a blank *can* still get wrong:
the page (`services/page_fit.py`, because the candidate's rule is one page and
their CV already fills it) and the language.

The third track, the Step agent, was removed on 2026-08-28; see
`documentation/applying.md`.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping
from typing import Any

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.parallel_agent import ParallelAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.events.event import Event, EventActions
from google.adk.tools.google_search_tool import GoogleSearchTool
from google.genai import types
from pydantic import PrivateAttr

from ..config import get_settings
from ..services import (
    base_documents,
    docx_template,
    job_titles,
    language_check,
    letter_fields,
    page_fit,
)
from ..services.context_blocks import (
    brief_block,
    candidate_lists_block,
    compose,
    job_block,
    personalisation_block,
    playbook_block,
    profile_block,
)
from .critic import reviewed
from .models import grounded, resolve
from .prompts import (
    ADDRESS_RESEARCH_INSTRUCTION,
    COVER_LETTER_INSTRUCTION,
    HONESTY_RULES,
    HUMANISER_INSTRUCTION,
    RESUME_TAILOR_INSTRUCTION,
    humaniser_tells,
    language_block,
)
from .rubrics import COVER_LETTER_RUBRIC, RESUME_RUBRIC
from .schemas import HumanisedProse, TailoredCoverLetter, TailoredResume

RESUME_STATE_KEY = "tailored_resume"
COVER_LETTER_STATE_KEY = "cover_letter"
ADDRESS_STATE_KEY = "address_research"
HUMANISER_STATE_KEY = "letter_prose_rewrites"

FEEDBACK_NOTE = (
    "## If you are revising\n\n"
    "A critic may have rejected your previous attempt. If feedback appears in the "
    "conversation above, treat every point in it as mandatory: fix each one and return the "
    "complete artifact again, not a diff. Do not argue with the critic."
)


def _shared_context(job_id: int, language: str, personalisation: str = "") -> str:
    """What both writers get: the brief, the playbook, the profile, the posting.

    The posting block is the same record the Jobs deck shows — summary, fit
    score and rationale, strengths, risks, requirements, language — so the two
    writers argue from the assessment the candidate actually read before saying
    yes, rather than re-deriving one from the raw description.

    `language` reaches one block: the candidate's two lists are written in both
    and only this run's is shown, so the courses and skills arrive already
    spelled the way the document being filled spells them.

    `personalisation` is whatever the candidate typed into the dialog when they
    pressed Generate. It goes last, because it is the only block that outranks
    the others: a contact on the team is a fact none of the research has.
    """
    return compose(
        brief_block(),
        playbook_block(),
        profile_block(),
        candidate_lists_block(language),
        job_block(job_id),
        personalisation_block(personalisation),
    )


# ---------------------------------------------------------------------------
# The base document, as its writer sees it
# ---------------------------------------------------------------------------


def base_document_block(plan: base_documents.Plan) -> str:
    """The candidate's own document and the blanks in it, as its writer sees it.

    Two parts, and both are needed. The **listing** is the whole document, one
    line per paragraph, numbered — not because the model can address a line (it
    cannot) but because a blank is filled *into a sentence*, and a model that
    cannot see the sentence writes something that does not fit in it. The
    **blanks** are the actual work: key, token, the line each one sits in, and
    the character budget measured off the room left on that page.

    The listing shows the blanks Python already answered **as answered** —
    today's date and the employer's name are printed in place of their
    placeholders (`services/letter_fields.py`). That is deliberate: they are part
    of the sentence the model is completing, and a model shown `[company_name]`
    three lines above its own blank will helpfully write the company name again.

    The budget is per blank and there is a total as well, because they answer
    different questions. A blank over its own cap is reported against that
    blank; the total is what stops four reasonable fills adding up to a second
    page. Both are checked in Python afterwards — this is the request, the check
    is the promise.

    The total is quoted **twice**, as a cap and as a target, and the second
    figure is the one that was missing. A model shown only a ceiling reads it as
    a cliff and camps well below: the first letter filled this way used 1,133 of
    its 2,174 characters and stopped ten lines above the bottom of the page.
    `page_fit.short_problems` is the check behind the target, exactly as
    `page_problems` is the check behind the cap.
    """
    lines = docx_template.filled_lines(plan.blocks, plan.slots, plan.auto)
    listing = "\n".join(
        f"{block.index:>3} | {lines.get(block.index, block.text)}" for block in plan.blocks
    )
    blanks = "\n".join(
        f"  {slot.key}  {slot.token}\n"
        f"        in line {slot.block}: {slot.line.strip()}\n"
        f"        budget: {slot.budget} characters"
        for slot in plan.open
    )
    name = "French" if plan.language == "fr" else "English"
    already = (
        "\nToday's date and the employer's name are already written into the listing above, "
        "from the candidate's own record of this posting. They are not yours to write and they "
        "are not in the list below — but they are part of the sentences you are completing, so "
        "read them.\n"
        if plan.auto
        else ""
    )
    full = f"This document is {plan.estimate.fraction:.0%} full with the blanks still in it"
    if plan.target:
        room = (
            f"## How much of the page to use\n\n"
            f"{full}, which leaves room for about **{plan.room} characters**. Aim to use about "
            f"**{plan.target}** of them.\n\n"
            "Both numbers are measured on their actual document, and the filled file is "
            "measured again after you answer, **in both directions**. Fills that run over the "
            "page are refused; so are fills that leave most of it empty. The room is theirs and "
            "they left these blanks to use it — a list that stops two items early and a page "
            "that ends halfway down are the same mistake as a page that spills."
        )
    else:
        # `page_fit.total_target` stands down on a document with more page than
        # its blanks could ever hold, and so must this: telling a model to fill
        # a page with a job title and an employer's name is asking for a fill
        # that would be refused for being one.
        room = (
            f"## How much of the page to use\n\n"
            f"{full}, which leaves room for about **{plan.room} characters** — more than these "
            "blanks could hold even at their caps. Fill each one properly and let the rest of "
            "the page be; laying it out is the candidate's business, not yours. The filled file "
            "is measured again after you answer, and anything over the page is refused."
        )
    return f"""
# The candidate's {name} {plan.noun} — {len(plan.blocks)} lines, {len(plan.open)} blank(s) to fill

This is their own Word document, one line per paragraph, numbered. You are not
editing it: every character outside the blanks below is copied into the file
exactly as it is here. The listing is so you can see the sentence each blank
lives in.

```
{listing}
```
{already}
## The blanks, and what each one may cost

{blanks or "  (none — this document has no placeholders left to fill)"}

{room}

Return one entry per blank, keyed by the slot ({", ".join(slot.key for slot in plan.open) or "n/a"}),
carrying **only** the text that replaces the token — not the words around it.
""".strip()


def build_resume_agent(
    job_id: int,
    plan: base_documents.Plan,
    personalisation: str = "",
) -> LlmAgent:
    settings = get_settings()

    async def instruction(_ctx: ReadonlyContext) -> str:
        return compose(
            RESUME_TAILOR_INSTRUCTION.format(honesty=HONESTY_RULES),
            language_block(plan.language),
            base_document_block(plan),
            _shared_context(job_id, plan.language, personalisation),
            FEEDBACK_NOTE,
        )

    return LlmAgent(
        name="resume_agent",
        model=resolve(settings.model_primary),
        description="Fills the blanks in the candidate's own résumé for this posting.",
        instruction=instruction,
        output_schema=TailoredResume,
        output_key=RESUME_STATE_KEY,
    )


def build_address_scout(job_id: int) -> LlmAgent:
    """Search for the postal address that goes at the top of the letter.

    Split from the writer for the reason the Contact Scout and the Interview
    Researcher are: an agent carrying `google_search` cannot also carry an
    `output_schema`, and a trace that shows the pages read separately from the
    answer drawn from them is the only way to tell a researched address from a
    plausible one.

    It exists at all because the alternative was a blank line. A posting almost
    never gives the employer's address, nothing else in this system knows it,
    and a model asked for one straight out invents a street number that looks
    exactly like a real one — so the choice was *leave it empty* or *go and
    look*. Looking wins as long as what comes back is a page anyone can open,
    which is what the instruction spends most of its words on.

    Cheap by construction: one grounded call per applying run, on the letter's
    branch, so it overlaps the résumé track entirely.
    """

    async def instruction(_ctx: ReadonlyContext) -> str:
        return compose(
            ADDRESS_RESEARCH_INSTRUCTION.format(honesty=HONESTY_RULES),
            job_block(job_id),
            "## This step\n\nSearch now, then write up the address as notes. The agent that "
            "fills the letter reads them and can run no search of its own — anything you "
            "leave out here is a blank line on the document, and anything you make up here "
            "is on the document instead.",
        )

    return LlmAgent(
        name="address_scout",
        # Google Search is a Gemini server-side tool — see agents/models.py.
        model=resolve(grounded()),
        description="Finds the employer's postal address for the letter's address block.",
        instruction=instruction,
        tools=[GoogleSearchTool(bypass_multi_tools_limit=True)],
        output_key=ADDRESS_STATE_KEY,
    )


def address_notes_block(notes: str) -> str:
    """The scout's findings, as the letter writer and its Critic see them."""
    return f"""
# The employer's address, as researched

These notes were written by the Address Scout, which searched for this
employer's postal address a moment ago. They are the **only** source for the
address block: you cannot search, and an address that is not below is one
nobody read.

{notes.strip() or "_(the scout returned nothing — leave the address blanks empty)_"}
""".strip()


def build_cover_letter_agent(
    job_id: int,
    plan: base_documents.Plan,
    personalisation: str = "",
) -> LlmAgent:
    settings = get_settings()

    async def instruction(ctx: ReadonlyContext) -> str:
        return compose(
            COVER_LETTER_INSTRUCTION.format(honesty=HONESTY_RULES),
            language_block(plan.language),
            base_document_block(plan),
            address_notes_block(str(ctx.state.get(ADDRESS_STATE_KEY) or "")),
            _shared_context(job_id, plan.language, personalisation),
            FEEDBACK_NOTE,
        )

    return LlmAgent(
        name="cover_letter_agent",
        model=resolve(settings.model_primary),
        description="Fills the blanks in the candidate's own cover letter for this posting.",
        instruction=instruction,
        output_schema=TailoredCoverLetter,
        output_key=COVER_LETTER_STATE_KEY,
    )


# ---------------------------------------------------------------------------
# The Humaniser
# ---------------------------------------------------------------------------

# A fill has to be a sentence or two before there is anything to humanise. Twelve
# words is the line, and it is drawn on the *writer's own output* rather than on
# a list of blank names: "Data Science", "Paris" and "Data Scientist (H/F)" are
# fields whichever template they came from, and a candidate who names their
# paragraph `[para2]` still gets one humanised. Below the line there is nothing
# to re-word — a machine tell needs a sentence to hide in.
PROSE_WORDS = 12


def prose_keys(fills: Mapping[str, str], plan: base_documents.Plan) -> list[str]:
    """The slots holding prose, in document order — the Humaniser's whole remit.

    Python decides this, and decides it twice: once to tell the Humaniser what
    it may rewrite, and again to accept what came back. That is the same shape
    as `merge_scores` joining the Matcher's verdicts onto postings it never
    held — the model works on the thing it is good at, and the join stays where
    it cannot be corrupted.
    """
    answered = plan.auto
    return [
        slot.key
        for slot in plan.slots
        if slot.key not in answered
        and len(str(fills.get(slot.key) or "").split()) >= PROSE_WORDS
    ]


def build_letter_humaniser(job_id: int, plan: base_documents.Plan) -> LlmAgent:
    """Rewrite the letter's paragraphs so they do not read as generated.

    A recruiter reads a hundred letters a season and has learnt the shape of a
    generated one; a letter that pattern-matches to *machine* is discarded
    before anyone weighs what it says. That is a different failure from the ones
    the Critic scores — the letter can be true, specific, well-evidenced and
    still be binned on sight — so it gets a pass of its own rather than another
    line in the writer's instruction, which is already two thousand words about
    what to say rather than how it sounds.

    It runs **inside** the review loop, between the writer and the Critic: what
    it produces is what ships, so it is what the Critic must score and what the
    gate must measure. A rewrite that breaks a budget, drops into the other
    language or leaves a placeholder behind is refused exactly like the writer's
    own fills.

    The tells it works from are per language and it is shown only the run's own
    — *delve* is not a French problem and *également* is not an English one.
    They come from two public skills the candidate pointed at, rewritten for
    this genre; see `agents/prompts.py`.
    """
    settings = get_settings()

    async def instruction(ctx: ReadonlyContext) -> str:
        artifact = ctx.state.get(COVER_LETTER_STATE_KEY)
        fills = docx_template.fill_map(artifact if isinstance(artifact, dict) else {})
        return compose(
            HUMANISER_INSTRUCTION.format(
                tells=humaniser_tells(plan.language), honesty=HONESTY_RULES
            ),
            language_block(plan.language),
            _prose_block(fills, plan),
            job_block(job_id),
            FEEDBACK_NOTE,
        )

    return LlmAgent(
        name="cover_letter_humaniser",
        model=resolve(settings.model_primary),
        description="Rewrites the letter's paragraphs so they do not read as generated.",
        instruction=instruction,
        output_schema=HumanisedProse,
        output_key=HUMANISER_STATE_KEY,
    )


def _prose_block(fills: Mapping[str, str], plan: base_documents.Plan) -> str:
    """The paragraphs as they stand, with the room each one has.

    The whole letter is shown around them, because a paragraph is humanised
    *into* a document: the sentence above it is the candidate's own greeting and
    the one below is their own sign-off, and prose that ignores them reads as
    pasted in — which is the failure this agent exists to remove.

    It is shown the page's total as well as each paragraph's cap, because this
    agent's whole instinct is to cut and what it returns is what ships. Removing
    filler shortens a paragraph and that is the job; taking the letter under
    `page_fit.total_target` is refused by the same gate that refuses the writer.
    """
    keys = prose_keys(fills, plan)
    by_key = {slot.key: slot for slot in plan.slots}
    used = page_fit.added_chars(plan.open, fills)
    room = (
        f"This page has room for about {plan.room} characters of fills and should use about "
        f"{plan.target} of them; the fills above come to {used}. Whatever you return is measured "
        "again, and a letter that ends halfway down its page is refused just as one that runs "
        "over is. Cutting padding is your job; cutting the letter is not."
        if plan.target
        else
        f"This page has room for about {plan.room} characters of fills, more than its blanks "
        f"could hold; the fills above come to {used}. Whatever you return is measured again, "
        "and anything over a blank's budget is refused."
    )
    lines = docx_template.filled_lines(plan.blocks, plan.slots, fills)
    page = "\n".join(
        f"{block.index:>3} | {lines.get(block.index, block.text)}" for block in plan.blocks
    )
    paragraphs = "\n\n".join(
        f"  {key} — budget {by_key[key].budget} characters\n  {fills.get(key, '')}"
        for key in keys
    )
    return f"""
# The letter as it stands

Everything outside the paragraphs below is the candidate's own document and is
not yours to touch. It is here so that what you write fits between the lines
around it.

```
{page}
```

## The paragraphs you may rewrite

{paragraphs or "  (none — nothing in this letter is long enough to humanise)"}

{room}

Return only the ones you actually changed, keyed by slot
({", ".join(keys) or "n/a"}), each carrying the whole paragraph.
""".strip()


class MergeProse(BaseAgent):
    """Write the Humaniser's rewrites back over the letter's fills, in Python.

    The join is here rather than in the Humaniser's answer for the reason the
    Matcher answers with an index: a field a model copies is a field it can
    corrupt. Asked to return the whole artifact with three paragraphs changed,
    it will occasionally normalise the reference line, drop `facts_used` or
    reformat the address. Asked for three paragraphs, it can only ever give
    three paragraphs — and this agent is what makes them the letter.

    Two things it refuses, silently and by construction: a rewrite for a slot
    Python did not classify as prose, and one for a blank the record answered.
    Both are the Humaniser reaching outside its remit, and neither is worth a
    revision round.
    """

    _plan: base_documents.Plan = PrivateAttr()

    def __init__(self, *, name: str, plan: base_documents.Plan, **kwargs: Any) -> None:
        super().__init__(name=name, description="Applies the humanised prose.", **kwargs)
        self._plan = plan

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        artifact = state.get(COVER_LETTER_STATE_KEY)
        artifact = dict(artifact) if isinstance(artifact, dict) else {}
        rewrites = state.get(HUMANISER_STATE_KEY)
        rewrites = rewrites if isinstance(rewrites, dict) else {}

        fills = docx_template.fill_map(artifact)
        allowed = set(prose_keys(fills, self._plan))
        applied: dict[str, str] = {}
        for entry in rewrites.get("rewrites") or []:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("slot") or "").strip()
            text = str(entry.get("text") or "").strip()
            if key in allowed and text:
                applied[key] = text

        if not applied:
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                branch=ctx.branch,
                content=types.Content(
                    role="model",
                    parts=[types.Part(text="The letter's prose was left as it was written.")],
                ),
            )
            return

        merged = [
            {**entry, "text": applied.get(str(entry.get("slot") or ""), entry.get("text", ""))}
            for entry in artifact.get("fills") or []
            if isinstance(entry, dict)
        ]
        artifact["fills"] = merged
        artifact["humanised"] = sorted(applied)

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        text=f"Rewrote {len(applied)} paragraph(s) of the letter: "
                        f"{', '.join(sorted(applied))}."
                    )
                ],
            ),
            actions=EventActions(state_delta={COVER_LETTER_STATE_KEY: artifact}),
        )


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def merged_fills(artifact: dict, plan: base_documents.Plan) -> dict[str, str]:
    """The fills that will actually be written: the model's, under Python's.

    `plan.auto` wins, and silently. Those blanks were answered from the record
    before the model was asked anything and it was never shown them — a fill it
    volunteers for one is a stray, not a disagreement, and sending a whole
    revision loop back over it would cost a model call to change nothing.
    """
    return {**docx_template.fill_map(artifact), **plan.auto}


def hard_check(artifact: dict, plan: base_documents.Plan) -> str:
    """Everything about a filling run that is a fact rather than an opinion.

    Three families, none of which is left to the Critic because none of them is
    a matter of taste:

    * **the blanks** — one fill each, no tabs, no line breaks, nothing still in
      brackets, nothing over its own budget (`docx_template.check_fills`);
    * **the page**, both ways. `page_fit.page_problems` measures the document
      that would actually be sent and refuses it if it spills — the candidate's
      rule is one page and their CV already fills most of it, so on a résumé
      this is the constraint that bites. `page_fit.short_problems` refuses the
      opposite: fills that left most of the page empty. On a cover letter, which
      starts at 69% of a page, that is the one that bites, and until 2026-09-10
      nothing checked it at all;
    * **the language**, measured on the fills (`language_check.wrong_language`).

    Returning a reason disqualifies the attempt no matter how the Critic scored
    it. The Critic reads JSON, and a Critic asked whether a fill still fits, or
    whether a stray "and the" is English, answers from impressions.

    The language check reads **the prose the model wrote, and only that**, which
    is a change from the re-wording design and a deliberate one. Everything else on
    the page is the candidate's own text, unreachable by this agent — failing a
    run because their French CV happens to carry an English sentence would be
    refusing an agent for something it cannot fix, over and over. A base
    document in the wrong language is a problem, but it is *their* problem and
    it is reported to them at upload, where they can act on it. Python's own
    fills are excluded for the same reason one step further in: a French
    employer's name is not the model writing French.

    Reading only the fills also makes the check sharper rather than weaker: four
    English words dropped into a 3,500-character French CV never moved a
    whole-document ratio, and they are exactly what this run wrote. The letter's
    address block is left out for the third variant of the same reason: a place
    name is not a sentence, and *12 rue de la Paix* would fail an English letter
    for spelling a French street correctly.
    """
    written = docx_template.fill_map(artifact)
    fills = merged_fills(artifact, plan)
    # A letter's address block is the one place an empty answer is the honest
    # one — a street nobody published cannot be filled in, and inventing one
    # puts a fabricated fact on a document going to an employer — and the one
    # place the language check must not look: *12 rue de la Paix* is the right
    # address for a French employer in an English letter.
    address = (
        letter_fields.address_keys(plan.slots)
        if plan.kind == base_documents.COVER_LETTER
        else set()
    )
    problems = docx_template.check_fills(plan.blocks, plan.slots, fills, optional=address)
    if not problems:
        problems.extend(
            page_fit.page_problems(plan.data, plan.blocks, plan.slots, fills, noun=plan.noun)
        )
    if not problems:
        # And the same rule the other way up. Checked only once the page is
        # known to fit, so a document that is both over the ceiling and — after
        # the estimator's own error bar — arguably under the target is told the
        # one thing it can act on. The two can never both be true: one fires
        # above the room, the other below 80% of it.
        problems.extend(
            page_fit.short_problems(
                plan.estimate, plan.open, fills, noun=plan.noun, optional=address
            )
        )

    if not written and plan.open:
        problems.append("You returned no fills at all, and this document has blanks in it.")

    prose = "\n".join(
        written.get(slot.key, "") for slot in plan.open if slot.key not in address
    )
    if foreign := language_check.wrong_language(prose, plan.language):
        problems.append(foreign)

    # Sentence sanity and recruitment boilerplate checks:
    for slot in plan.open:
        text = str(written.get(slot.key, "")).strip()
        if not text:
            continue
        token_name = letter_fields.field_name(slot.token)
        if job_titles.has_gender_indicator(text):
            problems.append(
                f"{slot.name} contains a gender indicator (such as (F/H) or (H/F)). "
                "Remove all gender indicators from document fills."
            )
        if token_name in {"job_title", "job_posting_name"}:
            if bad_caps := job_titles.all_caps_words(text):
                problems.append(
                    f"{slot.name} contains regular word(s) in ALL CAPS ({', '.join(bad_caps)}). "
                    "Write normal words in proper case (e.g. 'Data', not 'DATA')."
                )
            if token_name == "job_title" and any(dash in text for dash in (" - ", " – ", " — ")):
                problems.append(
                    f"{slot.name} contains a raw title dash. Complete the sentence naturally "
                    "(e.g. 'Ingénieur IA pour la conception d'agents autonomes' instead of "
                    "'Ingénieur IA - Conception...')."
                )

    if not problems:
        return ""
    return (
        f"The {plan.noun} fills were rejected. Fix every point below and return the complete "
        "set of fills again:\n\n" + "\n".join(f"- {problem}" for problem in problems)
    )


def _filling_report(artifact: dict, plan: base_documents.Plan) -> str:
    """Show the Critic the document as it will read, not the fills that got there.

    A list of fills is unreadable as a résumé or as a letter — the Critic would
    be scoring fragments out of context, with no way to tell a well-chosen
    course list from one that breaks the sentence it lands in. This renders the
    finished page and marks what was filled.
    """
    fills = merged_fills(artifact, plan)
    lines = docx_template.filled_lines(plan.blocks, plan.slots, fills)
    changed = {index for index, text in lines.items() if any(
        block.index == index and block.text != text for block in plan.blocks
    )}
    page = "\n".join(
        f"{block.index:>3} | {lines.get(block.index, block.text)}"
        + (" ←filled" if block.index in changed else "")
        for block in plan.blocks
    )
    chosen = "\n".join(
        f"{slot.key} {slot.token} → {fills.get(slot.key, '(nothing)')!r}"
        + ("   [from the record, not the agent]" if slot.key in plan.auto else "")
        for slot in plan.slots
    )
    guidance = (
        RESUME_CRITIC_NOTE if plan.kind == base_documents.RESUME else LETTER_CRITIC_NOTE
    )
    return f"""
## The {plan.noun} as it will actually read

The candidate wrote this document. The agent could not edit it — it filled the
{len(plan.open)} blank(s) it was given and every other character is theirs — so
do not score it on what is absent from the page, on its layout, or on wording it
did not choose.

```
{page}
```

### What went into each blank

```
{chosen or "(nothing)"}
```

{guidance}
""".strip()


RESUME_CRITIC_NOTE = """
Score `selection` on whether each fill is the **best available** choice for this
posting out of what the candidate actually offers: the right job title, the four
most relevant courses rather than the first four, the skills this employer
screens for. Score `truthfulness` by checking every course and skill against the
candidate's own lists and profile — an item that is not in them is invented, and
that is the worst thing this can do. Score `fit` on whether each fill reads as a
natural completion of the sentence around it, punctuation and register included:
refuse any fill with gender indicators like (F/H) or (H/F), raw title dashes
(e.g. 'Ingénieur IA - Conception...' instead of 'Ingénieur IA pour la conception...'),
or normal words left in ALL CAPS ('DATA' instead of 'Data').
""".strip()

LETTER_CRITIC_NOTE = """
Score the **paragraphs**, not the letterhead: the greeting, the availability
sentence and the sign-off are the candidate's own and were not written here.

Score `specificity` on whether the opening could be pasted into an application
to a different employer — if it could, that is the defect. Score `truthfulness`
against the profile and the posting: an achievement, a conversation or a detail
about the employer that appears in neither is invented. Score `structure` on
whether the three paragraphs do their three jobs (why they are writing, why this
employer and what they have done, a plain close) **without repeating what the
document already says around them** — a closing paragraph that restates the
availability sentence below it is a letter written twice. Refuse any letter
containing recruitment boilerplate like (F/H) or (H/F) in reference lines or prose,
raw title dashes, or normal words in ALL CAPS ('DATA' -> 'Data'). An empty street
address or postal code is correct when the posting does not give one, and is not
a defect.
""".strip()


def build_applying_team(
    job_id: int,
    resume_plan: base_documents.Plan | None = None,
    letter_plan: base_documents.Plan | None = None,
    personalisation: str = "",
) -> ParallelAgent:
    """A lane per document the run was asked for, each behind its own gate.

    **A plan is the request.** `None` means that document is not part of this
    run, and the lane is simply not built: the résumé alone is the default
    package, the letter joins it when the candidate ticks the box, and the
    letter alone is the run that adds one to an application that already has a
    résumé. At least one of the two is required — a team with no lanes would
    stream a run that produces nothing.

    The letter's lane is the longer one: the Address Scout searches for the
    employer's postal address, the writer fills the letter with the notes in
    front of it, and inside its review loop the Humaniser rewrites the
    paragraphs so they do not read as generated before the Critic ever sees
    them. That is also why it is optional — it costs a grounded search and
    several minutes, and most applications are made through a form with nowhere
    to attach it.

    Each plan is the candidate's own base document for the run's language,
    already read, with its blanks found and priced. They are passed in rather
    than read here so that one run cannot straddle two versions of a document:
    the flow reads each once, hands the same plan to the agent, the gate and the
    Critic, and fills the file it came from.
    """
    if resume_plan is None and letter_plan is None:
        raise ValueError("An applying team needs at least one document to produce.")
    # Everything a Critic is told that is not about one document — the language,
    # and the lists read in it — comes from whichever plan this run has.
    language = (resume_plan or letter_plan).language

    def critic_context(_ctx: ReadonlyContext) -> str:
        # The Critic needs the same ground truth the producer had, so it can tell
        # a supported claim from an invented one — including the two lists the
        # fills must be drawn from, in the same language the producer saw them
        # in, so that a translated course reads here as what it is: an item that
        # is not on the list. Plus which language the candidate asked for, and
        # the candidate's own notes, without which a named contact in the letter
        # looks exactly like an invented one.
        return compose(
            profile_block(),
            candidate_lists_block(language),
            job_block(job_id),
            personalisation_block(personalisation),
            language_block(language),
        )

    def report_context(plan: base_documents.Plan, state_key: str):
        def provider(ctx: ReadonlyContext) -> str:
            artifact = ctx.state.get(state_key)
            if not isinstance(artifact, dict):
                artifact = {}
            blocks = [critic_context(ctx), _filling_report(artifact, plan)]
            if plan.kind == base_documents.COVER_LETTER:
                # The letter's Critic gets the research notes for the same
                # reason the contact shortlist's does: `truthfulness` there is
                # partly the question "was this address on a page somebody
                # read", which cannot be answered without the notes in front of
                # it.
                blocks.append(address_notes_block(str(ctx.state.get(ADDRESS_STATE_KEY) or "")))
            return compose(*blocks)

        return provider

    lanes: list[BaseAgent] = []

    if resume_plan is not None:
        plan = resume_plan
        lanes.append(
            reviewed(
                build_resume_agent(job_id, plan, personalisation),
                rubric=RESUME_RUBRIC,
                artifact_key=RESUME_STATE_KEY,
                context_provider=report_context(plan, RESUME_STATE_KEY),
                hard_check=lambda artifact: hard_check(artifact, plan),
            )
        )

    if letter_plan is not None:
        plan = letter_plan
        lanes.append(
            # The letter's lane is a sequence rather than a bare loop: the
            # address is searched for once, up front, and the writer — which
            # carries an output schema and therefore cannot carry a tool —
            # reads the notes. The revision loop sits inside, so a rejected
            # letter is rewritten against the same research rather than
            # re-searching for an address that has not moved.
            SequentialAgent(
                name="cover_letter_track",
                description="Researches the employer's address, then writes the letter.",
                sub_agents=[
                    build_address_scout(job_id),
                    reviewed(
                        build_cover_letter_agent(job_id, plan, personalisation),
                        rubric=COVER_LETTER_RUBRIC,
                        artifact_key=COVER_LETTER_STATE_KEY,
                        context_provider=report_context(plan, COVER_LETTER_STATE_KEY),
                        hard_check=lambda artifact: hard_check(artifact, plan),
                        # Between the writer and the Critic, so the humanised
                        # prose is what gets scored and what the hard checks
                        # measure — it is what would be sent.
                        then=[
                            build_letter_humaniser(job_id, plan),
                            MergeProse(name="cover_letter_merge", plan=plan),
                        ],
                    ),
                ],
            )
        )

    return ParallelAgent(
        name="applying_team",
        description="Produces and audits the application package.",
        sub_agents=lanes,
    )
