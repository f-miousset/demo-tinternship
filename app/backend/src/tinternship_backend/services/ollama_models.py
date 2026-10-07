"""What the local Ollama is serving.

The same job `gemini_models.py` does for the API, against `/api/tags` on the
machine instead. "Local" is Ollama's sense of the word, not necessarily yours:
a `…-cloud` model is listed like any other but runs on ollama.com, so
`remote_host` travels with each option and the UI only promises privacy for the
ones that really are on the machine. Ollama reports a `capabilities` list per model,
which is what separates a model an agent can use from an embedding model that
would only fail at run time.

Tool-calling capability is deliberately *not* filtered on. The only agents that
carry a tool are the two grounded ones, and those stay on Gemini — and a model
without it still honours an `output_schema`, because Ollama enforces the schema
itself rather than leaving it to the model (verified on gemma3:4b, which reports
no tool support and returns valid structured output anyway).

Unreachable is the normal case, not an error: Ollama is optional, and most of
the time this returns an empty list quickly and the picker simply has no local
section. Which is why the timeout is short — a laptop with Ollama shut down
must not make the Settings page hang.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from ..agents.models import OLLAMA_PREFIX
from ..config import get_settings

logger = logging.getLogger(__name__)

CACHE_TTL = 60.0  # seconds; `ollama pull` should show up without a restart
PROBE_TIMEOUT = 2.0  # seconds; not running is the common answer

_cache: tuple[float, list[LocalModel]] | None = None


@dataclass(frozen=True)
class LocalModel:
    """One model Ollama serves. `id` carries the prefix agents resolve on."""

    id: str
    name: str
    #: Where the weights actually run. Empty for a model on this machine, and
    #: the host name for one Ollama is proxying to (`…-cloud` models run on
    #: ollama.com). The UI must not promise "nothing leaves your machine" about
    #: one of those, so the distinction travels with the option.
    remote_host: str = ""

    @property
    def on_this_machine(self) -> bool:
        return not self.remote_host


def _fetch() -> list[LocalModel]:
    settings = get_settings()
    response = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=PROBE_TIMEOUT)
    response.raise_for_status()

    models: list[LocalModel] = []
    for entry in response.json().get("models", []):
        name = entry.get("name") or entry.get("model") or ""
        capabilities = entry.get("capabilities") or []
        # No `capabilities` key at all is an older Ollama; assume it generates.
        if name and (not capabilities or "completion" in capabilities):
            models.append(
                LocalModel(
                    id=f"{OLLAMA_PREFIX}{name}",
                    name=name,
                    remote_host=_host(entry.get("remote_host") or ""),
                )
            )
    return sorted(models, key=lambda model: model.id)


def _host(url: str) -> str:
    """`https://ollama.com:443` -> `ollama.com`, for something short to show."""
    return url.split("://")[-1].split("/")[0].split(":")[0]


def available(*, refresh: bool = False) -> list[LocalModel]:
    """Every local model, or an empty list if Ollama is not answering."""
    global _cache

    now = time.monotonic()
    if not refresh and _cache is not None and now - _cache[0] < CACHE_TTL:
        return _cache[1]

    try:
        models = _fetch()
    except Exception as exc:
        # Debug, not warning: no Ollama is a normal way to run this app.
        logger.debug("Ollama is not answering at %s (%s)", get_settings().ollama_base_url, exc)
        models = []

    _cache = (now, models)
    return models


def is_reachable() -> bool:
    return bool(available())


def invalidate() -> None:
    global _cache
    _cache = None
