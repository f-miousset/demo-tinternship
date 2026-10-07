"""The HR Expert run, and CRUD over the editable versioned prompts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db.models import PromptKind
from ..services import audit, flows, prompt_store
from .sse import sse_response

router = APIRouter(prefix="/api/strategy", tags=["strategy"])

# The Critic files a verdict under the *rubric's* subject kind, which is not the
# prompt kind: the search brief is audited as "brief" (rubric `search_brief_v1`).
AUDIT_KIND = {PromptKind.SEARCH_BRIEF: "brief", PromptKind.PLAYBOOK: "playbook"}


def _verdicts() -> dict[tuple[str, str], dict[str, Any]]:
    return audit.latest_verdicts(AUDIT_KIND.values())


def _serialise(prompt: Any, verdicts: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    """One prompt, with the score it was given when it was written.

    The audit travels with the prompt rather than only with the run that
    produced it, so the brief and the playbook show what they scored whenever
    you look at them — not just in the minute after a run.
    """
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
        "audit": verdicts.get((AUDIT_KIND.get(prompt.kind, prompt.kind), str(prompt.id))),
    }


@router.post("/hr-expert")
def run_hr_expert():
    """Stream the research and the playbook it produces.

    Server-sent events for the same reason as the other two long runs: grounded
    research plus an audit pass outlives the 100 seconds a proxy will wait on a
    silent response. A run that produces no playbook says so as an `error`
    event — by the time we know, the 200 has already been sent.
    """
    return sse_response(flows.hr_expert_stream())


@router.get("/prompts")
def list_prompts(kind: str | None = None):
    verdicts = _verdicts()
    return {"prompts": [_serialise(p, verdicts) for p in prompt_store.list_versions(kind)]}


@router.get("/prompts/active")
def active_prompts():
    verdicts = _verdicts()
    return {
        kind: (_serialise(prompt, verdicts) if (prompt := prompt_store.get_active(kind)) else None)
        for kind in (PromptKind.SEARCH_BRIEF, PromptKind.PLAYBOOK)
    }


class PromptEdit(BaseModel):
    content: str
    structured: dict[str, Any] | None = None
    title: str = ""
    note: str = ""


@router.put("/prompts/{kind}")
def edit_prompt(kind: str, body: PromptEdit):
    """Save an edited prompt as a new active version. The old one is kept."""
    if kind not in {PromptKind.SEARCH_BRIEF, PromptKind.PLAYBOOK}:
        raise HTTPException(status_code=400, detail=f"Unknown prompt kind {kind!r}")
    previous = prompt_store.get_active(kind)
    fallback_structured = previous.structured if previous else {}
    prompt = prompt_store.save_prompt(
        kind,
        content=body.content,
        structured=body.structured if body.structured is not None else fallback_structured,
        title=body.title or (previous.title if previous else ""),
        author="user",
        note=body.note or "Edited by hand.",
    )
    return _serialise(prompt, _verdicts())


@router.post("/prompts/{prompt_id}/activate")
def activate_prompt(prompt_id: int):
    """Roll back to an earlier version."""
    prompt = prompt_store.activate(prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"No prompt {prompt_id}")
    return _serialise(prompt, _verdicts())
