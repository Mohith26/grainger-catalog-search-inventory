"""Facet aggregation over a result set.

Facets are counted in Python over the matched candidate rows (pre-pagination), so
the counts a buyer sees always describe the actual result set they can drill into.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

FACET_DIMENSIONS: tuple[str, ...] = ("category", "brand", "material")


def facet_counts(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    facets: dict[str, list[dict[str, Any]]] = {}
    for dim in FACET_DIMENSIONS:
        counter = Counter(row[dim] for row in rows)
        # Sort by count desc, then value asc for deterministic output.
        ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        facets[dim] = [{"value": value, "count": count} for value, count in ordered]
    return facets
