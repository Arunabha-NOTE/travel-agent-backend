from __future__ import annotations

import os


def pytest_configure() -> None:
    os.environ.setdefault(
        "SQLALCHEMY_DATABASE_URI",
        "postgresql+asyncpg://chatbot:chatbot@localhost:5432/chatbot",
    )
    os.environ.setdefault(
        "SQLALCHEMY_SYNC_DATABASE_URI",
        "postgresql+psycopg2://chatbot:chatbot@localhost:5432/chatbot",
    )
    os.environ.setdefault("LLM_API_KEY", "test-llm-key")
    os.environ.setdefault("FIRECRAWL_API_KEY", "test-firecrawl-key")
    os.environ.setdefault("GOOGLE_MAPS_API_KEY", "test-google-maps-key")
    os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
    os.environ.setdefault(
        "CORS_ORIGINS",
        '["http://localhost","http://127.0.0.1","https://travel-agent.arunabha.in"]',
    )
