"""OpenTelemetry wiring.

ADK already instruments itself with OTel spans for agent invocations, model
calls (including token usage) and tool calls, and it ships a SQLite span
exporter. We just point that exporter at `data/traces.db`. This is layer 1 of
the audit trail — the low-level, mechanical view. `AuditPlugin` is layer 2, the
semantic one that the UI reads.
"""

from __future__ import annotations

import logging

from google.adk.telemetry.setup import OTelHooks, maybe_set_otel_providers
from google.adk.telemetry.sqlite_span_exporter import SqliteSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from ..config import get_settings

logger = logging.getLogger(__name__)

_exporter: SqliteSpanExporter | None = None
_configured = False


def setup_tracing() -> SqliteSpanExporter | None:
    """Idempotently install the SQLite span exporter as the global tracer."""
    global _exporter, _configured
    if _configured:
        return _exporter

    settings = get_settings()
    try:
        _exporter = SqliteSpanExporter(db_path=str(settings.trace_db_path))
        maybe_set_otel_providers(
            otel_hooks_to_setup=[OTelHooks(span_processors=[BatchSpanProcessor(_exporter)])],
            otel_resource=Resource.create({"service.name": "tinternship"}),
        )
        logger.info("OTel spans → %s", settings.trace_db_path)
    except Exception:
        # Tracing is important but must never stop the app from booting.
        logger.exception("Failed to configure OpenTelemetry; continuing without spans")
        _exporter = None

    _configured = True
    return _exporter


def get_span_exporter() -> SqliteSpanExporter | None:
    return _exporter


def shutdown_tracing() -> None:
    global _configured
    if _exporter is not None:
        try:
            _exporter.force_flush()
            _exporter.shutdown()
        except Exception:
            logger.exception("Failed to shut down the span exporter cleanly")
    _configured = False
