from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(prefix="/observability", tags=["observability"])


@router.get("/health")
async def observability_health() -> dict[str, object]:
    """Return observability tooling readiness information."""
    traces_enabled = settings.OTEL_TRACES_EXPORTER.lower() == "otlp"

    return {
        "status": "ok",
        "tracing": {
            "enabled": traces_enabled,
            "exporter": settings.OTEL_TRACES_EXPORTER,
            "otlp_endpoint": settings.OTEL_EXPORTER_OTLP_ENDPOINT,
            "service_name": settings.OTEL_SERVICE_NAME,
            "environment": settings.ENVIRONMENT,
        },
        "metrics": {
            "enabled": True,
            "endpoint": "/metrics",
        },
        "logging": {
            "structured": True,
            "request_id_header": "x-request-id",
        },
    }
