"""Turning a configured model id into something an `LlmAgent` can run on.

Two providers, one setting. A Gemini id becomes ADK's own `Gemini` model with
retries turned on, and an id prefixed `ollama/` becomes a `LiteLlm` pointed at
the local Ollama. Every agent factory
calls `resolve()` on its way to `LlmAgent(model=...)`, so switching provider is
a Settings change rather than a code change.

**Google Search does not cross the line.** It is not a tool ADK sends to the
model, it is a Gemini server-side feature, and attaching it to anything else
raises `ValueError: Google search tool is not supported for model ...`. The
Scout and the HR researcher are the two agents that carry it, so they ask for
`grounded()` instead of the primary model and stay on Gemini even when
everything else has gone local. This is why the Settings page has a third model
knob rather than two.

Everything else does cross: the writers, the matcher, the normaliser and the
Critic all work on a local model, including the schema-validated ones — Ollama
supports structured output and LiteLLM passes the schema through.

**Every Gemini call retries a 429.** On Vertex AI Gemini is served from a pool
of capacity shared by every customer (Google's "dynamic shared quota"), so a
429 there is the pool being busy for a few seconds, not a budget spent — and
Google's answer to it is to retry with backoff. ADK's default is to not retry
at all, which surfaced as a failed link paste on 2026-09-23 while a single call
a minute later went through. `GEMINI_RETRY` waits roughly 2, 4, 8 and 16 s,
~30 s in all; the long runs stream with a keep-alive, so that wait never trips
Cloudflare's 100-second timeout.
"""

from __future__ import annotations

import logging
from typing import Any

from google.adk.models.google_llm import Gemini
from google.genai import types

from ..config import get_settings

logger = logging.getLogger(__name__)

# The app-level marker for "this one is served by Ollama". LiteLLM spells the
# same thing `ollama_chat/`, which stays in here: `ollama_chat` is the endpoint
# with working tool-calling, and that is an implementation detail, not a choice
# to store in the database.
OLLAMA_PREFIX = "ollama/"
LITELLM_PREFIX = "ollama_chat/"

# 429 and the 5xx family (the library's default list), five attempts in all.
GEMINI_RETRY = types.HttpRetryOptions(attempts=5, initial_delay=2.0, max_delay=30.0)


def is_local(model_id: str) -> bool:
    return model_id.startswith(OLLAMA_PREFIX)


def ollama_name(model_id: str) -> str:
    """`ollama/qwen3.5:9b` -> `qwen3.5:9b`."""
    return model_id.removeprefix(OLLAMA_PREFIX)


def resolve(model_id: str) -> Any:
    """A model id as `LlmAgent(model=...)` wants it.

    A Gemini id becomes ADK's own `Gemini` class — the same thing ADK builds
    from a bare string, so grounding and the Gemini tool surface are untouched —
    only with `GEMINI_RETRY` on it.
    """
    if not is_local(model_id):
        return Gemini(model=model_id, retry_options=GEMINI_RETRY)

    settings = get_settings()
    try:
        from google.adk.models.lite_llm import LiteLlm
    except ImportError as exc:  # pragma: no cover - the extra is a hard dep
        raise RuntimeError(
            "Local models need the LiteLLM extra: `uv add \"google-adk[extensions]\"`."
        ) from exc

    return LiteLlm(
        model=f"{LITELLM_PREFIX}{ollama_name(model_id)}",
        api_base=settings.ollama_base_url,
        # A 12B model on a laptop is not a hosted API. The default would give up
        # mid-thought on the long generations — a full résumé, a search brief.
        timeout=settings.ollama_timeout_seconds,
        # Thinking off, and this is not a preference. A thinking model spends its
        # output budget reasoning in plain prose, and for the agents that declare
        # an `output_schema` — the Critic, the normaliser, the matcher — that
        # prose *is* the response: the run ends having produced no JSON at all,
        # and the audit records a flat 0. Observed on qwen3.5:9b against the
        # Critic's rubric. Harmless on models that cannot think anyway.
        think=False,
    )


def grounded() -> str:
    """The model for the two agents that carry Google Search — always Gemini.

    A local id here would raise deep inside the run, which is a bad place to
    learn about it, so it is corrected up front and logged.
    """
    settings = get_settings()
    model_id = settings.model_grounded
    if is_local(model_id):
        fallback = type(settings).model_fields["model_grounded"].default
        logger.warning(
            "MODEL_GROUNDED is %s, which cannot ground — falling back to %s", model_id, fallback
        )
        return fallback
    return model_id
