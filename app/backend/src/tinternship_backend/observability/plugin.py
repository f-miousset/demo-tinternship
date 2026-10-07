"""AuditPlugin — the decision log.

Registered once on the ADK `App`, it implements every `BasePlugin` lifecycle
callback and writes an append-only `TraceEvent` row for each. That gives a
complete, queryable answer to "what did the agents actually do, and why?" —
including the prompt that went to the model, the response that came back, every
tool call with its arguments and result, token usage, latency and errors.

The plugin never modifies behaviour: every callback returns `None`.
It also never raises — a logging failure must not break a run.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from ..db.engine import session_scope
from ..db.models import AgentRun, TraceEvent
from .context import current_run
from .pricing import estimate_cost_usd

logger = logging.getLogger(__name__)

PREVIEW_LIMIT = 4000


def _truncate(text: str, limit: int = PREVIEW_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n… [truncated, {len(text) - limit} more chars]"


def content_to_text(content: types.Content | None) -> str:
    """Flatten a Content into something readable in the traces UI."""
    if content is None or not content.parts:
        return ""
    chunks: list[str] = []
    for part in content.parts:
        if getattr(part, "text", None):
            chunks.append(part.text or "")
        if getattr(part, "function_call", None):
            call = part.function_call
            chunks.append(f"[call {call.name}({_safe_json(dict(call.args or {}))})]")
        if getattr(part, "function_response", None):
            response = part.function_response
            chunks.append(f"[result {response.name} -> {_safe_json(response.response)}]")
        if getattr(part, "inline_data", None):
            blob = part.inline_data
            size = len(blob.data or b"")
            chunks.append(f"[inline {blob.mime_type}, {size} bytes]")
        if getattr(part, "file_data", None):
            chunks.append(f"[file {part.file_data.file_uri}]")
    return "\n".join(c for c in chunks if c)


def _safe_json(value: Any, limit: int = PREVIEW_LIMIT) -> str:
    try:
        return _truncate(json.dumps(value, default=str, ensure_ascii=False), limit)
    except (TypeError, ValueError):
        return _truncate(str(value), limit)


def _jsonable(value: Any) -> Any:
    """Coerce arbitrary tool args/results into something the JSON column accepts."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return json.loads(json.dumps(value, default=str))


def _hash(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8", errors="replace"))
    return digest.hexdigest()[:16]


class AuditPlugin(BasePlugin):
    """Writes a TraceEvent for every agent, model and tool lifecycle callback."""

    def __init__(self, name: str = "audit") -> None:
        super().__init__(name)
        self._agent_starts: dict[tuple[str, str], float] = {}
        self._model_starts: dict[tuple[str, str], float] = {}
        self._tool_starts: dict[tuple[str, str, str], float] = {}
        self._run_starts: dict[str, float] = {}

    # -- writing ----------------------------------------------------------

    def _record(
        self,
        *,
        phase: str,
        agent_name: str = "",
        model: str = "",
        tool_name: str = "",
        summary: str = "",
        input_preview: str = "",
        output_preview: str = "",
        payload: dict[str, Any] | None = None,
        prompt_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        latency_ms: int = 0,
        error: str = "",
        invocation_id: str = "",
        session_id: str = "",
        content_hash: str = "",
    ) -> None:
        ctx = current_run()
        if ctx and invocation_id and not ctx.invocation_id:
            ctx.invocation_id = invocation_id
        try:
            with session_scope() as session:
                session.add(
                    TraceEvent(
                        run_id=ctx.run_id if ctx else None,
                        invocation_id=invocation_id or (ctx.invocation_id if ctx else ""),
                        session_id=session_id or (ctx.session_id if ctx else ""),
                        seq=ctx.next_seq() if ctx else 0,
                        phase=phase,
                        agent_name=agent_name,
                        model=model,
                        tool_name=tool_name,
                        summary=_truncate(summary, 500),
                        input_preview=_truncate(input_preview),
                        output_preview=_truncate(output_preview),
                        payload=_jsonable(payload or {}),
                        prompt_tokens=prompt_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total_tokens,
                        latency_ms=latency_ms,
                        error=_truncate(error, 2000),
                        prompt_version_id=(
                            ctx.prompt_version_ids.get(agent_name) if ctx else None
                        ),
                        content_hash=content_hash,
                    )
                )
        except Exception:  # never let tracing break a run
            logger.exception("AuditPlugin failed to write a %s trace event", phase)

    def _bump_run_totals(
        self,
        *,
        prompt_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        cost_usd: float = 0.0,
        llm_calls: int = 0,
        tool_calls: int = 0,
    ) -> None:
        ctx = current_run()
        if ctx is None:
            return
        try:
            with session_scope() as session:
                run = session.get(AgentRun, ctx.run_id)
                if run is None:
                    return
                run.prompt_tokens += prompt_tokens
                run.output_tokens += output_tokens
                run.total_tokens += total_tokens
                run.cost_usd += cost_usd
                run.llm_calls += llm_calls
                run.tool_calls += tool_calls
                session.add(run)
        except Exception:
            logger.exception("AuditPlugin failed to update run totals")

    # -- run lifecycle ----------------------------------------------------

    async def before_run_callback(
        self, *, invocation_context: InvocationContext
    ) -> types.Content | None:
        self._run_starts[invocation_context.invocation_id] = time.perf_counter()
        ctx = current_run()
        if ctx is not None:
            ctx.invocation_id = invocation_context.invocation_id
            ctx.session_id = invocation_context.session.id
            try:
                with session_scope() as session:
                    run = session.get(AgentRun, ctx.run_id)
                    if run is not None:
                        run.invocation_id = invocation_context.invocation_id
                        run.session_id = invocation_context.session.id
                        session.add(run)
            except Exception:
                logger.exception("AuditPlugin failed to stamp run identifiers")

        root = invocation_context.agent
        self._record(
            phase="run_start",
            agent_name=getattr(root, "name", "") or "",
            summary=f"Run started on '{getattr(root, 'name', 'unknown')}'",
            input_preview=content_to_text(invocation_context.user_content),
            invocation_id=invocation_context.invocation_id,
            session_id=invocation_context.session.id,
        )
        return None

    async def after_run_callback(self, *, invocation_context: InvocationContext) -> None:
        started = self._run_starts.pop(invocation_context.invocation_id, None)
        latency = int((time.perf_counter() - started) * 1000) if started else 0
        self._record(
            phase="run_end",
            agent_name=getattr(invocation_context.agent, "name", "") or "",
            summary="Run finished",
            latency_ms=latency,
            invocation_id=invocation_context.invocation_id,
            session_id=invocation_context.session.id,
        )

    async def on_user_message_callback(
        self, *, invocation_context: InvocationContext, user_message: types.Content
    ) -> types.Content | None:
        self._record(
            phase="user_message",
            summary="User message received",
            input_preview=content_to_text(user_message),
            invocation_id=invocation_context.invocation_id,
            session_id=invocation_context.session.id,
        )
        return None

    async def on_event_callback(
        self, *, invocation_context: InvocationContext, event: Event
    ) -> Event | None:
        # Partial streaming chunks would flood the log; only record settled events.
        if getattr(event, "partial", False):
            return None
        text = content_to_text(event.content)
        actions = event.actions
        transfer = getattr(actions, "transfer_to_agent", None)
        escalate = getattr(actions, "escalate", None)
        state_delta = dict(getattr(actions, "state_delta", {}) or {})
        if not text and not transfer and not escalate and not state_delta:
            return None
        summary = f"Event from '{event.author}'"
        if transfer:
            summary += f" → transfer to '{transfer}'"
        if escalate:
            summary += " → escalate (loop exit)"
        self._record(
            phase="event",
            agent_name=event.author or "",
            summary=summary,
            output_preview=text,
            payload={
                "transfer_to_agent": transfer,
                "escalate": bool(escalate),
                "state_delta_keys": sorted(state_delta.keys()),
            },
            invocation_id=event.invocation_id or invocation_context.invocation_id,
            session_id=invocation_context.session.id,
            content_hash=_hash(event.author or "", text),
        )
        return None

    async def on_run_error_callback(
        self, *, invocation_context: InvocationContext, error: Exception
    ) -> None:
        self._record(
            phase="error",
            agent_name=getattr(invocation_context.agent, "name", "") or "",
            summary=f"Run failed: {type(error).__name__}",
            error=f"{type(error).__name__}: {error}",
            invocation_id=invocation_context.invocation_id,
            session_id=invocation_context.session.id,
        )

    # -- agent lifecycle --------------------------------------------------

    async def before_agent_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext
    ) -> types.Content | None:
        key = (callback_context.invocation_id, agent.name)
        self._agent_starts[key] = time.perf_counter()
        self._record(
            phase="agent_start",
            agent_name=agent.name,
            summary=f"{type(agent).__name__} '{agent.name}' started",
            payload={"agent_type": type(agent).__name__},
            invocation_id=callback_context.invocation_id,
            session_id=callback_context.session.id,
        )
        return None

    async def after_agent_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext
    ) -> types.Content | None:
        key = (callback_context.invocation_id, agent.name)
        started = self._agent_starts.pop(key, None)
        latency = int((time.perf_counter() - started) * 1000) if started else 0
        self._record(
            phase="agent_end",
            agent_name=agent.name,
            summary=f"{type(agent).__name__} '{agent.name}' finished",
            latency_ms=latency,
            invocation_id=callback_context.invocation_id,
            session_id=callback_context.session.id,
        )
        return None

    async def on_agent_error_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext, error: Exception
    ) -> None:
        self._agent_starts.pop((callback_context.invocation_id, agent.name), None)
        self._record(
            phase="error",
            agent_name=agent.name,
            summary=f"Agent '{agent.name}' raised {type(error).__name__}",
            error=f"{type(error).__name__}: {error}",
            invocation_id=callback_context.invocation_id,
            session_id=callback_context.session.id,
        )

    # -- model lifecycle --------------------------------------------------

    async def before_model_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> LlmResponse | None:
        key = (callback_context.invocation_id, callback_context.agent_name)
        self._model_starts[key] = time.perf_counter()

        config = llm_request.config
        system_instruction = ""
        if config is not None and config.system_instruction:
            instruction = config.system_instruction
            system_instruction = (
                instruction if isinstance(instruction, str) else content_to_text(instruction)
            )
        conversation = "\n\n".join(
            f"[{c.role}] {content_to_text(c)}" for c in (llm_request.contents or [])
        )
        tool_names = sorted(llm_request.tools_dict.keys()) if llm_request.tools_dict else []
        response_schema = None
        if config is not None and getattr(config, "response_schema", None) is not None:
            response_schema = getattr(config.response_schema, "__name__", str(type(config.response_schema)))

        self._record(
            phase="model_request",
            agent_name=callback_context.agent_name,
            model=llm_request.model or "",
            summary=f"→ {llm_request.model} ({len(llm_request.contents or [])} turns)",
            input_preview=(
                f"### SYSTEM INSTRUCTION\n{system_instruction}\n\n### CONVERSATION\n{conversation}"
                if system_instruction
                else conversation
            ),
            payload={
                "tools": tool_names,
                "turns": len(llm_request.contents or []),
                "response_schema": response_schema,
                "temperature": getattr(config, "temperature", None) if config else None,
            },
            invocation_id=callback_context.invocation_id,
            session_id=callback_context.session.id,
            content_hash=_hash(system_instruction, conversation),
        )
        return None

    async def after_model_callback(
        self, *, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> LlmResponse | None:
        # Streaming emits many partial responses; only the settled one is logged.
        if llm_response.partial:
            return None

        key = (callback_context.invocation_id, callback_context.agent_name)
        started = self._model_starts.pop(key, None)
        latency = int((time.perf_counter() - started) * 1000) if started else 0

        usage = llm_response.usage_metadata
        prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
        thoughts = int(getattr(usage, "thoughts_token_count", 0) or 0) if usage else 0
        total_tokens = int(getattr(usage, "total_token_count", 0) or 0) if usage else 0
        output_tokens += thoughts

        model = llm_response.model_version or ""
        cost = estimate_cost_usd(model, prompt_tokens, output_tokens)

        grounding = llm_response.grounding_metadata
        sources: list[str] = []
        if grounding is not None:
            for chunk in getattr(grounding, "grounding_chunks", None) or []:
                web = getattr(chunk, "web", None)
                if web is not None and getattr(web, "uri", None):
                    sources.append(web.uri)

        self._record(
            phase="model_response",
            agent_name=callback_context.agent_name,
            model=model,
            summary=(
                f"← {model or 'model'} "
                f"({prompt_tokens} in / {output_tokens} out, ${cost:.4f})"
            ),
            output_preview=content_to_text(llm_response.content),
            payload={
                "finish_reason": str(llm_response.finish_reason or ""),
                "error_code": llm_response.error_code,
                "error_message": llm_response.error_message,
                "grounding_sources": sources[:50],
                "cost_usd": round(cost, 6),
                "thoughts_tokens": thoughts,
            },
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency,
            error=llm_response.error_message or "",
            invocation_id=callback_context.invocation_id,
            session_id=callback_context.session.id,
        )
        self._bump_run_totals(
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
            llm_calls=1,
        )
        return None

    async def on_model_error_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
        error: Exception,
    ) -> LlmResponse | None:
        self._model_starts.pop((callback_context.invocation_id, callback_context.agent_name), None)
        self._record(
            phase="error",
            agent_name=callback_context.agent_name,
            model=llm_request.model or "",
            summary=f"Model call failed: {type(error).__name__}",
            error=f"{type(error).__name__}: {error}",
            invocation_id=callback_context.invocation_id,
            session_id=callback_context.session.id,
        )
        return None

    # -- tool lifecycle ---------------------------------------------------

    async def before_tool_callback(
        self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext
    ) -> dict[str, Any] | None:
        key = (tool_context.invocation_id, tool_context.agent_name, tool.name)
        self._tool_starts[key] = time.perf_counter()
        self._record(
            phase="tool_start",
            agent_name=tool_context.agent_name,
            tool_name=tool.name,
            summary=f"→ tool {tool.name}",
            input_preview=_safe_json(tool_args),
            payload={"args": _jsonable(tool_args)},
            invocation_id=tool_context.invocation_id,
            session_id=tool_context.session.id,
        )
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        key = (tool_context.invocation_id, tool_context.agent_name, tool.name)
        started = self._tool_starts.pop(key, None)
        latency = int((time.perf_counter() - started) * 1000) if started else 0
        self._record(
            phase="tool_end",
            agent_name=tool_context.agent_name,
            tool_name=tool.name,
            summary=f"← tool {tool.name} ({latency} ms)",
            input_preview=_safe_json(tool_args),
            output_preview=_safe_json(result),
            payload={"result": _jsonable(result)},
            latency_ms=latency,
            invocation_id=tool_context.invocation_id,
            session_id=tool_context.session.id,
        )
        self._bump_run_totals(tool_calls=1)
        return None

    async def on_tool_error_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        error: Exception,
    ) -> dict[str, Any] | None:
        self._tool_starts.pop((tool_context.invocation_id, tool_context.agent_name, tool.name), None)
        self._record(
            phase="error",
            agent_name=tool_context.agent_name,
            tool_name=tool.name,
            summary=f"Tool '{tool.name}' failed: {type(error).__name__}",
            input_preview=_safe_json(tool_args),
            error=f"{type(error).__name__}: {error}",
            invocation_id=tool_context.invocation_id,
            session_id=tool_context.session.id,
        )
        return None
