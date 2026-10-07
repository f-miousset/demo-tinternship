"""Settings: what is configured, what is stored, and how to change or delete it."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import reset as reset_service
from ..services import runtime_config

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Deleting is irreversible and there is no undo, so the client has to say so
# explicitly rather than a stray POST wiping everything.
CONFIRM_PHRASE = "DELETE"


@router.get("/config")
def editable_config():
    """The settings the UI may change, with their `.env` defaults and bounds."""
    return runtime_config.state()


class ConfigUpdate(BaseModel):
    """Every field is optional: the form sends what it has, omissions stay put.

    **One field per knob in `runtime_config.KNOBS`.** Pydantic drops undeclared
    fields silently, so a knob missing here never reaches `save()`: the form
    posts it, the API answers 200, and the value snaps back on the next render.
    `model_grounded` and `posting_half_life_days` were missing for exactly that
    reason and could only be set from `.env`. `test_runtime_config.py` now PUTs
    every knob in `KNOBS` and checks each one landed, so the next knob added
    without a field here fails a test instead of half-working.
    """

    model_primary: str | None = None
    model_fast: str | None = None
    model_grounded: str | None = None
    audit_pass_threshold: float | None = None
    audit_max_revisions: int | None = None
    follow_up_after_days: int | None = None
    posting_half_life_days: float | None = None


@router.put("/config")
def update_config(body: ConfigUpdate):
    try:
        runtime_config.save(body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return runtime_config.state()


@router.delete("/config")
def reset_config():
    """Back to whatever `.env` says."""
    runtime_config.clear()
    return runtime_config.state()


@router.get("/data")
def stored_data():
    return {
        "summary": reset_service.summary(),
        "scopes": [
            {"key": scope.key, "label": scope.label, "description": scope.description}
            for scope in reset_service.SCOPES
        ],
        "confirm_phrase": CONFIRM_PHRASE,
    }


class ResetRequest(BaseModel):
    scopes: list[str] = Field(default_factory=list)
    confirm: str = ""


@router.post("/reset")
async def reset(body: ResetRequest):
    if body.confirm != CONFIRM_PHRASE:
        raise HTTPException(
            status_code=400,
            detail=f"This cannot be undone. Type {CONFIRM_PHRASE} to confirm.",
        )
    try:
        deleted = await reset_service.reset(set(body.scopes))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "deleted": deleted, "summary": reset_service.summary()}
