from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application configuration loaded from environment variables.

    All settings are validated at startup using Pydantic.
    Environment variables are loaded from .env file and environment.
    """

    # === Sentry Configuration ===
    SENTRY_DSN: str | None = None

    # === OpenTelemetry Configuration ===
    OTEL_SERVICE_NAME: str = "chatbot-backend"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://141.148.203.99:4318"
    OTEL_EXPORTER_OTLP_PROTOCOL: str = "http/protobuf"
    OTEL_TRACES_EXPORTER: str = "otlp"

    # === Database Configuration ===
    SQLALCHEMY_DATABASE_URI: str = (
        "postgresql+asyncpg://user:password@localhost/chatbot"
    )

    # === API Configuration ===
    API_V1_PREFIX: str = "/api/v1"
    API_TITLE: str = "Chatbot Backend API"
    API_VERSION: str = "0.1.0"

    # === Security Configuration ===
    JWT_SECRET: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24

    # === Application Environment ===
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Singleton instance - used throughout the app
settings = Settings()
