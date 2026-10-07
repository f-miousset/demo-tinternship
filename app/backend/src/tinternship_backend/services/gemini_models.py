"""What the configured Gemini key can actually run.

The model pickers on the Settings page ask Google rather than showing a list
this repo maintains, because a hardcoded list is wrong the week after it is
written — the price table in `observability/pricing.py` had seven entries while
the key could reach nearly forty.

Two things are filtered out of the answer:

* anything that cannot `generateContent` at all — embedding models, mostly;
* the single-modality models. Speech, image, music, robotics and the
  computer-use and deep-research agents all advertise `generateContent`, but an
  agent here has to take a prompt, call a tool and return JSON against a schema,
  and picking Nano Banana to write a résumé fails in a way the UI cannot warn
  about after the fact.

The filter is by name because the API exposes no modality field. That makes it
a guess about names not yet invented, so it only ever decides what is *offered*:
both fields stay free text, and a model this list is wrong about can still be
typed in.

On Vertex AI (Google Cloud's "Agent Platform", `GOOGLE_GENAI_USE_VERTEXAI=TRUE`)
there is nothing to ask: the model catalogue answers an API key with
`401 API keys are not supported by this API`, although generating with the same
key works. So there the picker offers the priced models without calling.

The listing is a network call, so it is cached for `CACHE_TTL` and every failure
degrades to the priced models rather than breaking the page.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from ..config import get_settings
from ..observability.pricing import get_model_price, priced_models

logger = logging.getLogger(__name__)

# Fragments that mark a model as built for one modality this app never uses.
NON_TEXT_MARKERS: tuple[str, ...] = (
    "tts",
    "image",
    "nano-banana",
    "lyria",
    "veo",
    "imagen",
    "embedding",
    "robotics",
    "computer-use",
    "deep-research",
    "antigravity",
    "video-understanding",
    "transcribe",
)

CACHE_TTL = 600.0  # seconds; the catalogue moves in weeks, not minutes
LIST_TIMEOUT_MS = 8000

_cache: tuple[float, list[ModelOption]] | None = None


@dataclass(frozen=True)
class ModelOption:
    id: str
    label: str
    priced: bool
    input_price: float | None = None
    output_price: float | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "priced": self.priced,
            "input_price": self.input_price,
            "output_price": self.output_price,
        }


def _is_usable(model_id: str, actions: list[str]) -> bool:
    if "generateContent" not in actions:
        return False
    return not any(marker in model_id for marker in NON_TEXT_MARKERS)


def _uses_vertex() -> bool:
    return get_settings().google_genai_use_vertexai.strip().lower() in {"true", "1"}


def _fallback() -> list[ModelOption]:
    """No key, no network, no answer — offer what the price table knows."""
    options: list[ModelOption] = []
    for name in priced_models():
        price = get_model_price(name)
        options.append(
            ModelOption(
                id=name,
                label="",
                priced=True,
                input_price=price[0] if price else None,
                output_price=price[1] if price else None,
            )
        )
    return options


def _fetch() -> list[ModelOption]:
    from google.genai import Client
    from google.genai.types import HttpOptions

    settings = get_settings()
    client = Client(
        api_key=settings.google_api_key,
        vertexai=False,
        http_options=HttpOptions(timeout=LIST_TIMEOUT_MS),
    )

    options: list[ModelOption] = []
    for model in client.models.list():
        model_id = (model.name or "").removeprefix("models/")
        if not model_id or not _is_usable(model_id, list(model.supported_actions or [])):
            continue
        price = get_model_price(model_id)
        options.append(
            ModelOption(
                id=model_id,
                label=model.display_name or "",
                priced=price is not None,
                input_price=price[0] if price else None,
                output_price=price[1] if price else None,
            )
        )
    # Newest first is the wrong sort for a list of names, and alphabetical puts
    # gemini-3.6 above gemini-3.10. Neither matters enough to parse versions:
    # sorted is at least stable and predictable to scan.
    return sorted(options, key=lambda option: option.id)


def available(*, refresh: bool = False) -> list[ModelOption]:
    """Every model the key can run for this app's kind of work."""
    global _cache

    settings = get_settings()
    if not settings.google_api_key or _uses_vertex():
        return _fallback()

    now = time.monotonic()
    if not refresh and _cache is not None and now - _cache[0] < CACHE_TTL:
        return _cache[1]

    try:
        options = _fetch()
    except Exception:
        # An expired key, an outage, no network. The page still has to render,
        # and the field still accepts anything typed into it.
        logger.warning("Could not list Gemini models; offering the priced ones", exc_info=True)
        return _cache[1] if _cache is not None else _fallback()

    if not options:
        logger.warning("Gemini listed no usable models; offering the priced ones")
        return _fallback()

    _cache = (now, options)
    return options


def invalidate() -> None:
    """Drop the cached listing — used by the tests, and after a key change."""
    global _cache
    _cache = None
