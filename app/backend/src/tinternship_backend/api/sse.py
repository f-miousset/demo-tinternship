"""Server-sent events helper for streaming agent runs to the browser."""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Without this, nginx-style proxies buffer the stream and nothing appears
    # until the run finishes.
    "X-Accel-Buffering": "no",
}

# An agent run goes quiet for as long as a model takes to answer, and a proxy
# reads a long silence as a hung origin — Cloudflare gives up at 100 seconds and
# answers 524 while the run carries on here. A comment frame is bytes on the
# wire and nothing to any SSE parser, so it keeps the connection alive without
# the client needing to know it exists.
KEEPALIVE_SECONDS = 15.0
KEEPALIVE_FRAME = ": keep-alive\n\n"

_EXHAUSTED = object()


def format_event(event_type: str, data: Any) -> str:
    payload = json.dumps(data, default=str, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


async def _pull(iterator: AsyncIterator[tuple[str, Any]]) -> Any:
    """The next event, or `_EXHAUSTED` — a sentinel survives being a Task result."""
    try:
        return await iterator.__anext__()
    except StopAsyncIteration:
        return _EXHAUSTED


async def event_stream(
    source: AsyncIterator[tuple[str, Any]],
    *,
    keepalive: float = KEEPALIVE_SECONDS,
) -> AsyncGenerator[str, None]:
    iterator = source.__aiter__()
    # Every pull runs in the *same* copied context. A generator borrows the
    # context of whatever resumes it, so a task per event would hand the source
    # a clean slate each time: `run_context(...)` sets the ambient run on one
    # pull's context and then tries to reset it on another's, which ends the run
    # in a `ValueError` about a token from a different Context — and, before
    # that, leaves `AuditPlugin` reading None and filing every trace event after
    # the first under no run at all.
    context = contextvars.copy_context()
    loop = asyncio.get_running_loop()
    pending: asyncio.Task[Any] | None = None
    try:
        while True:
            if pending is None:
                pending = loop.create_task(_pull(iterator), context=context)
            try:
                # Shielded: the timeout is on *waiting*, not on the run. Letting
                # `wait_for` cancel the pull would abandon a run mid-event every
                # time an agent thought for longer than the keep-alive.
                event = await asyncio.wait_for(asyncio.shield(pending), keepalive)
            except TimeoutError:
                yield KEEPALIVE_FRAME
                continue
            pending = None
            if event is _EXHAUSTED:
                return
            event_type, data = event
            yield format_event(event_type, data)
    except Exception as exc:  # surface the failure to the client rather than hanging
        # Once a frame has been written the response is a 200, so the error
        # handler that would normally humanise this never sees it. Do its job
        # here: the client shows `error` verbatim either way.
        from .errors import humanise

        logger.exception("SSE source failed")
        yield format_event("error", {"error": humanise(exc)[1]})
    finally:
        # The client hung up, or the source raised. Either way nothing will read
        # the event this is still waiting for.
        if pending is not None:
            pending.cancel()


def sse_response(source: AsyncIterator[tuple[str, Any]]) -> StreamingResponse:
    return StreamingResponse(
        event_stream(source), media_type="text/event-stream", headers=SSE_HEADERS
    )
