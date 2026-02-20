import time

import sentry_sdk
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.core.config import settings
from app.core.handlers import register_exception_handlers
from app.core.logging import get_logger
from app.core.metrics import HTTP_LATENCY, HTTP_REQUESTS
from app.core.telemetry import setup_telemetry

logger = get_logger(__name__)

sentry_sdk.init(
    dsn=settings.SENTRY_DSN,
    send_default_pii=True,
)

setup_telemetry()

app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
)

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FastAPIInstrumentor.instrument_app(app)

# Register exception handlers
register_exception_handlers(app)

# Include API routers
app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
app.include_router(users_router, prefix=settings.API_V1_PREFIX)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    route = request.scope.get("route")
    path = route.path if route else "unknown"

    HTTP_REQUESTS.labels(
        request.method,
        path,
        response.status_code,
    ).inc()

    HTTP_LATENCY.labels(path).observe(duration)

    return response


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
