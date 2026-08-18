"""Inventory ATP: available-to-promise correctness, decrement, nearest, backorder."""

from __future__ import annotations

import pytest

from stockfind import db
from stockfind.errors import InsufficientStockError, NotFoundError
from stockfind.inventory.availability import get_availability
from stockfind.inventory.reserve import release, reserve

pytestmark = pytest.mark.integration

SKU = "IRO-HBH-00055"
WH = "TXDAL"


def _set_stock(sku: str, wh: str, on_hand: int, reserved: int = 0) -> None:
    with db.get_pool().connection() as conn:
        conn.execute(
            "UPDATE inventory SET on_hand=%s, reserved=%s WHERE warehouse_code=%s "
            "AND product_id=(SELECT id FROM products WHERE part_no=%s)",
            (on_hand, reserved, wh, sku),
        )
        conn.commit()


def test_atp_equals_on_hand_minus_reserved_every_warehouse():
    avail = get_availability(SKU)
    for w in avail["warehouses"]:
        assert w["atp"] == w["on_hand"] - w["reserved"]
    assert avail["total_atp"] == avail["total_on_hand"] - avail["total_reserved"]


def test_reservation_decrements_atp(reseed):
    _set_stock(SKU, WH, on_hand=50, reserved=0)
    before = _wh(SKU, WH)["atp"]
    result = reserve(SKU, WH, 10, "buyer1")
    after = _wh(SKU, WH)["atp"]
    assert after == before - 10
    assert result["remaining_atp"] == after


def test_release_restores_atp(reseed):
    _set_stock(SKU, WH, on_hand=50, reserved=0)
    r = reserve(SKU, WH, 15, "buyer1")
    release(r["reservation_id"])
    assert _wh(SKU, WH)["atp"] == 50


def test_release_is_idempotent(reseed):
    _set_stock(SKU, WH, on_hand=50, reserved=0)
    r = reserve(SKU, WH, 5, "buyer1")
    first = release(r["reservation_id"])
    second = release(r["reservation_id"])
    assert first["restored_atp"] == second["restored_atp"] == 50


def test_reserve_more_than_available_raises(reseed):
    _set_stock(SKU, WH, on_hand=3, reserved=0)
    with pytest.raises(InsufficientStockError):
        reserve(SKU, WH, 4, "buyer1")
    # Nothing was reserved on failure.
    assert _wh(SKU, WH)["reserved"] == 0


def test_reserve_down_to_exactly_zero(reseed):
    _set_stock(SKU, WH, on_hand=8, reserved=0)
    reserve(SKU, WH, 8, "buyer1")
    assert _wh(SKU, WH)["atp"] == 0


def test_unknown_sku_raises_not_found():
    with pytest.raises(NotFoundError):
        get_availability("DOES-NOT-EXIST")


def test_nearest_warehouse_is_closest_with_stock(reseed):
    # Force TX warehouse to have stock, make sure nearest for region=TX is TXDAL.
    _set_stock(SKU, "TXDAL", on_hand=100, reserved=0)
    avail = get_availability(SKU, region="TX")
    assert avail["nearest_available_warehouse"] == "TXDAL"
    # Distances are populated and sorted ascending when a region is supplied.
    distances = [w["distance_km"] for w in avail["warehouses"]]
    assert distances == sorted(distances)


def test_backorder_flag_when_no_stock_anywhere(reseed):
    for wh in ("ILCHI", "TXDAL", "CALAX", "GAATL", "NJEWR"):
        _set_stock(SKU, wh, on_hand=0, reserved=0)
    avail = get_availability(SKU, region="TX")
    assert avail["total_atp"] == 0
    assert avail["backorder"] is True
    assert avail["nearest_available_warehouse"] is None
    assert avail["lead_time_days"] >= 0


def _wh(sku: str, wh: str) -> dict:
    avail = get_availability(sku)
    return next(w for w in avail["warehouses"] if w["code"] == wh)
