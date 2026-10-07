"""Turning agents into runnable ADK apps.

Every flow gets its own `App`, but they all share one `AuditPlugin` instance and
one session service, so the decision log is continuous across flows and chat
history survives a server restart.

`execute()` is the single entry point the API layer uses: it opens an
`AgentRun`, streams the invocation, and returns the final session state plus the
events that were produced.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from google.adk.agents.base_agent import BaseAgent
from google.adk.apps.app import App
from google.adk.events.event import Event
from google.adk.runners import Runner
from google.adk.sessions.base_session_service import BaseSessionService
from google.adk.sessions.session import Session
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.genai import types
from pydantic import BaseModel

from ..config import get_settings
from ..db.models import RunStatus
from ..observability.context import RunContext, run_context
from ..observability.plugin import AuditPlugin, content_to_text
from ..observability.runs import create_run, finish_run

logger = logging.getLogger(__name__)

APP_NAME = "tinternship"
DEFAULT_USER_ID = "local"


def _build_deferred_genai_models() -> int:
    """Force pydantic to build every `google.genai` model, and say how many.

    `google.genai` sets `defer_build=True` on its base model: a type's validator
    and serializer are built on first use rather than at import, which is most of
    what importing `google.genai.types` — several hundred models — would
    otherwise cost. A model that only ever appears as a *nested field* of a
    validated response never touches its own class-level serializer, because the
    parent's schema does that work, so the class keeps pydantic's placeholder
    `MockValSer` forever.

    That placeholder is a live grenade in ADK session state. `AgentTool` writes
    the sub-agent's `types.GroundingMetadata` — nested inside the response it
    came from, so never built — to `temp:_adk_grounding_metadata`, and the Scout
    is handed an `AgentTool` whenever `search_job_board` is configured beside
    `google_search`: Gemini forbids a built-in tool alongside function tools, so
    ADK wraps the search in a sub-agent. `EventActions.state_delta` is typed
    `dict[str, Any]`, so pydantic-core serialises its values by inference — it
    reaches for the value's class serializer, finds the placeholder, and raises
    `TypeError: 'MockValSer' object is not an instance of 'SchemaSerializer'`.
    ADK's sanitising fallback goes through `to_jsonable_python`, which walks into
    the same placeholder, so the exception escapes and the whole run dies.

    That is what killed investigator run 81 on 2026-09-06, on the one turn where
    the Scout called `google_search` and `search_job_board` in parallel and ADK
    merged the two function-response events with `actions.model_dump()`. It is
    non-deterministic — it needs parallel calls in the same turn — which is why
    it read as a random failure rather than a broken pipeline.

    Building all of them costs ~0.1 s, once, at import. Rebuilding only the type
    ADK stashes today would be free, and would break again the next time ADK
    stashes a different one.
    """
    built = 0
    for value in vars(types).values():
        if not isinstance(value, type) or not issubclass(value, BaseModel):
            continue
        try:
            # `model_rebuild()` answers True only when it actually built
            # something, and is a no-op on a model pydantic already completed.
            if value.model_rebuild() is True:
                built += 1
        except Exception:  # pragma: no cover - hardening must not break startup
            logger.exception("Could not build the pydantic serializer for %s", value)
    return built


_built_genai_models = _build_deferred_genai_models()
logger.debug("Built %s deferred google.genai model serializers", _built_genai_models)

_session_service: BaseSessionService | None = None
_audit_plugin: AuditPlugin | None = None


def get_session_service() -> BaseSessionService:
    global _session_service
    if _session_service is None:
        settings = get_settings()
        _session_service = SqliteSessionService(db_path=str(settings.sessions_db_path))
    return _session_service


def get_audit_plugin() -> AuditPlugin:
    global _audit_plugin
    if _audit_plugin is None:
        _audit_plugin = AuditPlugin()
    return _audit_plugin


def build_runner(agent: BaseAgent, *, app_name: str = APP_NAME) -> Runner:
    app = App(name=app_name, root_agent=agent, plugins=[get_audit_plugin()])
    return Runner(app=app, session_service=get_session_service())


async def ensure_session(session_id: str, *, user_id: str = DEFAULT_USER_ID) -> Session:
    service = get_session_service()
    session = await service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    if session is None:
        session = await service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
    return session


async def get_session(session_id: str, *, user_id: str = DEFAULT_USER_ID) -> Session | None:
    return await get_session_service().get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )


def user_message(text: str, parts: list[types.Part] | None = None) -> types.Content:
    all_parts: list[types.Part] = list(parts or [])
    if text:
        all_parts.append(types.Part(text=text))
    return types.Content(role="user", parts=all_parts)


@dataclass
class RunResult:
    run_id: int
    session_id: str
    invocation_id: str
    state: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    events: list[Event] = field(default_factory=list)


async def stream(
    agent: BaseAgent,
    *,
    kind: str,
    session_id: str,
    message: types.Content,
    label: str = "",
    payload: dict[str, Any] | None = None,
    user_id: str = DEFAULT_USER_ID,
) -> AsyncGenerator[tuple[str, Any], None]:
    """Run an agent, yielding `(event_type, data)` pairs for SSE.

    Event types: `run` (run metadata), `event` (an ADK event), `state` (final
    session state), `error`, `done`.
    """
    await ensure_session(session_id, user_id=user_id)
    runner = build_runner(agent)
    run_id = create_run(kind, label or agent.name, payload)
    ctx = RunContext(run_id=run_id, kind=kind, label=label, session_id=session_id)

    yield ("run", {"run_id": run_id, "session_id": session_id, "kind": kind})

    final_text_parts: list[str] = []
    try:
        with run_context(ctx):
            async for event in runner.run_async(
                user_id=user_id, session_id=session_id, new_message=message
            ):
                text = content_to_text(event.content)
                if text and not getattr(event, "partial", False):
                    final_text_parts.append(text)
                yield (
                    "event",
                    {
                        "author": event.author,
                        "text": text,
                        "partial": bool(getattr(event, "partial", False)),
                        "invocation_id": event.invocation_id,
                        "is_final": event.is_final_response()
                        if hasattr(event, "is_final_response")
                        else False,
                    },
                )
    except Exception as exc:
        # The full exception goes to the trace; the client gets the actionable version.
        from ..api.errors import humanise

        logger.exception("Run %s (%s) failed", run_id, kind)
        finish_run(run_id, status=RunStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
        yield ("error", {"run_id": run_id, "error": humanise(exc)[1]})
        return

    session = await get_session(session_id, user_id=user_id)
    state = dict(session.state) if session else {}
    finish_run(run_id, status=RunStatus.SUCCEEDED, output={"keys": sorted(state.keys())})

    yield ("state", state)
    yield (
        "done",
        {"run_id": run_id, "text": "\n".join(final_text_parts), "invocation_id": ctx.invocation_id},
    )


async def execute(
    agent: BaseAgent,
    *,
    kind: str,
    session_id: str,
    message: types.Content,
    label: str = "",
    payload: dict[str, Any] | None = None,
    user_id: str = DEFAULT_USER_ID,
) -> RunResult:
    """Run an agent to completion and return its final state."""
    await ensure_session(session_id, user_id=user_id)
    runner = build_runner(agent)
    run_id = create_run(kind, label or agent.name, payload)
    ctx = RunContext(run_id=run_id, kind=kind, label=label, session_id=session_id)

    events: list[Event] = []
    texts: list[str] = []
    try:
        with run_context(ctx):
            async for event in runner.run_async(
                user_id=user_id, session_id=session_id, new_message=message
            ):
                if getattr(event, "partial", False):
                    continue
                events.append(event)
                text = content_to_text(event.content)
                if text:
                    texts.append(text)
    except Exception as exc:
        finish_run(run_id, status=RunStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
        raise

    session = await get_session(session_id, user_id=user_id)
    state = dict(session.state) if session else {}
    finish_run(run_id, status=RunStatus.SUCCEEDED, output={"keys": sorted(state.keys())})

    return RunResult(
        run_id=run_id,
        session_id=session_id,
        invocation_id=ctx.invocation_id,
        state=state,
        text="\n".join(texts),
        events=events,
    )
