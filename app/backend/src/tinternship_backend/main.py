"""FastAPI entrypoint."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import api_router
from .api.errors import install_error_handlers
from .config import get_settings
from .db.engine import init_db
from .observability.tracing import setup_tracing, shutdown_tracing
from .services import follow_up, runtime_config

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    init_db()
    # Settings the user changed from the UI shadow .env, and have to be back on
    # the shared Settings instance before the first agent is built.
    runtime_config.apply()
    setup_tracing()
    logger.info("Tinternship ready — data in %s", settings.data_path)
    if not settings.google_api_key:
        logger.warning("GOOGLE_API_KEY is not set; agent runs will fail until it is.")

    # The only thing in this app that runs without the user asking. It exists so
    # that the nudge and the drafted email arrive together: a notification that
    # says "chase Datadog" and leaves you an empty compose window is the
    # situation the candidate was already in. It costs one model call per
    # application per silence and nothing when nothing has gone quiet — see
    # services/follow_up.py.
    sweeper = asyncio.create_task(follow_up.sweeper(), name="follow-up-sweeper")
    try:
        yield
    finally:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper
        shutdown_tracing()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Tinternship",
        version=__version__,
        description=(
            "A multi-agent internship search and application copilot, with every agent "
            "decision traced and audited."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    install_error_handlers(app)
    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "tinternship_backend.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=True,
    )
