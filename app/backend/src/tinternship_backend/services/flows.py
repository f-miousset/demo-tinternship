"""End-to-end flows: run the agents, persist what they produced, audit it.

The API layer calls these; they own the "and then save it" half that the agents
deliberately do not do themselves. Keeping persistence out of the agents means
a model that forgets to call a tool cannot silently lose a run's work.

## Why the long runs stream

The HR Expert, the Investigator, the Applying team and the Follow-up writer all
take minutes, and a single blocking response that says nothing for that long is
indistinguishable from a hung origin: the proxy in front of the app cuts the
request off at 100 seconds (Cloudflare answers 524) while the run carries on
here to completion. The browser was being told a run had failed when it had not.

So all four are written as generators of `(event_type, data)` pairs — the shape
`api/sse.py` serialises — and the endpoints stream them. Bytes keep moving, so
nothing times out, and the events the run already produces become the progress
the page shows instead of a spinner. The vocabulary is small:

| event    | when |
|----------|------|
| `run`    | once, as soon as there is an `AgentRun` id to link a trace to |
| `phase`  | a stage started: `{phase, message}`, plus `track` when several are in flight |
| `result` | the terminal payload — the same dict the blocking endpoint returned |
| `error`  | the run failed; nothing follows it |

`run_hr_expert` / `run_investigator` / `run_applying` / `run_follow_up` remain
the non-streaming entry points, and are the same code: they drain the generator
and hand back its `result`. The follow-up has one caller of each kind — the
browser streams it, the background sweep in `services/follow_up.py` drains it —
which is the clearest argument for keeping both on one implementation.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any

from google.genai import types
from sqlmodel import select

from ..agents.applying import (
    COVER_LETTER_STATE_KEY,
    RESUME_STATE_KEY,
    build_applying_team,
)
from ..agents.contacts import (
    CONTACTS_STATE_KEY,
    OPENING_STATE_KEY,
    build_contacts,
    build_opener,
)
from ..agents.follow_up import FOLLOW_UP_STATE_KEY, build_follow_up_writer
from ..agents.hr_expert import PLAYBOOK_STATE_KEY, build_hr_expert
from ..agents.interrogator import (
    BRIEF_STATE_KEY,
    build_brief_writer,
    build_interrogator,
    split_completion,
)
from ..agents.interview_prep import INTERVIEW_PREP_STATE_KEY, build_interview_prep
from ..agents.investigator import (
    RANKED_STATE_KEY,
    build_investigator,
    build_matcher,
    clamp_results,
    numbered,
    rank_target,
)
from ..agents.profile_agent import (
    EXTRACTED_STATE_KEY,
    MERGED_STATE_KEY,
    build_profile_extractor,
    build_profile_merger,
)
from ..agents.reader import (
    ASSESSED_STATE_KEY,
    READ_STATE_KEY,
    build_link_intake,
    build_text_intake,
)
from ..agents.runtime import execute, stream, user_message
from ..agents.schemas import MasterProfile
from ..config import get_settings
from ..db.engine import session_scope
from ..db.models import (
    Application,
    ApplicationArtifact,
    ApplicationEvent,
    ArtifactKind,
    JobPosting,
    ProfileSource,
    ProfileSourceKind,
    PromptKind,
    RunKind,
    utcnow,
)
from ..tools.persistence import (
    find_pasted,
    partition_answered,
    paste_key,
    save_job_postings,
    track_posting,
)
from . import (
    base_documents,
    documents,
    docx_template,
    follow_up,
    grounding,
    job_links,
    language_check,
    letter_fields,
    outreach,
    page_fit,
    page_text,
    prompt_store,
    recency,
    render,
    verification,
)
from .audit import audit_artifact
from .context_blocks import SearchFocus, compose, job_block, profile_block
from .feedback import build_digest
from .languages import DEFAULT_LANGUAGE, normalise_language
from .profile_store import profile_as_dict, save_profile

logger = logging.getLogger(__name__)

INTERVIEW_SESSION = "interview"
HR_SESSION = "hr-expert"
INVESTIGATOR_SESSION = "investigator"
LINK_INTAKE_SESSION = "link-intake"
PROFILE_SESSION = "profile"


class RunFailed(RuntimeError):
    """A streaming run reported an `error` event to a caller that wanted a value.

    The message is already the humanised one `runtime.stream` produced for the
    browser, so it is safe to show as-is.
    """


def _count(number: int, noun: str) -> str:
    """`1 posting`, `3 postings` — a progress line is read by a person."""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


# How much of a chat message fits in a run's label. The Traces list gives it one
# line beside a date and a status, and the first few words of a request are what
# tells one run from another there.
HEADLINE_CHARS = 60


def _headline(text: str) -> str:
    """One line of a candidate's message, for a run label."""
    flat = " ".join(text.split())
    return flat if len(flat) <= HEADLINE_CHARS else flat[: HEADLINE_CHARS - 1].rstrip() + "…"


async def drain(source: AsyncIterator[tuple[str, Any]]) -> dict[str, Any]:
    """Run a streaming flow to completion and return its `result` payload.

    A failure arrives as an event rather than an exception — the stream turns it
    into one so the browser gets a message instead of a dead connection — so put
    it back into the shape a non-streaming caller expects.
    """
    result: dict[str, Any] = {}
    async for event_type, data in source:
        if event_type == "result":
            result = data
        elif event_type == "error":
            raise RunFailed(str((data or {}).get("error") or "The run failed."))
    return result


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return {}


# ---------------------------------------------------------------------------
# 1. Interrogator
# ---------------------------------------------------------------------------


async def interview_stream(
    message: str, session_id: str = INTERVIEW_SESSION
) -> AsyncIterator[tuple[str, Any]]:
    """One interview turn, plus the handoff the Interrogator decides on itself.

    The agent ends its closing turn with `COMPLETION_MARKER` rather than telling
    the candidate to press a button. The marker is peeled off every event — it is
    a signal to the app, not prose — and comes back out as a single `complete`
    event once the turn is done, which is what the Account page uses to write the
    brief and then research the playbook. A turn that never carries one is an
    ordinary turn: the "Generate search brief" button still does it by hand.
    """
    finished = False
    async for event_type, data in stream(
        build_interrogator(),
        kind=RunKind.INTERROGATOR,
        session_id=session_id,
        label="interview turn",
        message=user_message(message),
        payload={"message": message[:500]},
    ):
        if event_type == "error":
            yield (event_type, data)
            return
        if event_type == "event" and data.get("text"):
            text, complete = split_completion(str(data["text"]))
            finished = finished or complete
            data = {**data, "text": text}
        yield (event_type, data)

    # After the turn, not in the middle of it: the candidate should have read the
    # Interrogator's goodbye before the brief starts writing under it.
    if finished:
        yield ("complete", {"session_id": session_id})


async def finalise_brief(session_id: str = INTERVIEW_SESSION) -> dict[str, Any]:
    """Read the interview transcript and turn it into the editable search brief."""
    result = await execute(
        build_brief_writer(),
        kind=RunKind.INTERROGATOR,
        session_id=session_id,
        label="write search brief",
        message=user_message(
            "The interview is complete. Produce the definitive SearchBrief from our conversation."
        ),
    )
    brief = _as_dict(result.state.get(BRIEF_STATE_KEY))
    if not brief:
        raise ValueError("The brief writer did not return a usable brief. Try again.")

    prompt = prompt_store.save_prompt(
        PromptKind.SEARCH_BRIEF,
        content=prompt_store.render_search_brief(brief),
        structured=brief,
        title=brief.get("headline", "Search brief"),
        author="agent",
        note="Generated by the Interrogator from the interview transcript.",
        invocation_id=result.invocation_id,
    )

    verdict = await audit_artifact(
        subject_kind="brief",
        artifact=brief,
        session_id=f"{session_id}-audit",
        subject_id=str(prompt.id),
    )

    return {
        "brief": brief,
        "prompt": _prompt_dict(prompt),
        "audit": verdict,
        "run_id": result.run_id,
    }


def _prompt_dict(prompt: Any) -> dict[str, Any]:
    return {
        "id": prompt.id,
        "kind": prompt.kind,
        "version": prompt.version,
        "title": prompt.title,
        "content": prompt.content,
        "structured": prompt.structured,
        "is_active": prompt.is_active,
        "author": prompt.author,
        "note": prompt.note,
        "created_at": prompt.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# 2. HR Expert
# ---------------------------------------------------------------------------


# The run's two halves, in the words the Strategy page shows while it works.
HR_EXPERT_STEPS = {
    "hr_researcher": "Searching for how these roles are actually hired…",
    "playbook_writer": "Writing the playbook from the research…",
}


async def hr_expert_stream(session_id: str = HR_SESSION) -> AsyncIterator[tuple[str, Any]]:
    """Research the brief, write the playbook, then version and audit it.

    Yields `(event_type, data)` pairs; see this module's docstring for why. The
    research half runs grounded searches, which is what makes this run long
    enough to need it.
    """
    state: dict[str, Any] = {}
    run_id = 0
    invocation_id = ""
    speaking = ""
    async for event_type, data in stream(
        build_hr_expert(),
        kind=RunKind.HR_EXPERT,
        session_id=session_id,
        label="research hiring playbook",
        message=user_message("Research this brief and produce the hiring playbook."),
    ):
        if event_type == "run":
            run_id = int(data.get("run_id") or 0)
            yield ("run", data)
        elif event_type == "event":
            # Research then synthesis, in that order — so whoever is speaking is
            # where the run has got to.
            author = str(data.get("author") or "")
            if author in HR_EXPERT_STEPS and author != speaking:
                speaking = author
                yield ("phase", {"phase": author, "message": HR_EXPERT_STEPS[author]})
        elif event_type == "error":
            yield ("error", data)
            return
        elif event_type == "state":
            state = data
        elif event_type == "done":
            invocation_id = str(data.get("invocation_id") or "")

    playbook = _as_dict(state.get(PLAYBOOK_STATE_KEY))
    if not playbook:
        # Nothing to version or audit. Said as an event rather than raised: by
        # now the response is a 200 and the status code is spent.
        yield (
            "error",
            {
                "run_id": run_id,
                "error": "The HR Expert did not produce a playbook. Try again.",
            },
        )
        return

    # Grounded search cites opaque redirect URLs; turn them into links you can check.
    cited = len(playbook.get("sources") or [])
    yield (
        "phase",
        {
            "phase": "sources",
            "message": (
                "Resolving the one citation into a link you can check…"
                if cited == 1
                else f"Resolving {cited} citations into links you can check…"
            ),
        },
    )
    playbook["sources"] = await grounding.resolve_sources(playbook.get("sources") or [])

    yield ("phase", {"phase": "save", "message": "Saving the playbook as a new version…"})
    prompt = prompt_store.save_prompt(
        PromptKind.PLAYBOOK,
        content=prompt_store.render_playbook(playbook),
        structured=playbook,
        title="Hiring playbook",
        author="agent",
        note="Researched by the HR Expert with Google Search grounding.",
        invocation_id=invocation_id,
    )

    yield ("phase", {"phase": "audit", "message": "Auditing the playbook…"})
    verdict = await audit_artifact(
        subject_kind="playbook",
        artifact=playbook,
        session_id=f"{session_id}-audit",
        subject_id=str(prompt.id),
    )

    yield (
        "result",
        {
            "playbook": playbook,
            "prompt": _prompt_dict(prompt),
            "audit": verdict,
            "run_id": run_id,
        },
    )


async def run_hr_expert(session_id: str = HR_SESSION) -> dict[str, Any]:
    """`hr_expert_stream` run to completion, for callers that want the payload."""
    return await drain(hr_expert_stream(session_id))


# ---------------------------------------------------------------------------
# 3. Investigator
# ---------------------------------------------------------------------------


# What each stage of the run is doing, in the words the Jobs page shows while it
# works. Keyed by the agent's ADK name, so renaming one surfaces as a missing
# line rather than a wrong one.
INVESTIGATOR_STEPS = {
    "query_planner": "Planning the searches…",
    "scout": "Searching the priority boards and the open web…",
    "normaliser": "Cleaning and de-duplicating what came back…",
    "matcher": "Scoring each posting against your brief…",
}

# The most links one run may check, as a multiple of the target. A run where
# every link is broken has to stop somewhere, and this is where.
VERIFY_BUDGET = 2


async def investigator_stream(
    session_id: str = INVESTIGATOR_SESSION,
    target_results: int | None = None,
    focus: SearchFocus | None = None,
) -> AsyncIterator[tuple[str, Any]]:
    """Discover, normalise and rank postings, then persist and audit them.

    `target_results` is how many ranked postings the run should come back with —
    the Jobs page slider. `None` falls back to `RESULTS_PER_RUN` in `.env`.

    `focus` is what the candidate typed into the Jobs chat to steer this run, and
    `None` — the "Run Investigator" button — is the run this app has always done.
    It is threaded into the agents rather than filtered for afterwards: a posting
    the searches never went after is not in the list to be re-ranked, so a focus
    applied at the end could only ever throw results away.

    The matcher's order is not the final order. `services/recency.py` re-sorts
    the list on fit *and* age twice: once before the link checks, so the freshest
    matches are the ones that get a slot, and once after, because verification
    reads each posting's published date off the page and that is a better answer
    than the one the ranking was working from.

    Yields `(event_type, data)` pairs; see this module's docstring for why.
    """
    target = clamp_results(target_results)

    yield ("phase", {"phase": "feedback", "message": "Reading what past applications taught us…"})
    digest = await build_digest()

    state: dict[str, Any] = {}
    run_id = 0
    speaking = ""
    async for event_type, data in stream(
        build_investigator(digest or None, target, focus),
        kind=RunKind.INVESTIGATOR,
        session_id=session_id,
        # The ask goes in the label as well as the prompt: the Traces list is a
        # column of "find and rank 15 postings" otherwise, and a steered run is
        # the one you most want to find again.
        label=(
            f"find and rank {target} postings"
            + (f" — {_headline(focus.ask)}" if focus else "")
        ),
        message=user_message(
            f"Find the {target} best-matching internship postings for this brief."
            + (f" The candidate asked for: {focus.ask}" if focus else "")
        ),
        payload={
            "feedback_applied": bool(digest),
            "target_results": target,
            **({"focus": focus.ask} if focus else {}),
        },
    ):
        if event_type == "run":
            run_id = int(data.get("run_id") or 0)
            yield ("run", data)
        elif event_type == "event":
            # One line per stage rather than per event: the four specialists run
            # in order, so whoever is speaking is where the run has got to.
            author = str(data.get("author") or "")
            if author in INVESTIGATOR_STEPS and author != speaking:
                speaking = author
                yield ("phase", {"phase": author, "message": INVESTIGATOR_STEPS[author]})
        elif event_type == "error":
            yield ("error", data)
            return
        elif event_type == "state":
            state = data

    ranked = _as_dict(state.get(RANKED_STATE_KEY))
    jobs = ranked.get("jobs") or []

    # Postings on the table, nothing scored, and not a word about why. A matcher
    # that means "none of these are worth showing" says so in `strategy_notes` —
    # the prompt asks for exactly that — so silence here means the answer never
    # arrived: most often a response cut off before its first posting closed,
    # which `agents/salvage.py` can only salvage an empty list from. The
    # postings are in session state and the searching is already paid for, so
    # the scoring runs again on its own: one model call, not another six
    # minutes. Being wrong about the cause costs that one call.
    if not jobs and not ranked.get("strategy_notes") and numbered(state):
        yield (
            "phase",
            {
                "phase": "rescore",
                "message": "The scoring came back empty — scoring them again…",
            },
        )
        ranked = await _score_again(session_id, target, digest, focus)
        jobs = ranked.get("jobs") or []
        if not jobs:
            yield (
                "error",
                {
                    "run_id": run_id,
                    "error": (
                        "The postings were found, but scoring them came back empty twice — "
                        "usually a model answer that was cut short. Try again, or lower the "
                        "number of results on the slider."
                    ),
                },
            )
            return

    # A posting's link has to be the posting's link. Google Search grounding
    # hands the model `vertexaisearch.cloud.google.com/grounding-api-redirect/…`
    # URLs and it cites them faithfully — run 8 saved a real Saegus posting
    # behind one — but that link names Google rather than the employer, expires
    # within weeks, and defeats the shape check below by hiding the site it
    # opens. Resolved here because this is the last point before the URL is
    # judged, verified, shown as a source and turned into the row's identity.
    redirects = sum(
        1 for job in jobs if grounding.is_grounding_redirect(str(job.get("url", "")))
    )
    if redirects:
        yield (
            "phase",
            {
                "phase": "redirects",
                "message": (
                    "Following one Google search redirect back to the posting…"
                    if redirects == 1
                    else f"Following {redirects} Google search redirects back to the postings…"
                ),
            },
        )
    jobs = await grounding.resolve_jobs(jobs)

    # A posting you cannot open is not a result. Drop the ones whose URL is
    # missing outright, is a careers index, a board search page or a company
    # profile on its face, or is a grounding redirect that could not be
    # followed — no HTTP request is needed to know that, and dropping them
    # before the cut means a real posting takes the freed slot.
    jobs, link_drops = job_links.partition(jobs)
    if link_drops:
        logger.warning("Investigator returned postings with no usable link: %s", link_drops)

    # A posting the candidate already answered is not a result either. Dismissed
    # is a verdict and an application is already on the Tracker, so bringing
    # either back re-asks a settled question. `known_postings_block` asks the
    # planner, the Scout and the matcher not to; this is the promise behind that
    # request, and it sits here — beside the link drop and before the cut — so a
    # posting removed for it frees its slot for one of the matcher's spares.
    jobs, answered_drops = partition_answered(jobs)
    if answered_drops:
        logger.info("Investigator re-proposed postings the candidate answered: %s", answered_drops)

    # Re-order on age before anything is spent checking links. The matcher was
    # asked to weight recency and mostly does, but the order it returns is its
    # own judgement — and this list is about to be consumed front-first, so
    # whatever sits at the top is what the candidate gets. Sorting here is what
    # turns "prefer recent postings" from a request into the run's behaviour.
    jobs = recency.rank(jobs)

    # Fetch every link before trusting it, and keep only the postings whose link
    # actually reaches the posting. A grounded model still produces
    # plausible-but-invented URLs; a board still 404s a job it closed yesterday.
    #
    # In waves, cheapest first. The common case is one wave of exactly `target`
    # links, all of them fine. Every posting dropped for a dead link or a
    # careers-page link pulls the next-best candidate into the next wave — which
    # is what the matcher's spares are for — so a run only pays for the checks a
    # broken link actually costs it.
    queue, kept, budget = list(jobs), [], target * VERIFY_BUDGET
    wave = 0
    while queue and len(kept) < target and budget > 0:
        take = min(len(queue), max(1, target - len(kept)), budget)
        batch, queue = queue[:take], queue[take:]
        budget -= take
        wave += 1
        yield (
            "phase",
            {
                "phase": "verify",
                "message": (
                    f"Checking {_count(take, 'posting link')} — the ones behind bot "
                    "protection get opened in a browser…"
                    if wave == 1
                    else f"Replacing {_count(take, 'broken link')} with the next best…"
                ),
            },
        )
        checked, _ = await verification.verify_jobs(batch)
        for job in checked:
            if str(job.get("url_status", "")) in verification.UNUSABLE:
                link_drops[job["url_status"]] = link_drops.get(job["url_status"], 0) + 1
                logger.info(
                    "Dropped %r at %s: %s",
                    job.get("title", ""),
                    job.get("url", ""),
                    (job.get("risks") or ["link does not reach the posting"])[0],
                )
            else:
                kept.append(job)

    # Sort again, now that the pages have been read. Verification pulls the
    # `datePosted` the employer published out of every page it fetched, so a
    # posting that reached this point undated — or dated from a search snippet —
    # may have just acquired a better answer than the one it was ordered on.
    jobs = recency.rank(kept)[:target]

    url_tally: dict[str, int] = {}
    for job in jobs:
        status = str(job.get("url_status", verification.UNCHECKED))
        url_tally[status] = url_tally.get(status, 0) + 1

    freshness = recency.tally(jobs)

    fresh = freshness["week"] + freshness["month"]
    yield (
        "phase",
        {
            "phase": "save",
            "message": (
                f"Saving {_count(len(jobs), 'posting')}, freshest first — "
                f"{fresh} published in the last month…"
                if fresh
                else f"Saving {_count(len(jobs), 'posting')}…"
            ),
        },
    )
    saved = save_job_postings(jobs)

    yield ("phase", {"phase": "audit", "message": "Auditing the ranking…"})
    verdict = await audit_artifact(
        subject_kind="job_ranking",
        artifact={"jobs": jobs[:25], "strategy_notes": ranked.get("strategy_notes", "")},
        session_id=f"{session_id}-audit",
        subject_id=str(run_id),
    )

    yield (
        "result",
        {
            "jobs": jobs,
            "saved": saved,
            "url_check": url_tally,
            "freshness": freshness,
            "link_drops": link_drops,
            "answered_drops": answered_drops,
            "strategy_notes": ranked.get("strategy_notes", ""),
            "feedback_applied": digest,
            "audit": verdict,
            "run_id": run_id,
            "target_results": target,
            "focus": focus.ask if focus else "",
        },
    )


async def _score_again(
    session_id: str,
    target: int,
    digest: dict[str, Any] | None,
    focus: SearchFocus | None = None,
) -> dict[str, Any]:
    """Re-run the matcher alone, over the postings the run already has.

    The four Investigator stages talk to each other through session state, so
    the normalised list outlives the run that produced it and the matcher can
    be built and run against it a second time on its own. A repetition loop is
    a property of one sample rather than of the prompt, so a second draw is
    usually enough — and if it is not, the caller says so instead of saving an
    empty run.
    """
    try:
        result = await execute(
            build_matcher(rank_target(target), digest or None, focus),
            kind=RunKind.INVESTIGATOR,
            session_id=session_id,
            label="score the postings again",
            message=user_message("Score the postings listed in your instructions."),
        )
    except Exception:  # a failed retry must not replace the caller's plain message
        logger.exception("Re-scoring the Investigator's postings failed")
        return {}
    return _as_dict(result.state.get(RANKED_STATE_KEY))


async def run_investigator(
    session_id: str = INVESTIGATOR_SESSION,
    target_results: int | None = None,
    focus: SearchFocus | None = None,
) -> dict[str, Any]:
    """`investigator_stream` run to completion, for callers that want the payload."""
    return await drain(investigator_stream(session_id, target_results, focus))


# ---------------------------------------------------------------------------
# 3b. The pasted link
# ---------------------------------------------------------------------------


# The two agent stages, in the words the Jobs page shows while they run. Keyed
# by the agent's ADK name, like `INVESTIGATOR_STEPS`.
LINK_INTAKE_STEPS = {
    "reader": "Reading the posting…",
    "matcher": "Scoring it against your brief…",
}

# Below this much extracted text, the fetch did not return a posting — it
# returned a challenge page, a cookie wall, or the empty shell of a page that
# paints itself in JavaScript. Even a terse posting clears it several times
# over, and the answer is to open a real browser rather than to guess.
MIN_PAGE_TEXT = 400


def normalise_url(raw: str) -> str:
    """What the candidate pasted, as a URL.

    Copying a link off a phone brings whitespace around it, and plenty of people
    paste `welcometothejungle.com/…` without the scheme. Neither is a mistake
    worth an error message.

    Whitespace *inside* what is left is not tidied away, because a URL has none:
    the string is prose, and `https://` glued to the front of a sentence would
    turn "did you mean to paste a link?" into a fetch of something nonsensical.
    """
    url = (raw or "").strip()
    if not url or any(character.isspace() for character in url):
        return url
    if "://" not in url:
        url = f"https://{url}"
    return url


async def import_link_stream(
    url: str, session_id: str = LINK_INTAKE_SESSION
) -> AsyncIterator[tuple[str, Any]]:
    """Read one pasted posting link, score it, verify it, save it.

    The second way onto the Jobs page, and deliberately the same destination as
    the first: it ends in `save_job_postings`, so the posting it adds is a
    `JobPosting` row like any other and everything downstream — applying,
    rendering, the tracker, the follow-up sweep — works on it without knowing
    where it came from.

    What it does *not* share with a search run is the right to say no. The
    Investigator drops a weak posting because a slot is worth more to a better
    one; here the candidate asked for this specific posting, so a low score is
    an answer and not a reason to discard it. The only refusals are about the
    link itself: one that does not open a posting has nothing to read, and
    saving a card built out of a careers-page navigation menu would be worse
    than telling them so.

    It also says yes to the posting: `_track_posting` creates the application
    the deck's right swipe would have created. The candidate already chose this
    one, and the deck exists to make a choice they have made.

    Yields `(event_type, data)` pairs; see this module's docstring for why.
    """
    url = normalise_url(url)
    if not url.startswith(("http://", "https://")):
        yield ("error", {"error": "That does not look like a link. Paste the posting's URL."})
        return

    # A link copied out of an AI answer can be a Google search redirect rather
    # than the posting's own URL, so follow it first: the candidate meant the
    # page at the end of it, and that is also the link worth saving, since the
    # redirect expires. Costs nothing for an ordinary URL — `resolve_url`
    # short-circuits before opening a client.
    url = await grounding.resolve_url(url)

    # Judged on shape before anything else is spent on it: a careers index or a
    # board search page is not a posting, and the same rule that drops those
    # from a search run can say so here in a millisecond instead of after two
    # model calls.
    shape = job_links.classify(url)
    if shape.kind != job_links.POSTING:
        yield (
            "error",
            {
                "error": (
                    "That link does not open a single job posting — "
                    f"{shape.reason or 'it looks like a listing rather than one role'}. "
                    "Open the posting itself and paste the link from there."
                )
            },
        )
        return

    yield ("phase", {"phase": "fetch", "message": "Opening the link…"})
    check, body = await verification.fetch_posting(url)
    page = page_text.for_reader(body)

    if check.status == verification.BLOCKED or len(page) < MIN_PAGE_TEXT:
        # An HTTP client is not shown the posting on a board behind a WAF — the
        # blind spot that made `browser_check` necessary in the first place —
        # and Welcome to the Jungle is this candidate's first-priority board.
        # A browser runs the challenge and reads what a person would see.
        from . import browser_check

        if browser_check.enabled():
            yield (
                "phase",
                {
                    "phase": "browser",
                    "message": "The site did not answer with the posting — opening it in a browser…",
                },
            )
            rendered = await browser_check.read_page(url)
            if rendered is not None:
                if rendered.verdict is not None:
                    status, note = rendered.verdict
                    check = replace(check, status=status, note=note)
                page = page_text.for_reader(rendered.html) or rendered.text[: page_text.TEXT_LIMIT]

    if check.status in verification.UNUSABLE:
        why = check.note or f"it answered {check.http_status}"
        yield (
            "error",
            {
                "error": (
                    f"That link does not reach a posting — {why}. If the role is still open, "
                    "find it on the company's careers page and paste that link."
                )
            },
        )
        return

    if len(page) < MIN_PAGE_TEXT:
        yield (
            "error",
            {
                "error": (
                    "The page came back with nothing readable on it — usually bot protection, "
                    "or a page that needs a sign-in. Open it yourself and paste the posting's "
                    "text into the brief, or try the employer's own careers site."
                )
            },
        )
        return

    # No feedback digest here, unlike a search run: a paste is scored against
    # the brief alone, which saves a whole model call. See `agents/reader.py`.
    state: dict[str, Any] = {}
    run_id = 0
    speaking = ""
    async for event_type, data in stream(
        build_link_intake(url, page),
        kind=RunKind.LINK_INTAKE,
        session_id=session_id,
        label=f"read and score {url[:120]}",
        message=user_message("Read the posting on the page in your instructions and score it."),
        payload={"url": url, "browser_read": check.note or ""},
    ):
        if event_type == "run":
            run_id = int(data.get("run_id") or 0)
            yield ("run", data)
        elif event_type == "event":
            author = str(data.get("author") or "")
            if author in LINK_INTAKE_STEPS and author != speaking:
                speaking = author
                yield ("phase", {"phase": author, "message": LINK_INTAKE_STEPS[author]})
        elif event_type == "error":
            yield ("error", data)
            return
        elif event_type == "state":
            state = data

    posting = _as_dict(state.get(READ_STATE_KEY))
    # An empty title is how the Reader reports "this page is not one posting" —
    # a careers index that survived the shape check, a search page, a login
    # wall. Saying so beats saving a card assembled from a navigation menu.
    if not str(posting.get("title", "")).strip():
        yield (
            "error",
            {
                "error": (
                    "That page does not look like a single job posting — it reads as a careers "
                    "page, a list of roles, or a sign-in wall. Open the posting itself and paste "
                    "that link."
                )
            },
        )
        return

    job = {**posting, **_as_dict(state.get(ASSESSED_STATE_KEY))}
    # The URL is the candidate's, not the model's. The Reader is told to copy it
    # verbatim and mostly does, but this is the one field the whole row is
    # identified by — and a prompt is a request, a promise lives in Python.
    job["url"] = url
    job["source"] = str(job.get("source") or "") or job_links.site_name(url)

    job = verification.annotate(job, check)
    # `posted_on` and `posted_days_ago`, from whichever date survived: the
    # page's own `datePosted` where it published one, the Reader's reading of
    # the prose where it did not.
    job = recency.rank([job])[0]

    yield ("phase", {"phase": "save", "message": "Saving it to your list…"})
    key = paste_key(url)
    saved = save_job_postings([job], pasted_as=key)
    job_id, was_dismissed, was_trashed = _restore_posting(job, key)
    application_id, tracked = _track_posting(job_id)

    yield ("phase", {"phase": "audit", "message": "Auditing the score…"})
    verdict = await audit_artifact(
        subject_kind="job_ranking",
        artifact={"jobs": [job], "strategy_notes": "One posting, imported from a link."},
        session_id=f"{session_id}-audit",
        subject_id=str(run_id),
    )

    yield (
        "result",
        {
            "job": job,
            "job_id": job_id,
            "saved": saved,
            "already_saved": bool(saved.get("updated")),
            "restored": was_dismissed,
            "untrashed": was_trashed,
            "application_id": application_id,
            "tracked": tracked,
            "url_check": {job.get("url_status", verification.UNCHECKED): 1},
            "audit": verdict,
            "run_id": run_id,
        },
    )


def _restore_posting(job: dict[str, Any], key: str) -> tuple[int, bool, bool]:
    """The saved row's id, and whether this import undid an answer the candidate gave.

    Pasting a posting is an explicit "I want this one", which outranks a verdict
    from a previous run — so unlike an Investigator run, this path takes it back
    out of whichever pile it was in. `save_job_postings` deliberately does not:
    for a search run, a dismissal is the candidate's answer and re-finding a
    posting is not a reason to overrule it.

    There are two piles, and both have to be checked here or the paste has no
    visible effect at all:

    * **The Jobs trash** — `dismissed`, cleared so the posting is undecided
      again. `_track_posting` then decides it: a pasted posting goes to the
      Tracker rather than back to the deck.
    * **The Tracker's trash** — the posting became an application and the
      candidate threw that away. Clearing `trashed_at` puts the application back
      on the board with everything it had, which is the right destination: they
      already decided this posting was worth tracking.

    Both answers are *reported* from here, and that is why the untrash happens
    here rather than being left to `_track_posting` — which clears the same flag
    a moment later, idempotently. This function has to read the row before it is
    written to say what the paste undid, and a caller that read one place and
    wrote another would be one refactor away from disagreeing with itself.

    Found with `persistence.find_pasted` and the paste's `key`, which is the
    same lookup `save_job_postings(pasted_as=key)` just used to decide *where*
    to write — the two answers have to be the same answer. Until 2026-10-06 both
    used `find_existing`, whose company-and-title match folded a second posting
    at the same company with a look-alike title into the first one's row; see
    `persistence.paste_key`.

    Returns `(job_id, was_dismissed, was_trashed)`.
    """
    with session_scope() as session:
        posting = find_pasted(session, key, str(job.get("url") or ""))
        if posting is None:
            return 0, False, False
        was_dismissed = bool(posting.dismissed)
        if was_dismissed:
            posting.dismissed = False
            # A posting deleted forever comes back too: the tombstone
            # `services/trash.py` left is the row `save_job_postings` just
            # refilled, so all that is left of the deletion is the stamp.
            posting.purged_at = None
            session.add(posting)
        application = session.exec(
            select(Application).where(Application.job_posting_id == posting.id)
        ).first()
        was_trashed = application is not None and application.trashed_at is not None
        if was_trashed:
            application.trashed_at = None
            session.add(application)
        return int(posting.id or 0), was_dismissed, was_trashed


def _track_posting(job_id: int) -> tuple[int | None, bool]:
    """Say yes to a pasted posting on the candidate's behalf — the swipe right.

    Pasting a posting is not the same question as being shown one. The deck asks
    *"is this worth your time?"* and a run's fifteen cards each have to earn the
    answer; a paste is the candidate arriving with the answer already given —
    they found this posting, read it, and went and fetched its link or its text.
    Asking them to swipe right on the one card they chose is a step that can only
    go one way, and it is the step between "I want this one" and the documents
    they actually came for.

    So the import creates the application itself, with the same
    `persistence.track_posting` the deck's right swipe calls, which is what makes
    the resulting row indistinguishable from a swiped one — same first event,
    same `saved` status, same place on the board. Never pinned: a pin is "and
    this one first", which is a second thing to say and the deck's up swipe is
    where it is said.

    Two consequences worth stating, because they are what the candidate sees:

    * **The posting leaves the deck.** `api/jobs.list_jobs` keeps every posting
      with an application out of it, so a pasted posting is never swiped on. That
      is the point — the result card links straight to the application instead.
    * **It is answered**, so no later Investigator run re-proposes it
      (`partition_answered`). Changing their mind means throwing the application
      away from the Tracker, which is the same verdict the deck's left swipe
      gives — see `documentation/triage.md`.

    `job_id` is 0 when nothing was saved, which `save_job_postings` allows for a
    posting it refused; there is nothing to track then.

    Returns `(application_id, created)` — `created` false when the posting was
    already on the Tracker, which is the honest thing to say on a re-paste.
    """
    if not job_id:
        return None, False
    with session_scope() as session:
        posting = session.get(JobPosting, job_id)
        application, created = track_posting(
            session,
            job_id,
            note="Saved automatically — you pasted this posting.",
            language=language_check.posting_language(posting) if posting else "",
        )
        return int(application.id or 0), created


async def import_link(url: str, session_id: str = LINK_INTAKE_SESSION) -> dict[str, Any]:
    """`import_link_stream` run to completion, for callers that want the payload."""
    return await drain(import_link_stream(url, session_id))


# The shortest paste worth starting two model calls over. A real posting runs to
# thousands of characters; below this it is a title, a URL somebody meant to put
# in the other field, or an accidental paste — and the honest answer is to say
# so in a millisecond rather than to invent a card from four words.
MIN_PASTED_TEXT = 200

TEXT_INTAKE_SESSION = "text-intake"


async def import_text_stream(
    text: str, session_id: str = TEXT_INTAKE_SESSION
) -> AsyncIterator[tuple[str, Any]]:
    """Read one posting the candidate pasted the *text* of, score it, save it.

    The third way onto the Jobs page, and the one that works when the other two
    cannot. A posting reaches somebody as an email, a PDF, a screenshot's worth
    of text in a message, or on a board whose bot protection beats both our HTTP
    client and the browser — and until 2026-09-03 all of those ended the same
    way: the candidate had the posting in front of them and no way to get it
    into the app.

    Everything after the reading is the pasted link's pipeline, deliberately.
    Same Matcher, same scale, same `save_job_postings` and the same
    `_track_posting` — so this posting goes to the Tracker as a paste always
    does, and applying, the tracker and the follow-up sweep work on it without
    knowing where it came from.

    Two differences, both about the link:

    * **There may not be one.** The Reader copies a URL only if the text itself
      states one, and a posting with no link is saved anyway — the one place in
      the app where that is allowed, because here the candidate already has the
      posting and a missing link costs them nothing they had.
    * **A link the text does name is proved like any other**, and dropped rather
      than saved when it is not a posting. It is a bonus, not the reason the
      posting is here, so a bad one is silently discarded instead of refusing
      the whole import the way the pasted-link path must.
    """
    text = (text or "").strip()
    if len(text) < MIN_PASTED_TEXT:
        yield (
            "error",
            {
                "error": (
                    "That is too short to read as a job posting. Paste the whole posting — "
                    "the title, the company and what the role actually is. If what you have "
                    "is a link, use “Paste a link” instead."
                )
            },
        )
        return

    # The same ceiling the fetched page gets. Past it, a paste is the newsletter
    # the posting arrived in rather than the posting.
    text = text[: page_text.TEXT_LIMIT]

    state: dict[str, Any] = {}
    run_id = 0
    speaking = ""
    async for event_type, data in stream(
        build_text_intake(text),
        kind=RunKind.TEXT_INTAKE,
        session_id=session_id,
        label=f"read and score pasted text ({len(text)} chars)",
        message=user_message("Read the posting in your instructions and score it."),
        payload={"characters": len(text)},
    ):
        if event_type == "run":
            run_id = int(data.get("run_id") or 0)
            yield ("run", data)
        elif event_type == "event":
            author = str(data.get("author") or "")
            if author in LINK_INTAKE_STEPS and author != speaking:
                speaking = author
                yield ("phase", {"phase": author, "message": LINK_INTAKE_STEPS[author]})
        elif event_type == "error":
            yield ("error", data)
            return
        elif event_type == "state":
            state = data

    posting = _as_dict(state.get(READ_STATE_KEY))
    # An empty title is how the Reader says "this is not one posting" — a list
    # of several roles, an About page, an unrelated email. The same refusal the
    # link path makes, and for the same reason: a card assembled out of a
    # signature block looks exactly like a real one.
    if not str(posting.get("title", "")).strip():
        yield (
            "error",
            {
                "error": (
                    "That does not read as a single job posting — it looks like a list of "
                    "roles, a company page, or something else entirely. Paste the posting "
                    "itself: the title, the employer and what the role involves."
                )
            },
        )
        return

    job = {**posting, **_as_dict(state.get(ASSESSED_STATE_KEY))}

    yield ("phase", {"phase": "verify", "message": "Checking any link the text carried…"})
    job, check, link_note = await _link_from_text(str(job.get("url") or ""), job)

    job = recency.rank([job])[0]

    yield ("phase", {"phase": "save", "message": "Saving it to your list…"})
    key = paste_key(str(job.get("url") or ""), text)
    saved = save_job_postings([job], allow_missing_url=True, pasted_as=key)
    job_id, was_dismissed, was_trashed = _restore_posting(job, key)
    application_id, tracked = _track_posting(job_id)

    yield ("phase", {"phase": "audit", "message": "Auditing the score…"})
    verdict = await audit_artifact(
        subject_kind="job_ranking",
        artifact={"jobs": [job], "strategy_notes": "One posting, pasted as text."},
        session_id=f"{session_id}-audit",
        subject_id=str(run_id),
    )

    yield (
        "result",
        {
            "job": job,
            "job_id": job_id,
            "saved": saved,
            "already_saved": bool(saved.get("updated")),
            "restored": was_dismissed,
            "untrashed": was_trashed,
            "application_id": application_id,
            "tracked": tracked,
            "url_check": {job.get("url_status", verification.UNCHECKED): 1},
            "link_note": link_note,
            "audit": verdict,
            "run_id": run_id,
        },
    )


async def _link_from_text(
    url: str, job: dict[str, Any]
) -> tuple[dict[str, Any], verification.UrlCheck | None, str]:
    """Keep a URL the pasted text named only if it opens the posting.

    Same rule as everywhere else — every link is fetched before it is saved —
    with a different consequence. On the pasted-link path a link that does not
    open a posting is the whole import failing, because the link *was* the
    import. Here it is a detail the text happened to carry, so it is dropped
    with a sentence and the posting is saved without it.

    Returns the job, the check if one was made, and what to tell the candidate
    about their link — empty when there is nothing worth saying.
    """
    job = dict(job)
    url = normalise_url(url)
    if not url.startswith(("http://", "https://")):
        job["url"] = ""
        job["url_status"] = verification.UNCHECKED
        job["url_http_status"] = 0
        return job, None, "The text did not carry a link, so this posting has none."

    url = await grounding.resolve_url(url)
    shape = job_links.classify(url)
    if shape.kind != job_links.POSTING:
        job["url"] = ""
        job["url_status"] = verification.UNCHECKED
        job["url_http_status"] = 0
        return (
            job,
            None,
            f"The link in the text was dropped — {shape.reason or 'it is not a single posting'}.",
        )

    checks = await verification.check_urls([url])
    check = checks.get(url)
    if check is None or check.status in verification.UNUSABLE:
        why = (check.note if check else "") or "it did not reach the posting"
        job["url"] = ""
        job["url_status"] = verification.UNCHECKED
        job["url_http_status"] = 0
        return job, None, f"The link in the text was dropped — {why}."

    job["url"] = url
    job["source"] = str(job.get("source") or "") or job_links.site_name(url)
    job = verification.annotate(job, check)
    return job, check, ""


async def import_text(text: str, session_id: str = TEXT_INTAKE_SESSION) -> dict[str, Any]:
    """`import_text_stream` run to completion, for callers that want the payload."""
    return await drain(import_text_stream(text, session_id))


# ---------------------------------------------------------------------------
# 4. Profile intake
# ---------------------------------------------------------------------------


async def _extract_document(
    *, label: str, payload: documents.DocumentPayload, session_id: str
) -> tuple[dict[str, Any], str]:
    result = await execute(
        build_profile_extractor(),
        kind=RunKind.PROFILE_PARSE,
        session_id=session_id,
        label=f"extract {label}",
        message=types.Content(
            role="user", parts=[*payload.parts, types.Part(text=payload.text)]
        ),
    )
    return _as_dict(result.state.get(EXTRACTED_STATE_KEY)), result.invocation_id


async def remerge_profile() -> dict[str, Any]:
    """Rebuild the master profile from every parsed source."""
    with session_scope() as session:
        sources = session.exec(
            select(ProfileSource)
            .where(ProfileSource.status == "parsed")
            .order_by(ProfileSource.created_at)
        ).all()
        payloads = [
            {"label": s.label, "kind": s.kind, "extracted": s.extracted} for s in sources
        ]

    if not payloads:
        return {}
    if len(payloads) == 1:
        master = MasterProfile.model_validate(payloads[0]["extracted"])
    else:
        result = await execute(
            build_profile_merger(payloads),
            kind=RunKind.PROFILE_PARSE,
            session_id=f"{PROFILE_SESSION}-merge",
            label="merge profile sources",
            message=user_message("Merge the extracted sources into one master profile."),
        )
        merged = _as_dict(result.state.get(MERGED_STATE_KEY))
        master = MasterProfile.model_validate(merged) if merged else MasterProfile()

    save_profile(master)
    return master.model_dump()


async def ingest_upload(filename: str, data: bytes, *, label: str = "") -> dict[str, Any]:
    """Ingest an uploaded résumé, LinkedIn PDF, or LinkedIn data-export ZIP."""
    settings = get_settings()
    label = label or filename
    stored = settings.uploads_path / filename
    stored.write_bytes(data)

    lower = filename.lower()
    is_linkedin_pdf = "linkedin" in lower and lower.endswith(".pdf")

    if documents.looks_like_linkedin_archive(filename, data):
        # Structured CSVs — parse them directly, no model call needed.
        extracted = documents.parse_linkedin_archive(data).model_dump()
        kind = ProfileSourceKind.LINKEDIN_ARCHIVE
        invocation_id = ""
    else:
        payload = documents.payload_for_upload(filename, data)
        extracted, invocation_id = await _extract_document(
            label=label, payload=payload, session_id=f"{PROFILE_SESSION}-{abs(hash(filename)) % 10000}"
        )
        if is_linkedin_pdf:
            kind = ProfileSourceKind.LINKEDIN_PDF
        elif lower.endswith(".docx"):
            kind = ProfileSourceKind.UPLOAD_DOCX
        else:
            kind = ProfileSourceKind.UPLOAD_PDF

    with session_scope() as session:
        source = ProfileSource(
            kind=kind,
            label=label,
            file_path=str(stored),
            extracted=extracted,
            status="parsed" if extracted else "failed",
            error="" if extracted else "The extractor returned nothing usable.",
            invocation_id=invocation_id,
        )
        session.add(source)
        session.flush()
        source_id = source.id

    profile = await remerge_profile()
    return {"source_id": source_id, "kind": kind, "extracted": extracted, "profile": profile}


async def ingest_base_document(
    kind: str, language: str, filename: str, data: bytes
) -> dict[str, Any]:
    """Store one of the four base documents, and — for a résumé — extract the profile too.

    Two things happen on a résumé upload, deliberately. The file becomes *the*
    document that gets filled in and sent for that language — see
    `services/base_documents.py` — and it is *also* read by the profile
    extractor like any other import, so the Matcher, the Interrogator and the
    Interview Coach have structured facts. Asking the candidate to upload the
    same CV twice, once as a template and once as evidence, would be an apology
    for our own data model.

    A **cover letter is not extracted**, and that is the one asymmetry between
    the kinds. A letter template is a letterhead, a salutation and three
    brackets: everything in it that is a career fact is already in the profile
    from the CV, so the extraction would spend a model call and a minute of the
    candidate's time to learn nothing — and what it did learn ("Available for a
    six-month internship starting in January 2027") would be a sentence from a
    template, filed as a fact about them.

    A failed extraction does not fail the upload. The document itself is the
    part that matters and it is already on disk; the row is marked `failed` with
    the reason, the Account page shows it, and the profile can be filled in by
    hand or from another source. Losing the base résumé because Gemini was
    rate-limited would be the worse trade.
    """
    descriptor = base_documents.kind_of(kind)
    language = normalise_language(language)
    blocks = base_documents.validate(kind, data)
    fit = page_fit.measure(data)
    slots = docx_template.find_slots(blocks)

    stored = base_documents.stored_path(kind, language, filename)
    stored.write_bytes(data)
    source = base_documents.replace(kind, language, label=filename, file_path=str(stored))

    extracted: dict[str, Any] = {}
    invocation_id = ""
    error = ""
    if descriptor.extracted:
        payload = documents.docx_payload(
            data, f"{filename} (the candidate's {language} {descriptor.noun})"
        )
        try:
            extracted, invocation_id = await _extract_document(
                label=filename, payload=payload, session_id=f"{PROFILE_SESSION}-base-{language}"
            )
            error = "" if extracted else "The extractor returned nothing usable."
        except Exception as exc:
            logger.warning("Could not extract the %s base résumé", language, exc_info=True)
            extracted, invocation_id, error = {}, "", f"The extractor failed: {exc}"

    status = "parsed" if (extracted or not descriptor.extracted) else "failed"
    with session_scope() as session:
        row = session.get(ProfileSource, source.id)
        if row is not None:
            row.extracted = extracted
            row.status = status
            row.error = error
            row.invocation_id = invocation_id
            session.add(row)

    profile = await remerge_profile() if descriptor.extracted else profile_as_dict()
    return {
        "source_id": source.id,
        "kind": descriptor.key,
        "language": language,
        "blocks": len(blocks),
        "placeholders": len(slots),
        # What the candidate most needs to know about the file they just
        # uploaded, and the one thing they cannot see by looking at it: how much
        # room is left for the blanks. Their CV is one page by design and the
        # filling has to keep it there.
        "page": page_fit.describe(fit, noun=descriptor.noun),
        "room": fit.slack_chars,
        "crowded": bool(slots) and fit.slack_chars < page_fit.required_room(slots),
        "language_warning": base_documents.language_warning(kind, blocks, language),
        "status": status,
        "error": error,
        "profile": profile,
    }


# ---------------------------------------------------------------------------
# 5. Applying
# ---------------------------------------------------------------------------


def _artifact_session(job_id: int) -> str:
    return f"applying-{job_id}"


# The two tracks of an applying run, keyed by the producer's ADK name. Their
# critic and gate are named after them by `agents/critic.py::reviewed`, so an
# event's author says both which artifact it is about and what is happening to
# it. The track ids are artifact kinds, which is how the page matches a progress
# line to the tab it will fill.
APPLYING_TRACKS = {
    "resume_agent": ArtifactKind.RESUME,
    "cover_letter_agent": ArtifactKind.COVER_LETTER,
}

# The letter's lane has two steps that are not producers and are worth a line on
# the page anyway: the grounded search for the employer's address, which is the
# slowest thing on that lane and the one whose result the candidate may want to
# check, and the Humaniser, which is the only step that changes what the letter
# actually sounds like. Keyed apart from the producers because neither has a
# critic or a gate to be named after it.
APPLYING_STEPS = {
    "address_scout": (ArtifactKind.COVER_LETTER, "researching"),
    "cover_letter_humaniser": (ArtifactKind.COVER_LETTER, "humanising"),
}

TRACK_LABELS = {
    ArtifactKind.RESUME: "résumé",
    ArtifactKind.COVER_LETTER: "cover letter",
}

STAGE_MESSAGES = {
    "researching": "Looking up the employer's postal address…",
    "writing": "Writing the {label}…",
    "humanising": "Rewriting the letter so it does not read as generated…",
    "reviewing": "The Critic is reading the {label}…",
    "revising": "Revising the {label} on the Critic's notes…",
    "gate": "The Critic has ruled on the {label}.",
    "saved": "Saved the {label}.",
}


def _applying_stage(author: str, stages: dict[str, str]) -> tuple[str, str] | None:
    """Which track an event belongs to, and what stage it puts that track at."""
    for suffix, stage in (("_critic", "reviewing"), ("_gate", "gate")):
        if author.endswith(suffix):
            track = APPLYING_TRACKS.get(author[: -len(suffix)])
            return (track, stage) if track else None

    if step := APPLYING_STEPS.get(author):
        return step

    track = APPLYING_TRACKS.get(author)
    if track is None:
        return None
    # A producer speaking after its critic has is a revision, not a first draft —
    # which is exactly what the gate sent it back to do. After the scout or the
    # Humaniser it is still the first draft: neither is a rejection.
    return track, ("revising" if stages.get(track) in {"reviewing", "gate"} else "writing")


def _stage_message(track: str, stage: str, text: str) -> str:
    label = TRACK_LABELS.get(track, track)
    if stage == "gate":
        # The gate says either "Audit résumé: 8.2/10 … passed" or the notes it is
        # sending the artifact back with. Both beat anything we could write here.
        first = next((line for line in text.splitlines() if line.strip()), "")
        if first:
            return first
    return STAGE_MESSAGES[stage].format(label=label)


def _letter_facts(job_id: int, language: str) -> letter_fields.LetterFacts:
    """What the letter's date line and address block say, without asking a model.

    The employer's name is a column the candidate already validated when they
    swiped the card right, so it is copied rather than re-derived: "agents
    produce, Python persists — and joins". The date is the clock, which a model
    does not have. Everything else in that block has to fit a sentence, which is
    the agent's job — see `services/letter_fields.py`.
    """
    with session_scope() as session:
        job = session.get(JobPosting, job_id)
        return letter_fields.LetterFacts(
            language=normalise_language(language),
            company=(job.company if job else ""),
        )


def letter_plan(job_id: int, language: str) -> base_documents.Plan:
    """The base cover letter for one posting, with its record-blanks already answered.

    Built here rather than in `base_documents` because it is the one plan that
    needs a row: `POST …/generate` calls it too, to answer 409 before the stream
    opens on a letter that cannot be filled.
    """
    return base_documents.plan(
        base_documents.COVER_LETTER,
        language,
        known=letter_fields.resolver(_letter_facts(job_id, language)),
    )


def _record_known_fills(content: dict[str, Any], plan: base_documents.Plan) -> None:
    """Fold the blanks Python answered into the artifact's own list of fills.

    The artifact then holds **every** blank in the document, keyed to the slots
    stored beside it, which is what keeps the export a pure function of the
    artifact and the file: re-deriving the date at download time would produce a
    different string of a different length months later, and the stored spans
    would put it in the wrong place.

    A fill the model volunteered for one of these is dropped rather than kept:
    it was never asked for it, and two entries for one slot is a fill that
    depends on dictionary order.
    """
    if not plan.auto:
        return
    order = {slot.key: index for index, slot in enumerate(plan.slots)}
    entries = [
        entry
        for entry in (content.get("fills") or [])
        if isinstance(entry, dict) and str(entry.get("slot") or "") not in plan.auto
    ]
    entries.extend(
        {
            "slot": key,
            "text": text,
            "reason": "Taken from the posting's own record, not written by the agent.",
        }
        for key, text in plan.auto.items()
    )
    entries.sort(key=lambda entry: order.get(str(entry.get("slot") or ""), len(order)))
    content["fills"] = entries


async def applying_stream(
    application_id: int,
    job_id: int,
    language: str = DEFAULT_LANGUAGE,
    personalisation: str = "",
    cover_letter: bool = False,
    resume: bool = True,
) -> AsyncIterator[tuple[str, Any]]:
    """Produce the documents this run was asked for, each behind its own gate.

    Yields `(event_type, data)` pairs; see this module's docstring for why. When
    there are two tracks they run in parallel, so `phase` events carry a `track`
    and arrive interleaved.

    **Two booleans, three runs that make sense.** `resume` alone is the default
    package — every application form has a field for a CV. Both is the package
    with a covering letter, which the candidate asks for by ticking a box: the
    letter's lane is the expensive half of the run (a grounded search for the
    employer's address, a writer, a humanising pass and a Critic loop), and most
    forms have nowhere to attach one. `cover_letter` alone is the run behind
    *Add a cover letter* — the same application, later, once they have seen the
    posting's form and found somewhere to put one; re-writing the résumé that is
    already on the row would spend a second run to produce the same document.
    Both false is a `ValueError`: a stream that produces nothing is a bug, not a
    request, and the endpoint rejects it as a 400 before it gets here.

    Nothing is deleted by leaving a document out. One written by an earlier run
    stays on the application at the version it reached.

    `personalisation` is what the candidate typed into the same dialog — a
    contact on the team, an angle they want taken. It is stored on the
    application by the endpoint before the stream opens, so a regeneration
    months later still carries it; it is passed in here rather than re-read so
    one run cannot straddle two versions of it.
    """
    if not resume and not cover_letter:
        raise ValueError("An applying run needs at least one document to produce.")
    language = normalise_language(language)
    # Read once, here, and hand the same plans to the agents, their gates and
    # their Critics. Re-reading in each of them would let one run straddle two
    # versions of a document — the candidate can upload a new CV while a run is
    # in flight — and the fills would then land in slots that meant something
    # else when they were chosen.
    #
    # This dict is also the run's answer to "which documents is this?": the
    # lanes, the saved artifacts and the progress lines all come off it.
    plans = {}
    if resume:
        plans[ArtifactKind.RESUME] = base_documents.plan(base_documents.RESUME, language)
    if cover_letter:
        plans[ArtifactKind.COVER_LETTER] = letter_plan(job_id, language)
    sources = {
        kind: base_documents.get(plan.kind, language) for kind, plan in plans.items()
    }

    state: dict[str, Any] = {}
    run_id = 0
    invocation_id = ""
    stages: dict[str, str] = {}
    async for event_type, data in stream(
        build_applying_team(
            job_id,
            plans.get(ArtifactKind.RESUME),
            plans.get(ArtifactKind.COVER_LETTER),
            personalisation,
        ),
        kind=RunKind.APPLYING,
        session_id=_artifact_session(job_id),
        label=f"apply to job {job_id} in {language}",
        message=user_message(
            "Produce these documents for the job posting in your instructions: "
            + " and ".join(TRACK_LABELS[kind] for kind in plans)
            + "."
        ),
        payload={
            "job_id": job_id,
            "application_id": application_id,
            "language": language,
            "personalised": bool(personalisation.strip()),
            # On the trace, because "why is there no letter in this run" is
            # otherwise answered by counting the artifacts it saved.
            "documents": list(plans),
        },
    ):
        if event_type == "run":
            run_id = int(data.get("run_id") or 0)
            yield ("run", data)
        elif event_type == "event":
            step = _applying_stage(str(data.get("author") or ""), stages)
            if step is None:
                continue
            track, stage = step
            # An agent emits several events per turn; the page wants the turn.
            if stages.get(track) == stage:
                continue
            stages[track] = stage
            message = _stage_message(track, stage, str(data.get("text") or ""))
            yield ("phase", {"phase": stage, "track": track, "message": message})
        elif event_type == "error":
            yield ("error", data)
            return
        elif event_type == "state":
            state = data
        elif event_type == "done":
            invocation_id = str(data.get("invocation_id") or "")

    artifacts: dict[str, Any] = {}
    # Only the kinds this run was asked for: a plan is what proves a lane ran,
    # and reading the letter's state key on a résumé-only run would pick up
    # whatever the *previous* run left in the ADK session and save it again as a
    # new version of a letter nobody asked for.
    for kind, key in (
        (ArtifactKind.RESUME, RESUME_STATE_KEY),
        (ArtifactKind.COVER_LETTER, COVER_LETTER_STATE_KEY),
    ):
        if kind not in plans:
            continue
        content = _as_dict(state.get(key))
        if not content:
            logger.warning("Applying run produced no %s for job %s", kind, job_id)
            continue
        # The renderer picks its section headings off this, so it has to be what
        # the candidate asked for rather than whatever the model happened to set.
        content["language"] = language
        # The base document travels with the artifact. Not for the export —
        # that re-opens the real file, because the text is not the formatting —
        # but so the preview, the audit and the version history still read
        # months later when the candidate has replaced their CV. Without it,
        # "what did this run actually fill in" would be a list of fragments with
        # nothing to compare them against.
        plan = plans[kind]
        source = sources.get(kind)
        content["blocks"] = docx_template.blocks_payload(plan.blocks)
        content["slots"] = docx_template.slots_payload(plan.slots)
        content["base_document_id"] = source.id if source else None
        _record_known_fills(content, plan)
        if kind == ArtifactKind.COVER_LETTER:
            # The page the address was read on, followed to whatever it actually
            # points at. Grounding cites `vertexaisearch…/grounding-api-redirect`
            # links, which say nothing about the site behind them and expire —
            # and this one is stored precisely so the candidate can open it and
            # check an address before posting a letter to it.
            content["address_source"] = await grounding.resolve_url(
                str(content.get("address_source") or "")
            )
        revisions = int(state.get(f"_revisions_{key}", 0) or 0)
        record = _save_artifact(
            application_id=application_id,
            kind=kind,
            content=content,
            # `run_id` is a foreign key: better a saved artifact with no trace
            # link than an insert that fails over one.
            run_id=run_id or None,
            invocation_id=invocation_id,
            revisions=revisions,
        )
        artifacts[kind] = record
        yield (
            "phase",
            {"phase": "saved", "track": kind, "message": _stage_message(kind, "saved", "")},
        )

    yield ("result", {"artifacts": artifacts, "run_id": run_id})


async def run_applying(
    application_id: int,
    job_id: int,
    language: str = DEFAULT_LANGUAGE,
    personalisation: str = "",
    cover_letter: bool = False,
    resume: bool = True,
) -> dict[str, Any]:
    """`applying_stream` run to completion, for callers that want the payload."""
    return await drain(
        applying_stream(
            application_id, job_id, language, personalisation, cover_letter, resume
        )
    )


def _save_artifact(
    *,
    application_id: int,
    kind: str,
    content: dict[str, Any],
    run_id: int | None,
    invocation_id: str,
    revisions: int,
) -> dict[str, Any]:
    with session_scope() as session:
        latest = session.exec(
            select(ApplicationArtifact)
            .where(
                ApplicationArtifact.application_id == application_id,
                ApplicationArtifact.kind == kind,
            )
            .order_by(ApplicationArtifact.version.desc())
        ).first()
        artifact = ApplicationArtifact(
            application_id=application_id,
            kind=kind,
            version=(latest.version + 1) if latest else 1,
            content=content,
            run_id=run_id,
            invocation_id=invocation_id,
            revisions=revisions,
        )
        session.add(artifact)
        session.flush()
        session.refresh(artifact)
        session.expunge(artifact)

    return {
        "id": artifact.id,
        "kind": artifact.kind,
        "version": artifact.version,
        "content": artifact.content,
        "revisions": artifact.revisions,
    }


def artifact_document_name(artifact_id: int) -> str:
    """The presentable filename for one artifact, without its extension.

    `Resume_Alex_Martin_Acme_Data_Science_Intern` — the candidate's name,
    the employer and the role, because that is what an ATS shows the screener
    and what makes the file findable again on both sides weeks later. Assembled
    here rather than in `services/render.py` because it needs three rows that
    only this layer has: the artifact, the application's posting, and the
    master profile.

    Falls back to the artifact's own `full_name` when the profile has none, and
    degrades part by part: a posting with no company still exports.
    """
    with session_scope() as session:
        artifact = session.get(ApplicationArtifact, artifact_id)
        if artifact is None:
            raise ValueError(f"No artifact {artifact_id}")
        kind = artifact.kind
        content = dict(artifact.content or {})
        application = session.get(Application, artifact.application_id)
        job = (
            session.get(JobPosting, application.job_posting_id)
            if application is not None
            else None
        )
        company = job.company if job else ""
        title = job.title if job else ""

    profile = profile_as_dict() or {}
    candidate = str(profile.get("full_name") or content.get("full_name") or "")
    return render.document_stem(
        kind,
        candidate=candidate,
        company=company,
        title=title,
        # The document's own language, not the app's: a French package should
        # arrive as `CV_…`, and `language` is stamped onto every artifact by the
        # flow that saved it.
        language=str(content.get("language") or DEFAULT_LANGUAGE),
    )


def _filled_docx(kind: str, content: dict[str, Any], *, stem: str) -> tuple[Path, str]:
    """The candidate's own .docx with this run's fills written into it.

    This is the whole deliverable — for the résumé and, since 2026-09-09, for
    the cover letter — and it is assembled here rather than in
    `services/render.py` because it needs a row that only this layer can reach:
    the `ProfileSource` holding the base document for the artifact's kind and
    language. Rendering the stored text would produce a *different* document —
    the point of the design is that it does not.

    The language decides which file, not `base_document_id`: if the candidate
    has replaced their French CV since this run, the current one is the document
    they want sent, and the stored block text is still there for the preview to
    show what the run was reasoning about. An artifact whose base document is
    gone cannot export, and says so.

    The blocks and slots come from the **stored artifact**, not from re-reading
    the current document. A run's fills are keyed to the blanks that existed
    when it ran, and re-deriving `s2` from a CV whose placeholders have since
    moved would put the coursework where the job title goes. If the document has
    changed under the artifact, `apply_lines` skips what no longer matches and
    says so in the log rather than writing into the wrong line.
    """
    language = normalise_language(content.get("language"))
    blocks = docx_template.blocks_from_payload(content.get("blocks"))
    slots = docx_template.slots_from_payload(content.get("slots"))
    data, report = docx_template.apply_lines(
        base_documents.read(kind, language),
        docx_template.filled_lines(blocks, slots, docx_template.fill_map(content)),
        title=str(content.get("document_title") or ""),
    )
    if report.skipped:
        # Not fatal: the gate already refused anything structural, so a skip
        # here means the base document changed under a stored artifact. The
        # document still exports, one line short of what the run intended.
        logger.warning(
            "Exporting artifact against a base document that no longer matches it: %s",
            report.skipped,
        )
    path = render.artifact_path(stem)
    path.write_bytes(data)
    return path, docx_template.DOCX_MIME


def export_artifact_file(artifact_id: int) -> tuple[str, str, str]:
    """Write an artifact to disk as .docx. Returns (path, mime_type, download filename).

    The two names differ on purpose. On disk the version is part of the stem, so
    exporting v3 cannot overwrite the file v2's `rendered_path` still points at.
    In the browser it is not, because the version number means nothing to the
    recruiter who receives the attachment.
    """
    with session_scope() as session:
        artifact = session.get(ApplicationArtifact, artifact_id)
        if artifact is None:
            raise ValueError(f"No artifact {artifact_id}")
        kind = artifact.kind
        content = dict(artifact.content or {})
        version = artifact.version

    stem = artifact_document_name(artifact_id)
    if render.is_filled(content):
        path, mime = _filled_docx(kind, content, stem=f"{stem}_v{version}")
    else:
        path, mime = render.export_artifact(kind, content, stem=f"{stem}_v{version}")

    with session_scope() as session:
        artifact = session.get(ApplicationArtifact, artifact_id)
        if artifact is not None:
            artifact.rendered_path = str(path)
            session.add(artifact)

    return str(path), mime, f"{stem}{path.suffix}"


# ---------------------------------------------------------------------------
# 6. Follow-up
# ---------------------------------------------------------------------------

# One track, so no `track` key on the phase events — but the same stage
# vocabulary as the Applying run, because the page renders them the same way.
FOLLOW_UP_STAGES = {
    "follow_up_agent": "writing",
    "follow_up_agent_critic": "reviewing",
    "follow_up_agent_gate": "gate",
}

FOLLOW_UP_MESSAGES = {
    "writing": "Writing the follow-up email…",
    "revising": "Revising the follow-up email on the Critic's notes…",
    "reviewing": "The Critic is reading the follow-up email…",
    "gate": "The Critic has ruled on the follow-up email.",
    "saved": "Saved the follow-up email.",
}


async def follow_up_stream(application_id: int) -> AsyncIterator[tuple[str, Any]]:
    """Draft the chase email for one application that has gone quiet.

    Streams for the same reason the Applying run does: the writer plus up to two
    Critic rounds is a handful of model calls, and a blocking response that says
    nothing for 100 seconds is cut off by the proxy even though the run finishes
    and saves its work here. It is also how the background sweep runs it —
    `run_follow_up` drains this — so there is one code path, not two.
    """
    context = follow_up.draft_context(application_id)

    state: dict[str, Any] = {}
    run_id = 0
    invocation_id = ""
    stage = ""
    async for event_type, data in stream(
        build_follow_up_writer(context.job_id, context.language, context.history),
        kind=RunKind.FOLLOW_UP,
        session_id=f"follow-up-{application_id}",
        label=f"follow up on application {application_id}",
        message=user_message(
            "Write the follow-up email for the application described in your instructions."
        ),
        payload={
            "application_id": application_id,
            "job_id": context.job_id,
            "language": context.language,
            "days_silent": context.days_silent,
        },
    ):
        if event_type == "run":
            run_id = int(data.get("run_id") or 0)
            yield ("run", data)
        elif event_type == "event":
            next_stage = FOLLOW_UP_STAGES.get(str(data.get("author") or ""))
            if next_stage is None:
                continue
            # The writer speaking after the Critic has is a revision, not a
            # first draft — which is what the gate just sent it back to do.
            if next_stage == "writing" and stage in {"reviewing", "gate"}:
                next_stage = "revising"
            # An agent emits several events per turn; the page wants the turn.
            if next_stage == stage:
                continue
            stage = next_stage
            message = FOLLOW_UP_MESSAGES[next_stage]
            if next_stage == "gate":
                # The gate says either "Audit follow_up: 8.4/10 … passed" or the
                # notes it is sending the draft back with. Both beat this.
                first = next(
                    (line for line in str(data.get("text") or "").splitlines() if line.strip()),
                    "",
                )
                message = first or message
            yield ("phase", {"phase": next_stage, "message": message})
        elif event_type == "error":
            yield ("error", data)
            return
        elif event_type == "state":
            state = data
        elif event_type == "done":
            invocation_id = str(data.get("invocation_id") or "")

    email = _as_dict(state.get(FOLLOW_UP_STATE_KEY))
    if not email:
        logger.warning("Follow-up run produced no email for application %s", application_id)
        yield ("error", {"run_id": run_id, "error": "The agent produced no email. Try again."})
        return

    # Which language this is written in is a fact about the request, not
    # something to take the model's word for — the same reason the three
    # Applying artifacts are stamped rather than asked.
    email["language"] = context.language
    record = _save_artifact(
        application_id=application_id,
        kind=ArtifactKind.FOLLOW_UP,
        content=email,
        run_id=run_id or None,
        invocation_id=invocation_id,
        revisions=int(state.get(f"_revisions_{FOLLOW_UP_STATE_KEY}", 0) or 0),
    )
    yield ("phase", {"phase": "saved", "message": FOLLOW_UP_MESSAGES["saved"]})
    yield ("result", {"artifact": record, "run_id": run_id})


async def run_follow_up(application_id: int) -> dict[str, Any]:
    """`follow_up_stream` run to completion — how the background sweep calls it."""
    return await drain(follow_up_stream(application_id))


# ---------------------------------------------------------------------------
# 7. Interview prep
# ---------------------------------------------------------------------------

# One track, like the follow-up, so no `track` key on the phase events — but a
# research stage in front of it that no other writing run has, and that is where
# most of the wall-clock goes.
INTERVIEW_PREP_STAGES = {
    "interview_researcher": "researching",
    "interview_coach": "writing",
    "interview_coach_critic": "reviewing",
    "interview_coach_gate": "gate",
}

INTERVIEW_PREP_MESSAGES = {
    "researching": "Researching the employer, the role and how they interview…",
    "writing": "Writing the interview brief…",
    "revising": "Revising the brief on the Critic's notes…",
    "reviewing": "The Critic is reading the brief…",
    "gate": "The Critic has ruled on the brief.",
    "sources": "Resolving the citations into links you can check…",
    "saved": "Saved the interview brief.",
}


def interview_history(application_id: int) -> str:
    """This application's own record, for the coach and its Critic.

    The interview brief has to know where the application actually got to — when
    it went in, what the candidate wrote about the call that was booked, whether
    a recruiter has already spoken to them. All of that is in the timeline and
    nowhere else, and a brief that ignores it prepares for a first conversation
    that already happened.
    """
    with session_scope() as session:
        application = session.get(Application, application_id)
        if application is None:
            return ""
        events = session.exec(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == application_id)
            .order_by(ApplicationEvent.created_at)
        ).all()
        record = {
            "status": application.status,
            "applied_on": application.applied_at.date().isoformat()
            if application.applied_at
            else "",
            "candidate_notes": application.notes,
            "next_action": application.next_action,
            "timeline": [
                {
                    "at": event.created_at.date().isoformat(),
                    "from": event.from_status,
                    "to": event.to_status,
                    "note": event.note,
                }
                for event in events
            ],
        }

    return f"""Today is {utcnow().date().isoformat()}. Everything below is the record — if a
conversation, a promise or a name is not in it, it did not happen and you may
not refer to it.

```json
{json.dumps(record, indent=2, ensure_ascii=False, default=str)}
```"""


async def interview_prep_stream(application_id: int) -> AsyncIterator[tuple[str, Any]]:
    """Research the employer, then write the interview brief behind the gate.

    Runs when an application first reaches an interview round. Streams for the same reason
    every other long run does — grounded research plus a writer plus up to two
    Critic rounds is minutes of work, and a proxied request that says nothing
    for 100 seconds is killed while the run carries on here.
    """
    with session_scope() as session:
        application = session.get(Application, application_id)
        if application is None:
            raise ValueError(f"No application {application_id}")
        job_id = application.job_posting_id
        language = normalise_language(application.language)
        personalisation = application.personalisation or ""

    history = interview_history(application_id)

    state: dict[str, Any] = {}
    run_id = 0
    invocation_id = ""
    stage = ""
    async for event_type, data in stream(
        build_interview_prep(job_id, application_id, language, personalisation, history),
        kind=RunKind.INTERVIEW_PREP,
        session_id=f"interview-prep-{application_id}",
        label=f"prepare the interview for application {application_id}",
        message=user_message(
            "Research this employer and write the interview brief for the posting in your "
            "instructions."
        ),
        payload={
            "application_id": application_id,
            "job_id": job_id,
            "language": language,
        },
    ):
        if event_type == "run":
            run_id = int(data.get("run_id") or 0)
            yield ("run", data)
        elif event_type == "event":
            next_stage = INTERVIEW_PREP_STAGES.get(str(data.get("author") or ""))
            if next_stage is None:
                continue
            # The coach speaking after the Critic has is a revision, not a first
            # draft — which is what the gate just sent it back to do.
            if next_stage == "writing" and stage in {"reviewing", "gate"}:
                next_stage = "revising"
            # An agent emits several events per turn; the page wants the turn.
            if next_stage == stage:
                continue
            stage = next_stage
            message = INTERVIEW_PREP_MESSAGES[next_stage]
            if next_stage == "gate":
                first = next(
                    (line for line in str(data.get("text") or "").splitlines() if line.strip()),
                    "",
                )
                message = first or message
            yield ("phase", {"phase": next_stage, "message": message})
        elif event_type == "error":
            yield ("error", data)
            return
        elif event_type == "state":
            state = data
        elif event_type == "done":
            invocation_id = str(data.get("invocation_id") or "")

    prep = _as_dict(state.get(INTERVIEW_PREP_STATE_KEY))
    if not prep:
        logger.warning("Interview prep run produced no brief for application %s", application_id)
        yield ("error", {"run_id": run_id, "error": "The agent produced no brief. Try again."})
        return

    # Grounded search cites opaque redirect URLs that expire; the whole point of
    # requiring a source is that the candidate can open it before repeating what
    # it says. Same treatment as the playbook's citations.
    yield ("phase", {"phase": "sources", "message": INTERVIEW_PREP_MESSAGES["sources"]})
    prep["sources"] = await grounding.resolve_sources(prep.get("sources") or [])

    # Stamped rather than asked, for the same reason the package's artifacts
    # are: which language this was written in is a fact about the request.
    prep["language"] = language
    record = _save_artifact(
        application_id=application_id,
        kind=ArtifactKind.INTERVIEW_PREP,
        content=prep,
        run_id=run_id or None,
        invocation_id=invocation_id,
        revisions=int(state.get(f"_revisions_{INTERVIEW_PREP_STATE_KEY}", 0) or 0),
    )
    yield ("phase", {"phase": "saved", "message": INTERVIEW_PREP_MESSAGES["saved"]})
    yield ("result", {"artifact": record, "run_id": run_id})


async def run_interview_prep(application_id: int) -> dict[str, Any]:
    """`interview_prep_stream` run to completion, for callers that want the payload."""
    return await drain(interview_prep_stream(application_id))


# ---------------------------------------------------------------------------
# 8. Contacts
# ---------------------------------------------------------------------------

# One track, like the interview brief, and the same shape: grounded research in
# front of a writer, then a pass in Python that the page waits on — here the
# links are proved rather than the citations resolved.
CONTACTS_STAGES = {
    "contact_scout": "researching",
    "contact_strategist": "writing",
    "contact_strategist_critic": "reviewing",
    "contact_strategist_gate": "gate",
}

CONTACTS_MESSAGES = {
    "researching": "Looking for the people who could move this application…",
    "writing": "Choosing who is worth writing to, and what to say…",
    "revising": "Revising the shortlist on the Critic's notes…",
    "reviewing": "The Critic is reading the shortlist…",
    "gate": "The Critic has ruled on the shortlist.",
    "links": "Opening every link, so none of them wastes your time…",
    "saved": "Saved the people to contact.",
}


async def contacts_stream(application_id: int) -> AsyncIterator[tuple[str, Any]]:
    """Find who to contact about one posting, and prove every link before saving.

    Started by hand from the application page. Streams for the same reason
    the interview brief does — grounded research plus a writer plus up to two
    Critic rounds outlasts the proxy's 100-second patience several times over —
    and has one stage the brief does not: `links`, where every profile URL the
    scout produced is fetched and dropped unless the page turns out to be that
    person. See `services/outreach.py`.
    """
    with session_scope() as session:
        application = session.get(Application, application_id)
        if application is None:
            raise ValueError(f"No application {application_id}")
        job_id = application.job_posting_id
        language = normalise_language(application.language)
        personalisation = application.personalisation or ""
        job = session.get(JobPosting, job_id)
        company = job.company if job else ""
        title = job.title if job else ""
        keywords = [str(keyword) for keyword in (job.keywords or [])] if job else []

    state: dict[str, Any] = {}
    run_id = 0
    invocation_id = ""
    stage = ""
    failure = ""
    async for event_type, data in stream(
        build_contacts(job_id, language, personalisation),
        kind=RunKind.CONTACTS,
        session_id=f"contacts-{application_id}",
        label=f"find contacts for application {application_id}",
        message=user_message(
            "Find the people worth contacting about the posting in your instructions."
        ),
        payload={
            "application_id": application_id,
            "job_id": job_id,
            "language": language,
        },
    ):
        if event_type == "run":
            run_id = int(data.get("run_id") or 0)
            yield ("run", data)
        elif event_type == "event":
            next_stage = CONTACTS_STAGES.get(str(data.get("author") or ""))
            if next_stage is None:
                continue
            # The strategist speaking after the Critic has is a revision, not a
            # first draft — which is what the gate just sent it back to do.
            if next_stage == "writing" and stage in {"reviewing", "gate"}:
                next_stage = "revising"
            # An agent emits several events per turn; the page wants the turn.
            if next_stage == stage:
                continue
            stage = next_stage
            message = CONTACTS_MESSAGES[next_stage]
            if next_stage == "gate":
                first = next(
                    (line for line in str(data.get("text") or "").splitlines() if line.strip()),
                    "",
                )
                message = first or message
            yield ("phase", {"phase": next_stage, "message": message})
        elif event_type == "error":
            # Not fatal here, and that is the whole point — see below.
            failure = str((data or {}).get("error") or "The run failed.")
            break
        elif event_type == "state":
            state = data
        elif event_type == "done":
            invocation_id = str(data.get("invocation_id") or "")

    # **A failed writer does not lose the run.** Everything the candidate most
    # needs — the six searches — is built from the posting and their own profile,
    # so it survives an agent that produced nothing at all. This is not a
    # hypothetical: on 2026-08-29 a real run answered `"language": "fr` and then
    # enumerated locale tags until it hit the output ceiling, and the whole
    # grounded search went in the bin with the unclosed JSON. The schema no
    # longer has the field that derailed (`agents/schemas.py::ContactPlan`), but
    # a model can derail in any free-text field, and throwing away work that
    # already succeeded is a choice rather than a consequence.
    #
    # It saves rather than erroring because the artifact is genuinely useful:
    # what it cannot do is pretend. `degraded` carries the reason, the note says
    # it in words, and the page shows both.
    plan = _as_dict(state.get(CONTACTS_STATE_KEY))
    degraded = ""
    if not plan:
        degraded = failure or "The agent produced no shortlist."
        logger.warning(
            "Contacts run produced no shortlist for application %s: %s",
            application_id,
            degraded,
        )

    # Where the promise is kept. Everything above is a request; this is the pass
    # that builds the searches in Python and throws away every discovered link
    # that could not be opened. A run whose research found nobody still saves —
    # the searches are the floor, and they are worth having on their own.
    yield ("phase", {"phase": "links", "message": CONTACTS_MESSAGES["links"]})
    content = await outreach.resolve(
        plan, company=company, title=title, keywords=keywords
    )
    if degraded:
        content["degraded"] = degraded
        content["notes"] = (
            "The research run did not finish, so nobody could be named — but the "
            "searches below are built from this posting and your own profile, and "
            "they work. Press “Look again” to retry the research."
        )
    # Stamped rather than asked, for the same reason every other artifact's is:
    # which language this was written in is a fact about the request — and, since
    # 2026-08-29, the reason `ContactPlan` has no field for it at all.
    content["language"] = language
    record = _save_artifact(
        application_id=application_id,
        kind=ArtifactKind.CONTACTS,
        content=content,
        run_id=run_id or None,
        invocation_id=invocation_id,
        revisions=int(state.get(f"_revisions_{CONTACTS_STATE_KEY}", 0) or 0),
    )
    yield ("phase", {"phase": "saved", "message": CONTACTS_MESSAGES["saved"]})
    yield ("result", {"artifact": record, "run_id": run_id})


async def run_contacts(application_id: int) -> dict[str, Any]:
    """`contacts_stream` run to completion, for callers that want the payload."""
    return await drain(contacts_stream(application_id))


# How long a written message may be before the app calls it too long. LinkedIn
# hard-stops a connection note at 300 characters; the prompt asks for 280 so
# there is room to be wrong, and this is where being wrong is measured rather
# than requested — the same division as every other promise here.
MESSAGE_LIMIT = 300


class PersonMoved(ValueError):
    """The person at that index is not the person the button was pressed beside.

    Only reachable when the shortlist was re-run in another tab between the page
    loading and the button being pressed. Worth its own exception because the
    alternative is writing a message about the wrong human being onto somebody
    else's card — which reads as a considered answer, the same failure
    `merge_scores` refuses for a score on the wrong posting.
    """


async def write_opening_line(
    application_id: int, index: int, name: str
) -> dict[str, Any]:
    """Write the first message to one person on the shortlist, on request.

    Not part of the contacts run, since 2026-09-03. The shortlist run answers
    *who is worth writing to*; this answers *what to say to this one*, and they
    are two decisions with two different moments. A shortlist of eight arrived
    with eight drafts, of which the candidate read one — so seven were output
    tokens, a slower run and a quality gate spent on text nobody opened.

    One fast-model call, no tools and no Critic: it is two sentences built from
    facts already in the prompt, the candidate is looking at the result, and
    *Write it again* costs one click. Short enough to answer a plain POST rather
    than a stream — see `documentation/streaming.md` for where that line is.

    The message is written back into the **latest** `contacts` artifact, in
    place, at `people[index]["opening_line"]`. In place rather than as a new
    version because it is not a new shortlist: the same people, one of whom now
    has a message. A new version would make *Look again* — which really does
    re-research — indistinguishable from pressing *Write the message*.
    """
    with session_scope() as session:
        application = session.get(Application, application_id)
        if application is None:
            raise ValueError(f"No application {application_id}")
        job_id = application.job_posting_id
        language = normalise_language(application.language)
        personalisation = application.personalisation or ""

        artifact = session.exec(
            select(ApplicationArtifact)
            .where(
                ApplicationArtifact.application_id == application_id,
                ApplicationArtifact.kind == ArtifactKind.CONTACTS,
            )
            .order_by(ApplicationArtifact.version.desc())
        ).first()
        if artifact is None:
            raise ValueError(f"No shortlist for application {application_id} to write from")
        artifact_id = int(artifact.id or 0)
        content = dict(artifact.content or {})

    people = [dict(person) for person in (content.get("people") or []) if isinstance(person, dict)]
    if not 0 <= index < len(people):
        raise PersonMoved("That person is no longer on this shortlist — reload the page.")
    person = people[index]
    # The name travels with the index for one reason: an index alone is a
    # position, and a shortlist re-run in another tab renumbers positions.
    if str(person.get("name") or "").casefold() != str(name or "").casefold():
        here = person.get("name") or "somebody else"
        raise PersonMoved(
            f"That position on this shortlist now holds {here}, not {name or 'them'}. "
            "Reload the page and press it again."
        )

    result = await execute(
        build_opener(
            job_id,
            person,
            language=language,
            personalisation=personalisation,
            approach=[str(item) for item in (content.get("approach") or [])],
        ),
        kind=RunKind.CONTACT_MESSAGE,
        session_id=f"contact-message-{application_id}-{index}",
        label=f"write to {person.get('name') or 'a contact'}",
        message=user_message(
            "Write the message to the person in your instructions, and nothing else."
        ),
        payload={
            "application_id": application_id,
            "artifact_id": artifact_id,
            "person": person.get("name") or "",
            "language": language,
        },
    )
    written = _as_dict(result.state.get(OPENING_STATE_KEY))
    message = " ".join(str(written.get("message") or "").split())
    if not message:
        raise RunFailed(
            "The writer came back with nothing. Press it again — and if it keeps happening, "
            "the message is two sentences you can write faster than this can explain itself."
        )

    person["opening_line"] = message
    # Measured, not asked for: the prompt requests 280 characters and the page
    # shows the count either way, so a model that ran long is visible rather
    # than silently over LinkedIn's limit.
    person["opening_line_over_limit"] = len(message) > MESSAGE_LIMIT
    people[index] = person
    content["people"] = people

    with session_scope() as session:
        stored = session.get(ApplicationArtifact, artifact_id)
        if stored is None:
            raise ValueError(f"No artifact {artifact_id}")
        stored.content = content
        session.add(stored)

    return {
        "opening_line": message,
        "over_limit": person["opening_line_over_limit"],
        "artifact_id": artifact_id,
        "index": index,
        "name": person.get("name") or "",
        "run_id": result.run_id,
    }


# ---------------------------------------------------------------------------
# 9. Ad-hoc re-audit
# ---------------------------------------------------------------------------


async def reaudit_artifact(artifact_id: int) -> dict[str, Any]:
    """Re-run the Critic over a stored artifact — useful after a manual edit."""
    with session_scope() as session:
        artifact = session.get(ApplicationArtifact, artifact_id)
        if artifact is None:
            raise ValueError(f"No artifact {artifact_id}")
        kind = artifact.kind
        content = dict(artifact.content or {})
        application_id = artifact.application_id

    with session_scope() as session:
        application = session.get(Application, application_id)
        job_id = application.job_posting_id if application else 0

    context = compose(profile_block(), job_block(job_id) if job_id else "")
    return await audit_artifact(
        subject_kind=kind,
        artifact=content,
        session_id=f"reaudit-{artifact_id}",
        context=context,
        subject_id=str(artifact_id),
    )
