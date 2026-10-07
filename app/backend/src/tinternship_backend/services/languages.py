"""The languages an application package can be written in.

One shared vocabulary, because three layers need to agree on it: the API
validates what the UI sent, the Applying agents are told which one to write in,
and the renderer picks its section headings from it.
"""

from __future__ import annotations

from typing import Any

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "fr")


def normalise_language(value: Any) -> str:
    """Map anything a model or an API caller hands us onto a supported code.

    Accepts `fr`, `fr-FR`, `FR `, `French`… and falls back to the default rather
    than raising: a résumé in the wrong language is recoverable, a 500 on the
    generate button is not. The API validates explicit user input separately.
    """
    code = str(value or "").strip().lower()[:2]
    return code if code in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
