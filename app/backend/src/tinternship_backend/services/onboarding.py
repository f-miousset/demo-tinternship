"""Whether the one-time account setup is finished.

Base documents, profile, course and skill lists, search brief and hiring
playbook are configured once, together, on the Account page — everything
numbered downstream assumes they all exist. This is the single definition of
"done": `/api/config` reports it so the UI can hold a half-configured account on
the Account page, and `/api/account` reports it next to who is signed in.
"""

from __future__ import annotations

from ..agents.runtime import get_session
from ..db.models import PromptKind
from ..observability.plugin import content_to_text
from . import base_documents, prompt_store
from .flows import INTERVIEW_SESSION
from .profile_store import has_lists, has_profile

# The six things nothing downstream can run without. `has_base_resumes` joined
# them on 2026-08-28: an applying run does not generate a résumé any more, it
# fills the blanks in the candidate's own document, so a run in a language with
# no uploaded .docx has literally nothing to produce. `has_lists` joined on
# 2026-08-29 for the same kind of reason one step further in — the coursework
# and skills blanks are filled by *selecting* from lists the candidate wrote,
# and with no lists the agent's only options are to leave the blank or invent.
# `has_base_letters` joined on 2026-09-09, when the cover letter stopped being
# written from scratch: an applying run produces two documents and neither of
# them exists without the candidate's file.
# The interview is a further step on the page but not one of these: see
# `setup_state`.
REQUIRED = (
    "has_base_resumes",
    "has_base_letters",
    "has_profile",
    "has_lists",
    "has_brief",
    "has_playbook",
)


async def _has_interview() -> bool:
    """Whether the Interrogator has actually answered the candidate once.

    The Account page numbers the interview as its own step, so it needs its own
    signal — and it has to come from the session, not from the brief, or the
    step would tick before anyone had said anything.
    """
    session = await get_session(INTERVIEW_SESSION)
    if session is None:
        return False
    return any(
        event.author != "user"
        and not getattr(event, "partial", False)
        and content_to_text(event.content)
        for event in session.events
    )


async def setup_state() -> dict[str, bool]:
    """The steps of the Account page, plus whether setup is done.

    `complete` deliberately ignores `has_interview`: it gates the whole app, and
    starting the interview over — which deletes the session — must not lock
    someone out of Jobs over a brief and a playbook that still exist.
    """
    state = {
        "has_base_resumes": base_documents.complete(base_documents.RESUME),
        "has_base_letters": base_documents.complete(base_documents.COVER_LETTER),
        "has_profile": has_profile(),
        "has_lists": has_lists(),
        "has_interview": await _has_interview(),
        "has_brief": prompt_store.get_active(PromptKind.SEARCH_BRIEF) is not None,
        "has_playbook": prompt_store.get_active(PromptKind.PLAYBOOK) is not None,
    }
    return {**state, "complete": all(state[flag] for flag in REQUIRED)}
