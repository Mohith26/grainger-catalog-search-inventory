"""Pydantic request/response models — schema validation at every API boundary.

Constraints here (min/max, positive quantities, bounded page size) are what turn
malformed input into an automatic ``422`` instead of a downstream error.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ----------------------------- search -----------------------------

class ProductOut(BaseModel):
    id: int
    part_no: str
    name: str
    brand: str
    category: str
    subtype: str
    material: str
    price: float
    lead_time_days: int
    description: str
    attributes: dict[str, str]
    score: float | None = None


class FacetValue(BaseModel):
    value: str
    count: int


class SearchData(BaseModel):
    query: str
    results: list[ProductOut]
    facets: dict[str, list[FacetValue]]


# ----------------------------- availability -----------------------------

class WarehouseAvailability(BaseModel):
    code: str
    name: str
    region: str
    on_hand: int
    reserved: int
    atp: int  # available-to-promise = on_hand - reserved
    distance_km: float | None = None


class AvailabilityData(BaseModel):
    sku: str
    total_on_hand: int
    total_reserved: int
    total_atp: int
    warehouses: list[WarehouseAvailability]
    nearest_available_warehouse: str | None
    lead_time_days: int
    backorder: bool


# ----------------------------- reservations -----------------------------

class ReserveRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    warehouse_code: str = Field(min_length=1, max_length=16)
    quantity: int = Field(gt=0, le=100_000)


class ReserveData(BaseModel):
    reservation_id: int
    sku: str
    warehouse_code: str
    quantity: int
    remaining_atp: int


class ReleaseData(BaseModel):
    reservation_id: int
    status: str
    restored_atp: int


# ----------------------------- auth -----------------------------

class TokenRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    role: str = Field(pattern="^(buyer|admin)$")


class TokenData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    expires_in: int
