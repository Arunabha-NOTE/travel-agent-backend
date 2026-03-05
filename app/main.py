import time
from contextlib import asynccontextmanager
from uuid import uuid4

import sentry_sdk
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import trace
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.v1.auth import router as auth_router
from app.api.v1.observability import router as observability_router
from app.api.v1.users import router as users_router
from app.core.config import settings
from app.core.handlers import register_exception_handlers
from app.core.logging import get_logger
from app.core.metrics import HTTP_LATENCY, HTTP_REQUESTS
from app.core.telemetry import instrument_fastapi, setup_telemetry
from app.db.base import Base
from app.db.session import engine

import app.models  # noqa: F401

logger = get_logger(__name__)

sentry_sdk.init(
    dsn=settings.SENTRY_DSN,
    send_default_pii=True,
)

setup_telemetry(engine=engine)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize runtime resources at application startup."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as error:
        logger.warning("Database table initialization skipped", error=str(error))

    yield

app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    lifespan=lifespan,
)

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

instrument_fastapi(app)

# Register exception handlers
register_exception_handlers(app)

# Include API routers
app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
app.include_router(users_router, prefix=settings.API_V1_PREFIX)
app.include_router(observability_router, prefix=settings.API_V1_PREFIX)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    request_id = request.headers.get("x-request-id") or str(uuid4())
    path = request.url.path
    method = request.method
    status_code = 500
    response = None
    raised_error: Exception | None = None

    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        current_span.set_attribute("http.request_id", request_id)
        current_span.set_attribute("http.request.method", method)
        current_span.set_attribute("http.request.path", path)

    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as error:
        raised_error = error
        logger.exception(
            "Request failed",
            request_id=request_id,
            method=method,
            path=path,
        )

    duration = time.perf_counter() - start

    route = request.scope.get("route")
    metric_path = route.path if route else path

    HTTP_REQUESTS.labels(
        method,
        metric_path,
        status_code,
    ).inc()

    HTTP_LATENCY.labels(metric_path).observe(duration)
    logger.info(
        "Request completed",
        request_id=request_id,
        method=method,
        path=path,
        status_code=status_code,
        duration_ms=round(duration * 1000, 2),
    )

    if response is not None:
        response.headers["x-request-id"] = request_id
        return response

    if raised_error is not None:
        raise raised_error

    return Response(status_code=500)


@app.get("/metrics")
def metrics():
    return Response(
        generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/")
async def root():
    logger.info("Application is running", __path__="/", status="200", method="GET")
    return {"message": "Hello World"}
