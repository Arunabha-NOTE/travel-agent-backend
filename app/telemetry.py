import os
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter


def setup_telemetry():
    resource = Resource.create(
        {
            "service.name": "chatbot-backend",
            "service.version": "0.1.0",
        }
    )

    provider = TracerProvider(resource=resource)

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

    exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
