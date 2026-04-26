from __future__ import annotations

import logging
from opentelemetry import trace, _logs
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_telemetry_initialized = False


def get_tracer(name: str):
    """Return a tracer instance for manual spans."""
    return trace.get_tracer(name)


def setup_telemetry(engine: AsyncEngine | None = None) -> None:
    """Initialize OpenTelemetry with tracing and logging."""
    global _telemetry_initialized

    if _telemetry_initialized:
        return

    # Create resource with service identification
    resource = Resource.create(
        {
            "service.name": settings.OTEL_SERVICE_NAME,
            "service.version": "0.1.0",
            "deployment.environment": settings.ENVIRONMENT,
        }
    )

    # === Trace Setup ===
    trace_provider = TracerProvider(resource=resource)
    if settings.OTEL_TRACES_EXPORTER == "otlp":
        trace_exporter = OTLPSpanExporter(
            endpoint=f"{settings.OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces"
        )
        trace_provider.add_span_processor(BatchSpanProcessor(trace_exporter))

    trace.set_tracer_provider(trace_provider)

    # === Logs Setup ===
    if settings.OTEL_LOGS_EXPORTER == "otlp":
        log_provider = LoggerProvider(resource=resource)
        log_exporter = OTLPLogExporter(
            endpoint=f"{settings.OTEL_EXPORTER_OTLP_ENDPOINT}/v1/logs"
        )
        log_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
        _logs.set_logger_provider(log_provider)

        # Add the OTLP LoggingHandler to the root logger
        handler = LoggingHandler(level=logging.INFO, logger_provider=log_provider)
        logging.getLogger().addHandler(handler)

    # Auto-instrument libraries
    if not RequestsInstrumentor().is_instrumented_by_opentelemetry:
        RequestsInstrumentor().instrument()

    if not LoggingInstrumentor().is_instrumented_by_opentelemetry:
        LoggingInstrumentor().instrument(set_logging_format=False)

    sqlalchemy_instrumentor = SQLAlchemyInstrumentor()
    if (
        engine is not None
        and not sqlalchemy_instrumentor.is_instrumented_by_opentelemetry
    ):
        sqlalchemy_instrumentor.instrument(engine=engine.sync_engine)

    logger.info(
        "OpenTelemetry initialized",
        service_name=settings.OTEL_SERVICE_NAME,
        environment=settings.ENVIRONMENT,
        traces_exporter=settings.OTEL_TRACES_EXPORTER,
        logs_exporter=settings.OTEL_LOGS_EXPORTER,
    )
    _telemetry_initialized = True


def instrument_fastapi(app) -> None:
    """Instrument FastAPI app for automatic request spans."""
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/metrics")
