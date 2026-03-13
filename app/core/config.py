from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    OTEL_TRACES_EXPORTER: str = "none"

    # === Database Configuration ===
    SQLALCHEMY_DATABASE_URI: str = (
        "postgresql+asyncpg://chatbot:chatbot@localhost:5432/chatbot"
    )

    # === API Configuration ===
    API_V1_PREFIX: str = "/api/v1"
    API_TITLE: str = "Chatbot Backend API"
    API_VERSION: str = "0.1.0"

    # === Security Configuration ===
    JWT_SECRET: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24
    JWT_REFRESH_EXPIRATION_DAYS: int = 30
    PASSWORD_RESET_EXPIRATION_MINUTES: int = 30

    # === CORS Configuration ===
    CORS_ORIGINS: list[str] = [
        "http://localhost",
        "http://127.0.0.1",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]

    # === Application Environment ===
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # === Optional Vector DB Configuration ===
    VECTOR_DB_URL: str = "http://localhost:6333"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


# Singleton instance - used throughout the app
settings = Settings()
