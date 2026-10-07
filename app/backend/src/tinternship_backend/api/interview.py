"""Interrogator endpoints: the interview chat and the brief it produces."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agents.interrogator import split_completion
from ..agents.runtime import APP_NAME, DEFAULT_USER_ID, get_session, get_session_service
from ..observability.plugin import content_to_text
from ..services import flows
from .sse import sse_response

router = APIRouter(prefix="/api/interview", tags=["interview"])

# Whose turns count as conversation. `finalise` deliberately runs the brief writer
# inside the interview session so it can read the transcript, which leaves two
# machine-only turns behind: the synthetic "produce the brief" prompt and the raw
# SearchBrief JSON. Both belong to the trace, not to the chat the user sees.
CHAT_AUTHORS = {"user", "interrogator"}


class MessageIn(BaseModel):
    message: str
    session_id: str = flows.INTERVIEW_SESSION


@router.post("/message")
async def send_message(body: MessageIn):
    """Stream the Interrogator's reply as SSE."""
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    return sse_response(flows.interview_stream(body.message, body.session_id))


@router.get("/history")
async def history(session_id: str = flows.INTERVIEW_SESSION):
    session = await get_session(session_id)
    if session is None:
        return {"session_id": session_id, "messages": []}

    # Drop the whole invocation an off-chat agent took part in, so its prompt
    # disappears along with its answer rather than leaving a dangling user turn.
    machine_invocations = {
        event.invocation_id
        for event in session.events
        if event.author not in CHAT_AUTHORS and event.invocation_id
    }

    messages = []
    for event in session.events:
        if getattr(event, "partial", False):
            continue
        if event.invocation_id in machine_invocations:
            continue
        # The stored turn still carries the marker the Interrogator ended the
        # interview with; the candidate never saw it live and must not see it on
        # a reload either.
        text, _ = split_completion(content_to_text(event.content))
        if not text:
            continue
        role = "user" if event.author == "user" else "assistant"
        messages.append({"role": role, "author": event.author, "text": text})
    return {"session_id": session_id, "messages": messages}


@router.post("/finalise")
async def finalise(session_id: str = flows.INTERVIEW_SESSION):
    """Turn the transcript into the editable, versioned search brief."""
    try:
        return await flows.finalise_brief(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/reset")
async def reset(session_id: str = flows.INTERVIEW_SESSION):
    """Start the interview over. Prompts and jobs already saved are untouched."""
    service = get_session_service()
    session = await get_session(session_id)
    if session is not None:
        await service.delete_session(
            app_name=APP_NAME, user_id=DEFAULT_USER_ID, session_id=session_id
        )
    return {"status": "ok", "session_id": session_id}
