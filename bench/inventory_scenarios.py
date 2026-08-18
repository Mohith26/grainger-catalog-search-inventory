"""Inventory correctness bench: ATP == on_hand - reserved across scenarios,
reservation decrement, and zero oversell under concurrent reservations.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from bench.harness import ensure_seeded
from stockfind import db
from stockfind.errors import InsufficientStockError
from stockfind.inventory.availability import get_availability
from stockfind.inventory.reserve import release, reserve

# Deterministic SKUs (all seeded with known part numbers) used for ATP scenarios.
SCENARIO_SKUS = [
    "IRO-HBH-00055", "IRO-CBC-00454", "ACE-WGW-00583", "DUR-AMA-00743",
    "TIT-HBH-00001", "FLO-BVB-00777", "MAX-GWG-00687", "VOL-CCO-00499",
]


def _wh_atp(sku: str, warehouse: str) -> tuple[int, int, int]:
    row = db.fetch_one(
        """
        SELECT i.on_hand, i.reserved, (i.on_hand - i.reserved) AS atp
        FROM inventory i JOIN products p ON p.id = i.product_id
        WHERE p.part_no = %s AND i.warehouse_code = %s
        """,
        (sku, warehouse),
    )
    return row["on_hand"], row["reserved"], row["atp"]


def _set_stock(sku: str, warehouse: str, on_hand: int, reserved: int = 0) -> None:
    with db.get_pool().connection() as conn:
        conn.execute(
            """
            UPDATE inventory SET on_hand = %s, reserved = %s
            WHERE warehouse_code = %s
              AND product_id = (SELECT id FROM products WHERE part_no = %s)
            """,
            (on_hand, reserved, warehouse, sku),
        )
        conn.commit()


def run_atp_scenarios() -> dict[str, Any]:
    """Every check asserts ATP == on_hand - reserved. Counts correct / total."""
    total = 0
    correct = 0
    for sku in SCENARIO_SKUS:
        avail = get_availability(sku)
        for w in avail["warehouses"]:
            total += 1
            if w["atp"] == w["on_hand"] - w["reserved"]:
                correct += 1
    return {"total": total, "correct": correct,
            "accuracy": round(correct / total, 4) if total else 0.0}


def run_reservation_lifecycle() -> dict[str, Any]:
    """Reserve then release on a controlled row; verify ATP tracks exactly."""
    sku, wh = "IRO-HBH-00055", "TXDAL"
    _set_stock(sku, wh, on_hand=100, reserved=0)
    checks: list[bool] = []

    _, _, atp0 = _wh_atp(sku, wh)
    checks.append(atp0 == 100)

    r1 = reserve(sku, wh, 30, "bench")
    _, _, atp1 = _wh_atp(sku, wh)
    checks.append(atp1 == 70 and r1["remaining_atp"] == 70)

    r2 = reserve(sku, wh, 25, "bench")
    _, _, atp2 = _wh_atp(sku, wh)
    checks.append(atp2 == 45 and r2["remaining_atp"] == 45)

    release(r1["reservation_id"])
    _, _, atp3 = _wh_atp(sku, wh)
    checks.append(atp3 == 75)

    release(r2["reservation_id"])
    _, _, atp4 = _wh_atp(sku, wh)
    checks.append(atp4 == 100)

    return {"steps": len(checks), "passed": sum(checks), "all_correct": all(checks)}


def _concurrent_oversell_trial(sku: str, wh: str, on_hand: int, qty: int,
                               attempts: int) -> dict[str, Any]:
    _set_stock(sku, wh, on_hand=on_hand, reserved=0)

    def attempt(_: int) -> bool:
        try:
            reserve(sku, wh, qty, "racer")
            return True
        except InsufficientStockError:
            return False

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        results = list(pool.map(attempt, range(attempts)))

    successes = sum(results)
    on_hand_after, reserved_after, atp_after = _wh_atp(sku, wh)
    expected_successes = on_hand // qty
    oversell_units = max(0, reserved_after - on_hand_after)
    return {
        "on_hand": on_hand,
        "reserve_qty": qty,
        "concurrent_attempts": attempts,
        "successes": successes,
        "expected_successes": expected_successes,
        "reserved_after": reserved_after,
        "atp_after": atp_after,
        "oversell_units": oversell_units,
        "ok": (successes == expected_successes
               and reserved_after <= on_hand_after
               and oversell_units == 0),
    }


def run_oversell_trials() -> dict[str, Any]:
    trials = [
        _concurrent_oversell_trial("IRO-HBH-00055", "TXDAL", on_hand=10, qty=1, attempts=40),
        _concurrent_oversell_trial("IRO-CBC-00454", "CALAX", on_hand=10, qty=2, attempts=30),
        _concurrent_oversell_trial("ACE-WGW-00583", "ILCHI", on_hand=7, qty=3, attempts=25),
    ]
    return {
        "trials": trials,
        "total_oversell_units": sum(t["oversell_units"] for t in trials),
        "all_ok": all(t["ok"] for t in trials),
    }


def run_inventory_bench() -> dict[str, Any]:
    ensure_seeded()
    atp = run_atp_scenarios()
    lifecycle = run_reservation_lifecycle()
    oversell = run_oversell_trials()
    # Re-seed so the DB is left in the pristine deterministic state.
    ensure_seeded()
    return {
        "atp_scenarios": atp,
        "reservation_lifecycle": lifecycle,
        "oversell": oversell,
    }
