"""Inventory routes: availability/ATP, reserve, release, admin reservation list."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from stockfind import db
from stockfind.envelope import ok
from stockfind.inventory.availability import get_availability
from stockfind.inventory.reserve import release, reserve
from stockfind.models import ReserveRequest
from stockfind.security.auth import Principal, get_principal, require_admin
from stockfind.security.ratelimit import rate_limited

router = APIRouter()


@router.get("/availability")
def availability_endpoint(
    sku: str = Query(..., min_length=1, max_length=64),
    region: str | None = Query(None, max_length=8),
):
    return ok(get_availability(sku, region))


@router.post(
    "/reserve",
    dependencies=[Depends(rate_limited("reserve_limiter"))],
    status_code=201,
)
def reserve_endpoint(
    payload: ReserveRequest,
    principal: Principal = Depends(get_principal),
):
    result = reserve(
        sku=payload.sku,
        warehouse_code=payload.warehouse_code,
        quantity=payload.quantity,
        buyer=principal.username,
    )
    return ok(result)


@router.delete("/reservations/{reservation_id}")
def release_endpoint(
    reservation_id: int,
    principal: Principal = Depends(get_principal),
):
    return ok(release(reservation_id))


@router.get("/admin/reservations")
def list_reservations(
    principal: Principal = Depends(require_admin),
    limit: int = Query(50, ge=1, le=500),
):
    rows = db.fetch_all(
        """
        SELECT r.id, r.product_id, p.part_no, r.warehouse_code, r.quantity,
               r.buyer, r.status, r.created_at
        FROM reservations r
        JOIN products p ON p.id = r.product_id
        ORDER BY r.id DESC
        LIMIT %s
        """,
        (limit,),
    )
    for row in rows:
        row["created_at"] = row["created_at"].isoformat()
    return ok(rows)
