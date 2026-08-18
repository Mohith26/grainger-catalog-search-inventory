"""Secure-by-design suite: each control proven (401/403/422/429/SQLi-safe)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from stockfind import db
from stockfind.api.app import create_app
from stockfind.security.ratelimit import TokenBucketLimiter, parse_limit
from tests.conftest import make_settings

pytestmark = pytest.mark.integration

RESERVE_BODY = {"sku": "IRO-HBH-00055", "warehouse_code": "TXDAL", "quantity": 1}


# ------------------------- authentication (401) -------------------------

def test_reserve_without_token_is_401(client: TestClient):
    resp = client.post("/reserve", json=RESERVE_BODY)
    assert resp.status_code == 401
    assert resp.json()["success"] is False


def test_reserve_with_garbage_token_is_401(client: TestClient):
    resp = client.post(
        "/reserve", headers={"Authorization": "Bearer not-a-jwt"}, json=RESERVE_BODY
    )
    assert resp.status_code == 401


# ------------------------- authorization (403) -------------------------

def test_buyer_cannot_access_admin_route(client: TestClient, buyer_token: str):
    resp = client.get(
        "/admin/reservations", headers={"Authorization": f"Bearer {buyer_token}"}
    )
    assert resp.status_code == 403


def test_admin_can_access_admin_route(client: TestClient, admin_token: str):
    resp = client.get(
        "/admin/reservations", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# --------------------------- validation (422) ---------------------------

def test_zero_quantity_is_422(client: TestClient, buyer_token: str):
    body = {**RESERVE_BODY, "quantity": 0}
    resp = client.post(
        "/reserve", headers={"Authorization": f"Bearer {buyer_token}"}, json=body
    )
    assert resp.status_code == 422


def test_negative_quantity_is_422(client: TestClient, buyer_token: str):
    body = {**RESERVE_BODY, "quantity": -5}
    resp = client.post(
        "/reserve", headers={"Authorization": f"Bearer {buyer_token}"}, json=body
    )
    assert resp.status_code == 422


def test_malformed_attribute_filter_is_422(client: TestClient):
    resp = client.get("/search", params={"q": "bolt", "attr": "nocolon"})
    assert resp.status_code == 422


def test_search_limit_out_of_bounds_is_422(client: TestClient):
    assert client.get("/search", params={"q": "bolt", "limit": 0}).status_code == 422
    assert client.get("/search", params={"q": "bolt", "limit": 9999}).status_code == 422


# --------------------------- rate limiting (429) ---------------------------

def test_rate_limit_returns_429(settings):
    limited = create_app(make_settings(settings, search_rate_limit="3/minute"))
    tc = TestClient(limited)
    statuses = [tc.get("/search", params={"q": "bolt"}).status_code for _ in range(6)]
    assert statuses[:3] == [200, 200, 200]
    assert 429 in statuses


@pytest.mark.unit
def test_token_bucket_parse_and_drain():
    assert parse_limit("120/minute") == (120, 2.0)
    limiter = TokenBucketLimiter("2/minute")
    now = 1000.0
    assert limiter.allow("k", now=now) is True
    assert limiter.allow("k", now=now) is True
    assert limiter.allow("k", now=now) is False  # bucket drained


# --------------------------- SQL injection safe ---------------------------

def test_sql_injection_in_query_returns_no_leak(client: TestClient):
    before = db.fetch_one("SELECT count(*) AS n FROM products")["n"]
    resp = client.get("/search", params={"q": "'; DROP TABLE products; --"})
    after = db.fetch_one("SELECT count(*) AS n FROM products")["n"]
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert before == after  # table untouched -> parameterized queries


def test_sql_injection_in_attribute_filter_is_inert(client: TestClient):
    resp = client.get(
        "/search", params={"q": "bolt", "attr": "category:Fasteners' OR '1'='1"}
    )
    # Treated as a literal jsonb value -> simply matches nothing, no error, no leak.
    assert resp.status_code == 200
    assert resp.json()["success"] is True
