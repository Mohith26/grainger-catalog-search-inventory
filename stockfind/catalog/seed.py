"""Deterministic synthetic industrial-catalog generator + database seeder.

The catalog is 100% synthetic (fictional brands, computed prices) but modelled on
real MRO / industrial-distribution product families so that keyword, faceted, and
typo-tolerant search have something meaningful to rank. Everything is a pure
function of ``seed`` — the same seed always yields byte-identical rows, which is
what lets the relevance eval define ground truth independently of the search
engine.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from typing import Any

# Fictional brands — deliberately NOT real trademarks.
BRANDS = [
    "Titan", "IronClad", "Voltec", "GripPro", "SafeGuard",
    "FlowMaster", "DuraDrive", "MaxForce", "ProLine", "AceGrip",
]


@dataclass(frozen=True)
class Warehouse:
    code: str
    name: str
    region: str
    latitude: float
    longitude: float


# Five US distribution centers with real-ish coordinates (nearest-warehouse math).
WAREHOUSES: tuple[Warehouse, ...] = (
    Warehouse("ILCHI", "Chicago DC", "IL", 41.8500, -87.6500),
    Warehouse("TXDAL", "Dallas DC", "TX", 32.7800, -96.8000),
    Warehouse("CALAX", "Los Angeles DC", "CA", 34.0500, -118.2400),
    Warehouse("GAATL", "Atlanta DC", "GA", 33.7500, -84.3900),
    Warehouse("NJEWR", "Newark DC", "NJ", 40.7300, -74.1700),
)

# Region centroids a buyer may pass to /availability?region=. Superset of DC states.
REGION_COORDS: dict[str, tuple[float, float]] = {
    "IL": (41.85, -87.65), "TX": (32.78, -96.80), "CA": (34.05, -118.24),
    "GA": (33.75, -84.39), "NJ": (40.73, -74.17), "NY": (40.71, -74.01),
    "FL": (27.99, -81.76), "WA": (47.61, -122.33), "CO": (39.74, -104.99),
    "OH": (39.96, -82.99), "MA": (42.36, -71.06), "AZ": (33.45, -112.07),
    "PA": (40.44, -79.99), "MI": (42.33, -83.05), "NC": (35.23, -80.84),
}


@dataclass(frozen=True)
class SubtypeSpec:
    category: str
    subtype: str
    materials: list[str]
    brands: list[str]
    # Ordered attribute axes; the first is used as the headline attribute in names.
    attrs: dict[str, list[str]]
    lead_time_days: int
    price_range: tuple[int, int]  # in dollars, before cents conversion


SUBTYPE_SPECS: list[SubtypeSpec] = [
    # --- Fasteners ---
    SubtypeSpec("Fasteners", "Hex Bolt",
                ["Stainless Steel", "Zinc-Plated Steel", "Brass"],
                ["Titan", "IronClad", "MaxForce", "ProLine"],
                {"thread_size": ['1/4"-20', '3/8"-16', '1/2"-13', "M6", "M8", "M10"],
                 "length": ['1"', '2"', '3"']},
                2, (3, 25)),
    SubtypeSpec("Fasteners", "Socket Cap Screw",
                ["Stainless Steel", "Alloy Steel"],
                ["Titan", "IronClad", "MaxForce"],
                {"thread_size": ["M4", "M5", "M6", "M8", "M10"],
                 "length": ["10mm", "20mm", "30mm"]},
                2, (4, 30)),
    SubtypeSpec("Fasteners", "Hex Nut",
                ["Stainless Steel", "Zinc-Plated Steel", "Brass"],
                ["Titan", "IronClad", "ProLine"],
                {"thread_size": ['1/4"-20', '3/8"-16', '1/2"-13', "M6", "M8", "M10"]},
                1, (2, 12)),
    SubtypeSpec("Fasteners", "Flat Washer",
                ["Stainless Steel", "Zinc-Plated Steel"],
                ["Titan", "MaxForce", "ProLine"],
                {"size": ['1/4"', '3/8"', '1/2"', "M6", "M8"]},
                1, (1, 8)),
    # --- Electrical ---
    SubtypeSpec("Electrical", "Circuit Breaker",
                ["Thermoplastic"],
                ["Voltec", "IronClad", "ProLine"],
                {"voltage": ["120V", "240V", "480V"],
                 "amperage": ["15A", "20A", "30A", "50A"],
                 "poles": ["1-Pole", "2-Pole", "3-Pole"]},
                3, (12, 120)),
    SubtypeSpec("Electrical", "Contactor",
                ["Thermoplastic"],
                ["Voltec", "DuraDrive", "ProLine"],
                {"voltage": ["120V", "240V", "480V"],
                 "amperage": ["25A", "40A", "60A"]},
                4, (30, 220)),
    SubtypeSpec("Electrical", "Fuse",
                ["Ceramic"],
                ["Voltec", "SafeGuard", "ProLine"],
                {"voltage": ["250V", "600V"],
                 "amperage": ["5A", "10A", "20A", "30A"]},
                2, (2, 18)),
    # --- Safety ---
    SubtypeSpec("Safety", "Safety Glasses",
                ["Polycarbonate"],
                ["SafeGuard", "GripPro", "ProLine"],
                {"tint": ["Clear", "Gray", "Amber"], "rating": ["ANSI Z87.1"]},
                1, (3, 20)),
    SubtypeSpec("Safety", "Work Gloves",
                ["Nitrile", "Leather", "Latex"],
                ["SafeGuard", "GripPro", "AceGrip"],
                {"size": ["S", "M", "L", "XL"]},
                1, (4, 28)),
    SubtypeSpec("Safety", "Hard Hat",
                ["HDPE"],
                ["SafeGuard", "GripPro"],
                {"color": ["White", "Yellow", "Blue"], "class": ["Type I", "Type II"]},
                2, (12, 45)),
    # --- Power Transmission ---
    SubtypeSpec("Power Transmission", "V-Belt",
                ["Rubber"],
                ["DuraDrive", "FlowMaster", "MaxForce"],
                {"series": ["A", "B", "C"], "length": ['30"', '40"', '50"', '60"']},
                3, (8, 60)),
    SubtypeSpec("Power Transmission", "Roller Chain",
                ["Carbon Steel"],
                ["DuraDrive", "MaxForce"],
                {"pitch": ["#40", "#50", "#60"]},
                4, (20, 90)),
    SubtypeSpec("Power Transmission", "Ball Bearing",
                ["Chrome Steel"],
                ["DuraDrive", "FlowMaster"],
                {"bore": ["10mm", "15mm", "20mm", "25mm"]},
                3, (10, 75)),
    # --- Hand Tools ---
    SubtypeSpec("Hand Tools", "Adjustable Wrench",
                ["Chrome Vanadium"],
                ["GripPro", "MaxForce", "Titan"],
                {"size": ['6"', '8"', '10"', '12"']},
                1, (10, 45)),
    SubtypeSpec("Hand Tools", "Screwdriver",
                ["Chrome Vanadium"],
                ["GripPro", "AceGrip", "Titan"],
                {"drive": ["Phillips #1", "Phillips #2", 'Slotted 1/4"', "Torx T20"]},
                1, (5, 22)),
    SubtypeSpec("Hand Tools", "Pliers",
                ["Steel"],
                ["GripPro", "AceGrip"],
                {"style": ["Needle-Nose", "Lineman", "Slip-Joint"]},
                1, (8, 35)),
    # --- Abrasives ---
    SubtypeSpec("Abrasives", "Grinding Wheel",
                ["Aluminum Oxide"],
                ["MaxForce", "IronClad", "ProLine"],
                {"diameter": ['4"', '4.5"', '6"', '7"'], "grit": ["24", "36", "60"]},
                2, (4, 30)),
    SubtypeSpec("Abrasives", "Cutoff Wheel",
                ["Aluminum Oxide"],
                ["MaxForce", "IronClad"],
                {"diameter": ['4"', '4.5"', '6"'], "thickness": ['0.045"', '1/8"']},
                2, (3, 20)),
    # --- Motors ---
    SubtypeSpec("Motors", "AC Motor",
                ["Cast Iron"],
                ["DuraDrive", "Voltec"],
                {"horsepower": ["1 HP", "2 HP", "5 HP"],
                 "voltage": ["230V", "460V"],
                 "rpm": ["1750 RPM", "3450 RPM"]},
                14, (120, 850)),
    # --- Pneumatics ---
    SubtypeSpec("Pneumatics", "Air Filter Regulator",
                ["Aluminum"],
                ["FlowMaster", "Voltec"],
                {"port": ['1/4" NPT', '3/8" NPT', '1/2" NPT']},
                3, (18, 95)),
    SubtypeSpec("Pneumatics", "Push-to-Connect Fitting",
                ["Brass", "Nylon"],
                ["FlowMaster", "ProLine"],
                {"port": ['1/4"', '3/8"', '1/2"']},
                2, (2, 14)),
    # --- Plumbing ---
    SubtypeSpec("Plumbing", "Ball Valve",
                ["Brass", "PVC", "Stainless Steel"],
                ["FlowMaster", "ProLine", "IronClad"],
                {"size": ['1/2"', '3/4"', '1"']},
                3, (6, 55)),
    SubtypeSpec("Plumbing", "Pipe Elbow",
                ["PVC", "Copper", "Brass"],
                ["FlowMaster", "ProLine"],
                {"size": ['1/2"', '3/4"', '1"'], "angle": ["90 degree", "45 degree"]},
                2, (1, 18)),
]


def _iter_attr_combos(attrs: dict[str, list[str]]) -> list[dict[str, str]]:
    """Cartesian product of the attribute axes, preserving axis order."""
    combos: list[dict[str, str]] = [{}]
    for axis, values in attrs.items():
        combos = [{**c, axis: v} for c in combos for v in values]
    return combos


def _price_cents(part_no: str, low: int, high: int) -> int:
    """Deterministic price in [low, high] dollars derived from the part number."""
    h = int(hashlib.sha256(part_no.encode()).hexdigest(), 16)
    span = (high - low) * 100 + 1
    return low * 100 + (h % span)


def _subtype_code(subtype: str) -> str:
    letters = "".join(w[0] for w in subtype.split())
    return (letters + subtype.replace(" ", ""))[:3].upper()


@dataclass
class GeneratedCatalog:
    warehouses: list[dict[str, Any]]
    products: list[dict[str, Any]]
    inventory: list[dict[str, Any]] = field(default_factory=list)


def generate_products(seed: int = 42) -> list[dict[str, Any]]:
    """Return the full deterministic product list (no DB required)."""
    products: list[dict[str, Any]] = []
    seq = 0
    for spec in SUBTYPE_SPECS:
        combos = _iter_attr_combos(spec.attrs)
        headline_axis = next(iter(spec.attrs))
        for brand in spec.brands:
            for material in spec.materials:
                for combo in combos:
                    seq += 1
                    brand_code = brand[:3].upper()
                    part_no = f"{brand_code}-{_subtype_code(spec.subtype)}-{seq:05d}"
                    headline = combo[headline_axis]
                    name = f"{brand} {material} {spec.subtype} {headline}".strip()
                    attr_text = " ".join(combo.values())
                    desc_attrs = ", ".join(
                        f"{k.replace('_', ' ')} {v}" for k, v in combo.items()
                    )
                    description = (
                        f"{material} {spec.subtype.lower()} for industrial MRO use. "
                        f"{desc_attrs}. {spec.category} grade, {brand} quality."
                    )
                    products.append({
                        "id": seq,
                        "part_no": part_no,
                        "name": name,
                        "brand": brand,
                        "category": spec.category,
                        "subtype": spec.subtype,
                        "material": material,
                        "price_cents": _price_cents(part_no, *spec.price_range),
                        "lead_time_days": spec.lead_time_days,
                        "description": description,
                        "attributes": combo,
                        "attr_text": attr_text,
                    })
    return products


def generate_inventory(products: list[dict[str, Any]], seed: int = 42) -> list[dict[str, Any]]:
    """Per-(product, warehouse) on-hand stock. Some rows are deliberately 0 to
    exercise nearest-warehouse fallback and the backorder flag."""
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    for p in products:
        for wh in WAREHOUSES:
            # ~12% of (SKU, warehouse) cells are out of stock.
            on_hand = 0 if rng.random() < 0.12 else rng.randint(1, 500)
            rows.append({
                "product_id": p["id"],
                "warehouse_code": wh.code,
                "on_hand": on_hand,
                "reserved": 0,
            })
    return rows


def generate_catalog(seed: int = 42) -> GeneratedCatalog:
    products = generate_products(seed)
    inventory = generate_inventory(products, seed)
    warehouses = [
        {"code": w.code, "name": w.name, "region": w.region,
         "latitude": w.latitude, "longitude": w.longitude}
        for w in WAREHOUSES
    ]
    return GeneratedCatalog(warehouses=warehouses, products=products, inventory=inventory)


def seed_database(seed: int = 42) -> dict[str, int]:
    """Reset the schema and load the deterministic catalog. Returns row counts."""
    from stockfind import db

    db.reset_schema()
    catalog = generate_catalog(seed)
    pool = db.get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO warehouses (code, name, region, latitude, longitude) "
                "VALUES (%(code)s, %(name)s, %(region)s, %(latitude)s, %(longitude)s)",
                catalog.warehouses,
            )
            product_rows = [
                {**p, "attributes": json.dumps(p["attributes"])}
                for p in catalog.products
            ]
            cur.executemany(
                "INSERT INTO products (id, part_no, name, brand, category, subtype, "
                "material, price_cents, lead_time_days, description, attributes, attr_text) "
                "VALUES (%(id)s, %(part_no)s, %(name)s, %(brand)s, %(category)s, %(subtype)s, "
                "%(material)s, %(price_cents)s, %(lead_time_days)s, %(description)s, "
                "%(attributes)s::jsonb, %(attr_text)s)",
                product_rows,
            )
            cur.executemany(
                "INSERT INTO inventory (product_id, warehouse_code, on_hand, reserved) "
                "VALUES (%(product_id)s, %(warehouse_code)s, %(on_hand)s, %(reserved)s)",
                catalog.inventory,
            )
        conn.commit()
    return {
        "warehouses": len(catalog.warehouses),
        "products": len(catalog.products),
        "inventory_rows": len(catalog.inventory),
    }


def main() -> None:
    """CLI: seed the database configured by the environment.

    Usage: ``python -m stockfind.catalog.seed``
    """
    from stockfind import db
    from stockfind.config import get_settings

    settings = get_settings()
    db.init_pool(settings.pg_dsn)
    counts = seed_database(settings.seed)
    print(json.dumps({"seeded": counts, "seed": settings.seed}))
    db.close_pool()


if __name__ == "__main__":
    main()
