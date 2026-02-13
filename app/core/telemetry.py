from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

from app.core.config import settings


def setup_telemetry():
    """Initialize OpenTelemetry with tracing to Tempo."""
    # Create resource with service identification
    resource = Resource.create(
        {
            "service.name": settings.OTEL_SERVICE_NAME,
            "service.version": "0.1.0",
            "deployment.environment": "production",
        }
    )

    # Set up trace provider
    provider = TracerProvider(resource=resource)

    # Configure OTLP exporter (only if enabled)
    if settings.OTEL_TRACES_EXPORTER == "otlp":
        exporter = OTLPSpanExporter(
            endpoint=f"{settings.OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces"
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))

    # Set global tracer provider
    trace.set_tracer_provider(provider)

    # Auto-instrument libraries
    SQLAlchemyInstrumentor().instrument()
    RequestsInstrumentor().instrument()
