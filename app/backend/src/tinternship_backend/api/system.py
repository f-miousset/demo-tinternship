"""Health and capability reporting, so the UI can tell the user what is wired up."""

from __future__ import annotations

from fastapi import APIRouter

from ..agents import models as models_service
from ..agents.investigator import MAX_RESULTS, MIN_RESULTS, clamp_results
from ..config import get_settings
from ..services import base_documents, ollama_models
from ..services.onboarding import setup_state
from ..tools.job_sources.platforms import platform_labels
from ..tools.job_sources.registry import source_names

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/config")
async def config():
    """What is configured, and what the user still needs to do."""
    settings = get_settings()

    warnings: list[str] = []
    if not settings.google_api_key:
        warnings.append(
            "GOOGLE_API_KEY is not set — no agent can run. Add it to .env and restart."
        )
    if not settings.adzuna_enabled:
        warnings.append(
            "No structured job board configured. Grounded Google Search still works, but "
            "adding ADZUNA_APP_ID / ADZUNA_APP_KEY improves recall and freshness."
        )
    local_models = sorted(
        {
            model
            for model in (settings.model_primary, settings.model_fast)
            if models_service.is_local(model)
        }
    )
    if local_models and not ollama_models.is_reachable():
        warnings.append(
            f"{', '.join(local_models)} runs on Ollama, but nothing is answering at "
            f"{settings.ollama_base_url}. Start Ollama, or pick a Gemini model in Settings — "
            "runs will fail until one or the other."
        )
    for kind in base_documents.KINDS:
        noun = base_documents.kind_of(kind).noun
        for language in base_documents.missing_languages(kind):
            warnings.append(
                f"No {language} base {noun} uploaded. That is the document an application in "
                f"{language} is built from, so those runs cannot produce one — upload your own "
                f"Word {noun} in the Profile section of the Account page."
            )
        # A document that exists and has no room left on its page is the same
        # outcome as a missing one — `POST …/generate` answers 409 either way —
        # and it is far less obvious, because the Account page shows a green
        # card.
        for language, entry in base_documents.status(kind).items():
            if entry and entry.get("crowded"):
                warnings.append(
                    f"The {language} base {noun} already fills its page, so there is no room "
                    "to fill the blanks in it and applications in that language are blocked. "
                    "Free up a line or two and upload it again."
                )

    return {
        "models": {
            "primary": settings.model_primary,
            "fast": settings.model_fast,
            "grounded": settings.model_grounded,
        },
        "gemini_configured": bool(settings.google_api_key),
        "job_sources": source_names(),
        "priority_platforms": platform_labels(),
        "results": {
            "default": clamp_results(),
            "min": MIN_RESULTS,
            "max": MAX_RESULTS,
        },
        # Which of the four base documents exist. The Account page needs it for
        # the upload boxes, and the application page greys out a language it has
        # no documents for rather than failing once the stream is already open.
        "base_resumes": base_documents.status(base_documents.RESUME),
        "base_cover_letters": base_documents.status(base_documents.COVER_LETTER),
        "audit": {
            "threshold": settings.audit_pass_threshold,
            "max_revisions": settings.audit_max_revisions,
        },
        # The one-time Account setup. `complete` is what gates the numbered
        # steps in the UI, so it has to come from the same place the Account
        # page reads — see services/onboarding.py.
        "progress": await setup_state(),
        "warnings": warnings,
    }
