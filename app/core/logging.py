# app/logging.py
import logging
import structlog
from structlog.processors import JSONRenderer
from structlog.stdlib import LoggerFactory

logging.basicConfig(
    filename="logs/app.log",
    level=logging.INFO,
    format="%(message)s",
)

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        JSONRenderer(),
    ],
    logger_factory=LoggerFactory(),
)
