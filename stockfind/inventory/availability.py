"""Multi-warehouse availability + available-to-promise (ATP).

ATP for a (SKU, warehouse) is ``on_hand - reserved`` and is never negative (the DB
``no_oversell`` check guarantees ``reserved <= on_hand``). The endpoint aggregates
across warehouses, selects the nearest warehouse that can actually promise stock,
and raises a backorder flag when nothing is available anywhere.
"""

from __future__ import annotations

import math
from typing import Any

from stockfind import db
from stockfind.catalog.seed import REGION_COORDS
from stockfind.errors import NotFoundError

_EARTH_RADIUS_KM = 6371.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return _EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_availability(sku: str, region: str | None = None) -> dict[str, Any]:
    product = db.fetch_one(
        "SELECT id, lead_time_days FROM products WHERE part_no = %s", (sku,)
    )
    if product is None:
        raise NotFoundError(f"Unknown SKU: {sku}")

    rows = db.fetch_all(
        """
        SELECT w.code, w.name, w.region, w.latitude, w.longitude,
               i.on_hand, i.reserved, (i.on_hand - i.reserved) AS atp
        FROM inventory i
        JOIN warehouses w ON w.code = i.warehouse_code
        WHERE i.product_id = %s
        """,
        (product["id"],),
    )

    origin = REGION_COORDS.get(region.upper()) if region else None
    warehouses: list[dict[str, Any]] = []
    for r in rows:
        distance = (
            round(_haversine_km(origin[0], origin[1], r["latitude"], r["longitude"]), 1)
            if origin
            else None
        )
        warehouses.append({
            "code": r["code"],
            "name": r["name"],
            "region": r["region"],
            "on_hand": r["on_hand"],
            "reserved": r["reserved"],
            "atp": r["atp"],
            "distance_km": distance,
        })

    # Order by distance when a region was supplied, else by warehouse code.
    if origin:
        warehouses.sort(key=lambda w: (w["distance_km"], w["code"]))
    else:
        warehouses.sort(key=lambda w: w["code"])

    available = [w for w in warehouses if w["atp"] > 0]
    if origin:
        nearest = available[0]["code"] if available else None
    else:
        # No region: "nearest" degrades to the warehouse with the most to promise.
        nearest = max(available, key=lambda w: w["atp"])["code"] if available else None

    total_on_hand = sum(w["on_hand"] for w in warehouses)
    total_reserved = sum(w["reserved"] for w in warehouses)
    total_atp = sum(w["atp"] for w in warehouses)

    return {
        "sku": sku,
        "total_on_hand": total_on_hand,
        "total_reserved": total_reserved,
        "total_atp": total_atp,
        "warehouses": warehouses,
        "nearest_available_warehouse": nearest,
        "lead_time_days": product["lead_time_days"],
        "backorder": total_atp <= 0,
    }
