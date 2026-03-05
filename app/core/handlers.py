from __future__ import annotations


from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppException
from app.core.logging import get_logger
from app.core.metrics import EXCEPTION_EVENTS

logger = get_logger(__name__)


def _mark_span_error(exc: Exception) -> None:
    span = trace.get_current_span()
    if span and span.is_recording():
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(exc)))


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """
    Handle custom AppException and its subclasses.

    Logs the error with context and returns a standardized JSON response.
    """
    logger.error(
        "Application exception",
        error_code=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
        path=request.url.path,
        method=request.method,
        details=exc.details,
    )
    _mark_span_error(exc)
    EXCEPTION_EVENTS.labels(exc.error_code, request.url.path).inc()

    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """
    Handle standard FastAPI/Starlette HTTPException.

    Converts to our standard error response format.
    """
    logger.warning(
        "HTTP exception",
        status_code=exc.status_code,
        detail=exc.detail,
        path=request.url.path,
        method=request.method,
    )
    _mark_span_error(exc)
    EXCEPTION_EVENTS.labels("HTTP_ERROR", request.url.path).inc()

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": "HTTP_ERROR",
            "message": str(exc.detail),
            "details": {},
        },
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle unexpected exceptions.

    Logs the full traceback and returns a generic error response
    without exposing internal details in production.
    """
    logger.exception(
        "Unexpected exception",
        path=request.url.path,
        method=request.method,
        exc_info=exc,
    )
    _mark_span_error(exc)
    EXCEPTION_EVENTS.labels(exc.__class__.__name__, request.url.path).inc()

    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred",
            "details": {},
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all exception handlers with the FastAPI application.

    Args:
        app: FastAPI application instance
    """
    app.add_exception_handler(
        AppException,
        app_exception_handler,  # type: ignore
    )
    app.add_exception_handler(
        StarletteHTTPException,
        http_exception_handler,  # type: ignore
    )
    app.add_exception_handler(
        Exception,
        general_exception_handler,  # type: ignore
    )
