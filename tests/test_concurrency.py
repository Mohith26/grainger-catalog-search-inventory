"""Zero oversell under concurrent reservations (SELECT ... FOR UPDATE)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from stockfind import db
from stockfind.errors import InsufficientStockError
from stockfind.inventory.reserve import reserve

pytestmark = pytest.mark.integration

SKU = "IRO-HBH-00055"
WH = "TXDAL"


def _set_stock(on_hand: int) -> None:
    with db.get_pool().connection() as conn:
        conn.execute(
            "UPDATE inventory SET on_hand=%s, reserved=0 WHERE warehouse_code=%s "
            "AND product_id=(SELECT id FROM products WHERE part_no=%s)",
            (on_hand, WH, SKU),
        )
        conn.commit()


def _reserved() -> int:
    row = db.fetch_one(
        "SELECT reserved, on_hand FROM inventory WHERE warehouse_code=%s "
        "AND product_id=(SELECT id FROM products WHERE part_no=%s)",
        (WH, SKU),
    )
    return row["reserved"]


def _race(on_hand: int, qty: int, attempts: int) -> int:
    _set_stock(on_hand)

    def attempt(_: int) -> bool:
        try:
            reserve(SKU, WH, qty, "racer")
            return True
        except InsufficientStockError:
            return False

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        results = list(pool.map(attempt, range(attempts)))
    return sum(results)


def test_no_oversell_single_unit(reseed):
    successes = _race(on_hand=10, qty=1, attempts=40)
    # Exactly the available units may be reserved — never more.
    assert successes == 10
    assert _reserved() == 10


def test_no_oversell_multi_unit(reseed):
    successes = _race(on_hand=10, qty=2, attempts=30)
    assert successes == 5  # floor(10 / 2)
    assert _reserved() == 10


def test_reserved_never_exceeds_on_hand(reseed):
    _race(on_hand=7, qty=3, attempts=25)
    row = db.fetch_one(
        "SELECT reserved, on_hand FROM inventory WHERE warehouse_code=%s "
        "AND product_id=(SELECT id FROM products WHERE part_no=%s)",
        (WH, SKU),
    )
    assert row["reserved"] <= row["on_hand"]
