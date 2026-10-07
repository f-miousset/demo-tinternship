"""Turning provider failures into something the user can act on.

Agent runs fail for a handful of predictable reasons — quota, a bad key, safety
blocks, timeouts — and every one of them arrived as a 500 with a stack trace
until this existed. The UI shows `detail` verbatim, so it has to say what went
wrong *and* what to do about it.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def humanise(error: BaseException) -> tuple[int, str]:
    """Map an exception to (http_status, message)."""
    name = type(error).__name__
    text = str(error)

    if "RESOURCE_EXHAUSTED" in text or "429" in text or "ResourceExhausted" in name:
        return (
            429,
            "Gemini quota exceeded. The free tier is easily used up by a grounded-search "
            "run — check https://ai.dev/rate-limit, wait for the quota window to reset, or "
            "enable billing on the key. Nothing was lost: the partial run is in Traces.",
        )
    if "API_KEY_INVALID" in text or "API key not valid" in text:
        return (
            401,
            "Gemini rejected the API key. Check GOOGLE_API_KEY in .env and restart the "
            "backend — the key is read once at startup.",
        )
    if "PERMISSION_DENIED" in text or "403" in text:
        return (
            403,
            "Gemini denied the request. The key may not have access to this model; try "
            "setting MODEL_PRIMARY to gemini-3.5-flash-lite in .env.",
        )
    if "SAFETY" in text or "blocked" in text.lower():
        return (
            422,
            "Gemini blocked the response under its safety filters. Rephrasing the brief or "
            "the posting text usually clears it.",
        )
    if "DEADLINE_EXCEEDED" in text or "timeout" in text.lower() or "Timeout" in name:
        return (
            504,
            "The model call timed out. Grounded-search runs are slow — try again, or run "
            "the HR Expert before the Investigator so less work happens per request.",
        )
    if "NOT_FOUND" in text and "model" in text.lower():
        return (
            404,
            "Gemini does not recognise the configured model. Check MODEL_PRIMARY and "
            "MODEL_FAST in .env against https://ai.google.dev/gemini-api/docs/models.",
        )
    return 500, f"{name}: {text[:400]}"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def _handle(request: Request, exc: Exception) -> JSONResponse:
        status, message = humanise(exc)
        if status >= 500:
            logger.exception("Unhandled error on %s", request.url.path)
        else:
            logger.warning("%s on %s: %s", type(exc).__name__, request.url.path, message)
        return JSONResponse(status_code=status, content={"detail": message})
