import sentry_sdk
import time
from fastapi import FastAPI, Request, Response
from app.core.config import settings
from app.core.logging import structlog
from app.core.metrics import HTTP_REQUESTS, HTTP_LATENCY
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from app.core.telemetry import setup_telemetry

logger = structlog.get_logger(__name__)

sentry_sdk.init(
    dsn=settings.SENTRY_DSN,
    send_default_pii=True,
)

setup_telemetry()

app = FastAPI()

FastAPIInstrumentor.instrument_app(app)


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
