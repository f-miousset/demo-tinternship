"""Per-run ambient context.

`AuditPlugin` needs to know which `AgentRun` row the callbacks it is receiving
belong to. ADK generates the invocation id itself, so we cannot know it before
calling the runner; instead the service layer opens a `run_context(...)` around
the `run_async` loop and the plugin reads the ContextVar. Tasks that ADK spawns
for parallel agents inherit the context at creation time, so fan-out works.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_current_run: ContextVar[RunContext | None] = ContextVar("current_run", default=None)


@dataclass
class RunContext:
    run_id: int
    kind: str
    label: str = ""
    session_id: str = ""
    invocation_id: str = ""
    prompt_version_ids: dict[str, int] = field(default_factory=dict)
    _seq: int = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq


@contextmanager
def run_context(ctx: RunContext) -> Iterator[RunContext]:
    token = _current_run.set(ctx)
    try:
        yield ctx
    finally:
        try:
            _current_run.reset(token)
        except ValueError:
            # A generator holds this open across its yields, so the close can
            # land in a context the token never belonged to: a browser that
            # hangs up mid-run leaves the streaming generator to the event
            # loop's asyncgen finaliser, which runs wherever it likes. There is
            # nothing to restore in that case — the context dies with the task —
            # and the run must not fail over its own cleanup.
            logger.debug("Run %s left its context open in another task", ctx.run_id)


def current_run() -> RunContext | None:
    return _current_run.get()
