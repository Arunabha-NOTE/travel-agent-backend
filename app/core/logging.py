from __future__ import annotations

import os
import sys
import logging
import logging.handlers
from pathlib import Path

import structlog
from structlog.processors import (
    JSONRenderer,
    KeyValueRenderer,
    TimeStamper,
    add_log_level,
)
from structlog.stdlib import LoggerFactory, ProcessorFormatter

from app.core.config import settings


def setup_logging() -> None:
    """
    Configure structlog with environment-specific settings.

    - Development: Pretty console output with colors
    - Production: JSON output to both file and console for Loki/Prometheus
    """

    # Create logs directory if it doesn't exist
    logs_dir = Path(__file__).resolve().parent.parent.parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Configure standard library logging first
    log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # === Console Handler ===
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)

    # Choose formatter based on environment
    if settings.DEBUG:
        # Development: Pretty human-readable format
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    else:
        # Production: JSON for structured logging
        formatter = ProcessorFormatter(
            processor=JSONRenderer(),
            foreign_pre_chain=[
                add_log_level,
                TimeStamper(fmt="iso"),
            ],
        )

    argv_text = " ".join(sys.argv).lower()
    is_pytest_run = (
        os.getenv("PYTEST_CURRENT_TEST") is not None
        or os.getenv("PYTEST_VERSION") is not None
        or "pytest" in argv_text
    )
    enable_file_logging = not is_pytest_run

    if enable_file_logging:
        file_handler = logging.handlers.RotatingFileHandler(
            logs_dir / "app.log",
            maxBytes=10_000_000,  # 10MB
            backupCount=5,
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)

    console_handler.setFormatter(formatter)

    # Add handlers to root logger
    if enable_file_logging:
        root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # === Configure structlog ===
    structlog.configure(
        processors=[
            add_log_level,
            TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            # Add context data (request ID, user ID, etc.)
            structlog.processors.CallsiteParameterAdder(),
            # Choose renderer based on environment
            JSONRenderer() if not settings.DEBUG else KeyValueRenderer(),
        ],
        context_class=dict,
        logger_factory=LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        A structlog BoundLogger instance
    """
    return structlog.get_logger(name)


# Initialize logging on import
setup_logging()
