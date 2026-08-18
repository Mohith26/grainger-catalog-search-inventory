"""API contract: consistent envelope + bounded pagination."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration


def _assert_envelope(body: dict):
    assert set(body.keys()) == {"success", "data", "error", "meta"}


def test_search_envelope_and_meta(client: TestClient):
    resp = client.get("/search", params={"q": "hex bolt", "limit": 5})
    body = resp.json()
    _assert_envelope(body)
    assert body["success"] is True
    assert body["error"] is None
    meta = body["meta"]
    assert meta["limit"] == 5
    assert meta["offset"] == 0
    assert meta["returned"] == len(body["data"]["results"])
    assert meta["returned"] <= 5


def test_pagination_offset_advances_results(client: TestClient):
    page1 = client.get("/search", params={"q": "hex bolt", "limit": 5, "offset": 0}).json()
    page2 = client.get("/search", params={"q": "hex bolt", "limit": 5, "offset": 5}).json()
    ids1 = {r["id"] for r in page1["data"]["results"]}
    ids2 = {r["id"] for r in page2["data"]["results"]}
    assert ids1.isdisjoint(ids2)
    assert page1["meta"]["total"] == page2["meta"]["total"]


def test_limit_upper_bound_enforced(client: TestClient):
    # 100 is the max allowed; 101 must be rejected.
    assert client.get("/search", params={"q": "bolt", "limit": 100}).status_code == 200
    assert client.get("/search", params={"q": "bolt", "limit": 101}).status_code == 422


def test_product_detail_envelope(client: TestClient):
    resp = client.get("/products/1")
    body = resp.json()
    _assert_envelope(body)
    assert body["data"]["id"] == 1
    assert body["data"]["part_no"]


def test_not_found_uses_error_envelope(client: TestClient):
    resp = client.get("/products/999999")
    body = resp.json()
    _assert_envelope(body)
    assert resp.status_code == 404
    assert body["success"] is False
    assert body["error"]


def test_availability_envelope(client: TestClient):
    resp = client.get("/availability", params={"sku": "IRO-HBH-00055", "region": "TX"})
    body = resp.json()
    _assert_envelope(body)
    data = body["data"]
    assert data["sku"] == "IRO-HBH-00055"
    assert data["total_atp"] == data["total_on_hand"] - data["total_reserved"]
    assert len(data["warehouses"]) == 5
