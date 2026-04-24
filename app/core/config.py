from __future__ import annotations

import json
import os
from typing import Literal

from pydantic import field_validator
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
    SQLALCHEMY_DATABASE_URI: str
    # Sync URI for pgvector / LangChain (psycopg2)
    SQLALCHEMY_SYNC_DATABASE_URI: str

    # === LLM Configuration (Minimax m2.7 via OpenAI-compat) ===
    LLM_API_KEY: str
    LLM_BASE_URL: str = "https://api.minimax.io/v1"
    LLM_MODEL: str = "minimax-m2.7"

    # === Firecrawl Configuration ===
    FIRECRAWL_API_KEY: str

    # === SERP API Configuration ===
    SERP_API_KEY: str | None = None
    SERP_FLIGHTS_URL: str = "https://serpapi.com/search?engine=google_flights"
    SERP_HOTELS_URL: str = "https://serpapi.com/search?engine=google_hotels"
    SERP_GL: str = "us"
    SERP_HL: str = "en"

    # === Google Maps Configuration ===
    GOOGLE_MAPS_API_KEY: str

    # === Vector Store Configuration ===
    PGVECTOR_COLLECTION: str = "travel_knowledge"

    # === API Configuration ===
    API_V1_PREFIX: str = "/api/v1"
    API_TITLE: str = "Chatbot Backend API"
    API_VERSION: str = "0.1.0"

    # === Security Configuration ===
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24
    JWT_REFRESH_EXPIRATION_DAYS: int = 30
    PASSWORD_RESET_EXPIRATION_MINUTES: int = 30
    AUTH_ACCESS_COOKIE_NAME: str = "chatbot_access_token"
    AUTH_REFRESH_COOKIE_NAME: str = "chatbot_refresh_token"
    AUTH_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"

    # === CORS Configuration ===
    CORS_ORIGINS: list[str]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("[") and text.endswith("]"):
                return json.loads(text)
            return [item.strip() for item in text.split(",") if item.strip()]

        return value

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
        enable_decoding=False,
        validate_default=True,
    )


# Singleton instance - used throughout the app
if "DEBUG" in os.environ and os.environ["DEBUG"].lower() not in (
    "true",
    "false",
    "0",
    "1",
    "yes",
    "no",
):
    os.environ["DEBUG"] = "false"

settings = Settings()
