"""Catalog routes: keyword/faceted/typo-tolerant search + product detail."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from stockfind import db
from stockfind.envelope import PageMeta, ok
from stockfind.search.query import SearchFilters, search
from stockfind.security.ratelimit import rate_limited

HTTP_422 = 422  # version-agnostic (Starlette renamed the 422 constant)

router = APIRouter()


def _parse_attrs(attr: list[str] | None) -> tuple[tuple[str, str], ...]:
    if not attr:
        return ()
    parsed: list[tuple[str, str]] = []
    for item in attr:
        key, sep, value = item.partition(":")
        if not sep or not key.strip() or not value.strip():
            raise HTTPException(
                status_code=HTTP_422,
                detail=f"Malformed attribute filter '{item}'; expected 'key:value'.",
            )
        parsed.append((key.strip(), value.strip()))
    return tuple(parsed)


@router.get("/search", dependencies=[Depends(rate_limited("search_limiter"))])
def search_endpoint(
    q: str = Query("", max_length=200, description="Free-text query"),
    category: str | None = Query(None, max_length=64),
    brand: str | None = Query(None, max_length=64),
    material: str | None = Query(None, max_length=64),
    attr: list[str] | None = Query(None, description="Attribute filter 'key:value'"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    filters = SearchFilters(
        category=category, brand=brand, material=material, attrs=_parse_attrs(attr)
    )
    outcome = search(q, filters=filters, limit=limit, offset=offset)
    data = {
        "query": outcome.query,
        "results": outcome.results,
        "facets": outcome.facets,
    }
    meta = PageMeta(
        total=outcome.total, limit=limit, offset=offset, returned=len(outcome.results)
    )
    return ok(data, meta)


@router.get("/products/{product_id}")
def product_detail(product_id: int):
    row = db.fetch_one(
        """
        SELECT id, part_no, name, brand, category, subtype, material,
               price_cents, lead_time_days, description, attributes
        FROM products WHERE id = %s
        """,
        (product_id,),
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product {product_id} not found",
        )
    product = {
        "id": row["id"],
        "part_no": row["part_no"],
        "name": row["name"],
        "brand": row["brand"],
        "category": row["category"],
        "subtype": row["subtype"],
        "material": row["material"],
        "price": round(row["price_cents"] / 100, 2),
        "lead_time_days": row["lead_time_days"],
        "description": row["description"],
        "attributes": row["attributes"],
        "score": None,
    }
    return ok(product)
