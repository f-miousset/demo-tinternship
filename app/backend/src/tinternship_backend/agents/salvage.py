"""Keeping what a truncated structured response did manage to say.

A model asked for JSON answers with one string, and every model has a ceiling
on how long that string may be. Hit it and the response stops mid-token: the
JSON is unterminated, ADK's `output_schema` validation raises
`ValidationError: Invalid JSON: EOF while parsing`, and the exception travels up
through the agent, the `SequentialAgent` above it and `runtime.stream`, which
ends the whole run. Everything the earlier stages produced — for the
Investigator, a grounded search that took two and a half minutes — is thrown
away with it, and the candidate is shown an error naming a pydantic URL.

That happened on 2026-08-27: the Matcher looped inside one string field, ran to
`MAX_TOKENS` at 65 537 output tokens, and lost a six-minute run. The first fix
is to give it far less to say (`schemas.ScoredPosting`). This is the second: a
truncated list is still a list of results, minus its tail, and a run that comes
back with eleven of twenty-three postings is worth incomparably more than one
that comes back with a stack trace.

`keep_what_arrived(key)` is an `after_model_callback`. It only ever acts on a
response that does *not* parse, it never invents a field, and it drops the
element that was cut mid-word rather than closing its quotes — half a string is
not a shorter answer, it is a wrong one.

The trace is left alone: `AuditPlugin.after_model_callback` runs first and
records the response as it really arrived, so the decision log still shows the
truncation, the finish reason and the token count that caused it.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.genai import types

logger = logging.getLogger(__name__)

# ADK strips this before validating, so the salvage has to see the same text it
# would have seen — a fenced response that was cut off is still salvageable.
_FENCED = re.compile(r"```\w*\s*(.*?)\s*```", re.DOTALL)


def unfenced(text: str) -> str:
    """A whole-payload ```json fence removed; anything else unchanged."""
    stripped = text.strip()
    match = _FENCED.fullmatch(stripped)
    return match.group(1).strip() if match else text


def complete_items(text: str, key: str) -> list[Any] | None:
    """The elements of `{"<key>": [ … ]}` that arrived whole, in order.

    `None` means this is not that shape at all — prose, a different schema, a
    response cut off before the array even opened — and the caller should leave
    the response alone rather than replace it with something invented. An empty
    list is a different answer: the array opened and not one element closed.
    """
    marker = text.find(f'"{key}"')
    if marker == -1:
        return None

    cursor = marker + len(key) + 2
    for expected in (":", "["):
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor >= len(text) or text[cursor] != expected:
            return None
        cursor += 1

    # `raw_decode` parses exactly one value and says where it ended, so nesting,
    # escapes and quoted brackets are the standard library's problem rather than
    # a hand-written scanner's. The first element it cannot parse is the one
    # that was truncated, and everything before it is intact.
    decoder = json.JSONDecoder()
    items: list[Any] = []
    while cursor < len(text):
        while cursor < len(text) and text[cursor] in ", \t\r\n":
            cursor += 1
        if cursor >= len(text) or text[cursor] == "]":
            break
        try:
            value, cursor = decoder.raw_decode(text, cursor)
        except ValueError:
            break
        items.append(value)
    return items


def repair(text: str, key: str) -> str | None:
    """A truncated `{"<key>": [ … ]}` as valid JSON, or `None` if it is not one.

    Only the list survives. Anything the schema puts *after* it — the Matcher's
    `strategy_notes` — was never written: the response ran out inside the array.
    """
    items = complete_items(text, key)
    if items is None:
        return None
    return json.dumps({key: items}, ensure_ascii=False)


def keep_what_arrived(
    key: str,
) -> Callable[..., Awaitable[LlmResponse | None]]:
    """An `after_model_callback` that rescues a cut-off list response.

    Returns `None` — ADK's "keep the response as it is" — for every response
    that parses, which is all of them on a normal run, and for every failure
    that is not a truncated list of `key`.
    """

    async def callback(
        *, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> LlmResponse | None:
        if llm_response.partial or llm_response.content is None:
            return None
        text = "".join(
            part.text
            for part in (llm_response.content.parts or [])
            if part.text and not part.thought
        )
        if not text.strip():
            return None

        payload = unfenced(text)
        try:
            json.loads(payload)
        except ValueError:
            pass
        else:
            return None

        repaired = repair(payload, key)
        agent = callback_context.agent_name
        reason = str(llm_response.finish_reason or "unknown")
        if repaired is None:
            logger.warning(
                "%s answered with %d characters that are not valid JSON and cannot be "
                "salvaged (finish_reason=%s)",
                agent, len(text), reason,
            )
            return None

        kept = len(json.loads(repaired)[key])
        logger.warning(
            "%s was cut off after %d characters (finish_reason=%s); keeping the %d "
            "%s that arrived whole and dropping the truncated one",
            agent, len(text), reason, kept, key,
        )
        return llm_response.model_copy(
            update={
                "content": types.Content(role="model", parts=[types.Part(text=repaired)])
            }
        )

    return callback
