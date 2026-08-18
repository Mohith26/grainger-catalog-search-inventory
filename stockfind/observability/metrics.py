"""Prometheus metrics: request counts + latency histogram, per-app registry.

A fresh ``CollectorRegistry`` per app keeps metric families from colliding when
tests construct several apps in one process. The middleware labels by method,
route template (not raw path, to bound cardinality), and status.
"""

from __future__ import annotations

import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

_LATENCY_BUCKETS = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)


class Metrics:
    """Holds a private registry and the two core HTTP metrics."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests_total = Counter(
            "stockfind_http_requests_total",
            "Total HTTP requests processed.",
            labelnames=("method", "path", "status"),
            registry=self.registry,
        )
        self.request_duration = Histogram(
            "stockfind_http_request_duration_seconds",
            "HTTP request latency in seconds.",
            labelnames=("method", "path"),
            buckets=_LATENCY_BUCKETS,
            registry=self.registry,
        )

    def render(self) -> tuple[bytes, str]:
        return generate_latest(self.registry), CONTENT_TYPE_LATEST


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or request.url.path


class PrometheusMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, metrics: Metrics) -> None:
        super().__init__(app)
        self._metrics = metrics

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        status_code = 500
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - start
            path = _route_template(request)
            self._metrics.request_duration.labels(request.method, path).observe(elapsed)
            self._metrics.requests_total.labels(
                request.method, path, str(status_code)
            ).inc()
