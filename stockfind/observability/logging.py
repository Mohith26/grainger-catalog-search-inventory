"""Structured JSON logging with a request ID bound to every log line.

Each request gets an ``X-Request-ID`` (accepted from the caller or generated),
bound into structlog's contextvars so every log emitted while handling that
request carries it. The id is echoed back on the response header for tracing.
"""

from __future__ import annotations

import logging
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

REQUEST_ID_HEADER = "X-Request-ID"


def configure_logging(level: int = logging.INFO) -> None:
    """Configure structlog to emit one JSON object per line to stdout."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "stockfind") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a request id, time the request, and emit a structured access log."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._log = get_logger("stockfind.access")

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            self._log.error("request_failed", duration_ms=duration_ms)
            structlog.contextvars.clear_contextvars()
            raise
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        self._log.info(
            "request_completed",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        structlog.contextvars.clear_contextvars()
        return response
