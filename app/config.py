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
