from __future__ import annotations
from pathlib import Path

from dotenv import dotenv_values


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DOTENV_PATH = _PROJECT_ROOT / ".env"
_DOTENV = dotenv_values(_DOTENV_PATH)


def env(key: str, default: str | None = None) -> str | None:
    value = _DOTENV.get(key)
    return value if value is not None else default


SENTRY_DSN: str | None = env("SENTRY_DSN")

# OpenTelemetry configuration
OTEL_SERVICE_NAME: str = (
    env("OTEL_SERVICE_NAME", "chatbot-backend") or "chatbot-backend"
)
OTEL_EXPORTER_OTLP_ENDPOINT: str = (
    env("OTEL_EXPORTER_OTLP_ENDPOINT", "http://141.148.203.99:4318")
    or "http://141.148.203.99:4318"
)
OTEL_EXPORTER_OTLP_PROTOCOL: str = (
    env("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf") or "http/protobuf"
)
OTEL_TRACES_EXPORTER: str = env("OTEL_TRACES_EXPORTER", "otlp") or "otlp"
