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
    # Sync URI for pgvector / LangChain (psycopg2)
    SQLALCHEMY_SYNC_DATABASE_URI: str = (
        "postgresql+psycopg2://chatbot:chatbot@localhost:5432/chatbot"
    )

    # === LLM Configuration (Minimax m2.7 via OpenAI-compat) ===
    LLM_API_KEY: str = "changeme"
    LLM_BASE_URL: str = "https://api.minimax.io/v1"
    LLM_MODEL: str = "minimax-m2.7"

    # === Firecrawl Configuration ===
    FIRECRAWL_API_KEY: str = "changeme"

    # === SERP API Configuration ===
    SERP_API_KEY: str | None = None

    # === Google Maps Configuration ===
    GOOGLE_MAPS_API_KEY: str = "changeme"

    # === Vector Store Configuration ===
    PGVECTOR_COLLECTION: str = "travel_knowledge"

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

    # === Optional Vector DB Configuration (legacy) ===
    VECTOR_DB_URL: str = "http://localhost:6333"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        validate_default=True,
    )


# Singleton instance - used throughout the app
try:
    settings = Settings()
except Exception as e:
    # Fallback: Create settings with defaults if environment validation fails
    import os
    # Clear DEBUG environment variable if it has invalid value
    if "DEBUG" in os.environ and os.environ["DEBUG"].lower() not in ("true", "false", "0", "1", "yes", "no"):
        os.environ["DEBUG"] = "false"
    settings = Settings()
