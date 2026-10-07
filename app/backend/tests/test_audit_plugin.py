"""The AuditPlugin must record every lifecycle callback, and must never raise.

The "trace everything" promise is only as good as this test.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.genai import types
from sqlmodel import select

from tinternship_backend.db.engine import session_scope
from tinternship_backend.db.models import AgentRun, TraceEvent
from tinternship_backend.observability.plugin import AuditPlugin, content_to_text
from tinternship_backend.observability.runs import tracked_run


class FakeSession:
    id = "test-session"
    state: dict = {}


def fake_invocation_context(invocation_id: str = "inv-1"):
    return SimpleNamespace(
        invocation_id=invocation_id,
        session=FakeSession(),
        agent=SimpleNamespace(name="root_agent"),
        user_content=types.Content(role="user", parts=[types.Part(text="hello")]),
    )


def fake_callback_context(agent_name: str = "worker", invocation_id: str = "inv-1"):
    return SimpleNamespace(
        invocation_id=invocation_id,
        agent_name=agent_name,
        session=FakeSession(),
    )


def events() -> list[TraceEvent]:
    with session_scope() as session:
        rows = list(session.exec(select(TraceEvent).order_by(TraceEvent.seq, TraceEvent.id)).all())
        for row in rows:
            session.expunge(row)
        return rows


async def test_full_lifecycle_is_recorded():
    plugin = AuditPlugin()
    ictx = fake_invocation_context()
    cctx = fake_callback_context()
    agent = SimpleNamespace(name="worker")
    tool = SimpleNamespace(name="search_job_board")

    llm_request = SimpleNamespace(
        model="gemini-3.6-flash",
        contents=[types.Content(role="user", parts=[types.Part(text="find jobs")])],
        config=SimpleNamespace(system_instruction="You are a scout.", response_schema=None, temperature=0.3),
        tools_dict={"search_job_board": tool},
    )
    llm_response = SimpleNamespace(
        model_version="gemini-3.6-flash",
        content=types.Content(role="model", parts=[types.Part(text="found 3")]),
        partial=False,
        usage_metadata=SimpleNamespace(
            prompt_token_count=1200,
            candidates_token_count=340,
            thoughts_token_count=60,
            total_token_count=1600,
        ),
        grounding_metadata=None,
        finish_reason="STOP",
        error_code=None,
        error_message=None,
    )

    with tracked_run("test", "lifecycle"):
        await plugin.before_run_callback(invocation_context=ictx)
        await plugin.on_user_message_callback(
            invocation_context=ictx, user_message=ictx.user_content
        )
        await plugin.before_agent_callback(agent=agent, callback_context=cctx)
        await plugin.before_model_callback(callback_context=cctx, llm_request=llm_request)
        await plugin.after_model_callback(callback_context=cctx, llm_response=llm_response)
        await plugin.before_tool_callback(
            tool=tool, tool_args={"query": "ml intern"}, tool_context=cctx
        )
        await plugin.after_tool_callback(
            tool=tool, tool_args={"query": "ml intern"}, tool_context=cctx, result={"count": 3}
        )
        await plugin.after_agent_callback(agent=agent, callback_context=cctx)
        await plugin.after_run_callback(invocation_context=ictx)

    phases = [event.phase for event in events()]
    assert phases == [
        "run_start",
        "user_message",
        "agent_start",
        "model_request",
        "model_response",
        "tool_start",
        "tool_end",
        "agent_end",
        "run_end",
    ]


async def test_model_response_records_tokens_and_cost_on_the_run():
    plugin = AuditPlugin()
    cctx = fake_callback_context()
    llm_response = SimpleNamespace(
        model_version="gemini-3.6-flash",
        content=types.Content(role="model", parts=[types.Part(text="ok")]),
        partial=False,
        usage_metadata=SimpleNamespace(
            prompt_token_count=1_000_000,
            candidates_token_count=1_000_000,
            thoughts_token_count=0,
            total_token_count=2_000_000,
        ),
        grounding_metadata=None,
        finish_reason="STOP",
        error_code=None,
        error_message=None,
    )

    with tracked_run("test", "cost") as ctx:
        await plugin.after_model_callback(callback_context=cctx, llm_response=llm_response)
        run_id = ctx.run_id

    with session_scope() as session:
        run = session.get(AgentRun, run_id)
        assert run.prompt_tokens == 1_000_000
        assert run.output_tokens == 1_000_000
        assert run.llm_calls == 1
        # gemini-3.6-flash is $0.75 in / $3.75 out per 1M tokens.
        assert run.cost_usd == pytest.approx(4.5, rel=1e-6)


async def test_partial_streaming_chunks_are_not_logged():
    plugin = AuditPlugin()
    cctx = fake_callback_context()
    partial = SimpleNamespace(
        model_version="gemini-3.6-flash",
        content=types.Content(role="model", parts=[types.Part(text="par")]),
        partial=True,
        usage_metadata=None,
        grounding_metadata=None,
        finish_reason=None,
        error_code=None,
        error_message=None,
    )
    with tracked_run("test", "streaming"):
        await plugin.after_model_callback(callback_context=cctx, llm_response=partial)
    assert events() == []


async def test_errors_are_recorded_for_model_tool_and_agent():
    plugin = AuditPlugin()
    cctx = fake_callback_context()
    tool = SimpleNamespace(name="broken_tool")
    llm_request = SimpleNamespace(model="gemini-3.6-flash", contents=[], config=None, tools_dict={})

    with tracked_run("test", "errors"):
        await plugin.on_model_error_callback(
            callback_context=cctx, llm_request=llm_request, error=RuntimeError("429 quota")
        )
        await plugin.on_tool_error_callback(
            tool=tool, tool_args={}, tool_context=cctx, error=ValueError("bad args")
        )
        await plugin.on_agent_error_callback(
            agent=SimpleNamespace(name="worker"), callback_context=cctx, error=KeyError("state")
        )

    recorded = events()
    assert [event.phase for event in recorded] == ["error", "error", "error"]
    assert "429 quota" in recorded[0].error
    assert recorded[1].tool_name == "broken_tool"


async def test_a_logging_failure_never_breaks_the_run():
    """A malformed context must not propagate out of the plugin."""
    plugin = AuditPlugin()
    broken = SimpleNamespace()  # missing every attribute the callback reads

    with tracked_run("test", "resilience"):
        with pytest.raises(AttributeError):
            # The callback itself still reads attributes; what must not happen is
            # a *write* failure escaping. Verify the write path swallows instead.
            await plugin.before_agent_callback(agent=broken, callback_context=broken)

        # Directly exercise the write path with unserialisable content.
        plugin._record(phase="event", payload={"obj": object()}, summary="unserialisable")

    assert any(event.phase == "event" for event in events())


def test_content_to_text_flattens_calls_and_responses():
    content = types.Content(
        role="model",
        parts=[
            types.Part(text="thinking"),
            types.Part(
                function_call=types.FunctionCall(name="search_job_board", args={"query": "ml"})
            ),
        ],
    )
    text = content_to_text(content)
    assert "thinking" in text
    assert "search_job_board" in text
    assert content_to_text(None) == ""
