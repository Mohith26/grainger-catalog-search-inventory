"""Observability: /metrics, request-id propagation, /health, /ready."""

from __future__ import annotations

import pytest
import structlog
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration


def test_health_ok(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ok"


def test_ready_checks_database(client: TestClient):
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ready"


def test_metrics_exposes_histogram_and_counter(client: TestClient):
    client.get("/search", params={"q": "hex bolt"})
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    assert "stockfind_http_request_duration_seconds_bucket" in body
    assert "stockfind_http_requests_total" in body
    # A labeled sample for the /search route should be present.
    assert "/search" in body


def test_request_id_echoed_on_response(client: TestClient):
    resp = client.get("/health")
    assert "X-Request-ID" in resp.headers
    assert len(resp.headers["X-Request-ID"]) > 0


def test_incoming_request_id_is_preserved(client: TestClient):
    rid = "trace-abc-123"
    resp = client.get("/health", headers={"X-Request-ID": rid})
    assert resp.headers["X-Request-ID"] == rid


def test_structured_logs_carry_request_id(client: TestClient):
    """Capture structlog output and assert a request_id is bound to the access log."""
    cap = structlog.testing.LogCapture()
    structlog.configure(processors=[structlog.contextvars.merge_contextvars, cap])
    try:
        client.get("/search", params={"q": "bolt"})
    finally:
        # Restore normal logging configuration for later tests.
        from stockfind.observability.logging import configure_logging

        configure_logging()
    completed = [e for e in cap.entries if e.get("event") == "request_completed"]
    assert completed, "expected a request_completed access log"
    assert all("request_id" in e for e in completed)
    assert any(e.get("path") == "/search" for e in completed)
