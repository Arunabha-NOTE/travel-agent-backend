# app/metrics.py
from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["path"],
)

AUTH_EVENTS = Counter(
    "auth_events_total",
    "Authentication events",
    ["action", "outcome"],
)

EXCEPTION_EVENTS = Counter(
    "exception_events_total",
    "Unhandled/handled exception events",
    ["exception_type", "path"],
)
