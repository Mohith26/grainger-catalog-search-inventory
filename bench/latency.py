"""Latency benchmark for /search and /availability.

Measured **in-process via Starlette's TestClient (ASGI)** — this excludes the real
HTTP/TCP network socket and reflects the service's own per-request work (SQL,
FTS ranking, rapidfuzz blend, ATP aggregation). Stated plainly in RESULTS.md.
"""

from __future__ import annotations

import statistics
import time
from typing import Any

from bench.harness import ensure_seeded, make_client

SEARCH_QUERIES = [
    "stainless steel hex bolt", "480v circuit breaker", "nitrile work gloves",
    "grinding wheel", "ac motor 5 hp", "brass ball valve", "circut breaker",
    "adjustable wrench", "roller chain", "safety glasses",
]
AVAILABILITY_SKUS = [
    ("IRO-HBH-00055", "TX"), ("IRO-CBC-00454", "CA"), ("ACE-WGW-00583", "IL"),
    ("DUR-AMA-00743", "GA"), ("DUR-VV--00607", "NJ"),
]


def _percentiles(samples_ms: list[float]) -> dict[str, float]:
    ordered = sorted(samples_ms)
    return {
        "count": len(ordered),
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(_pct(ordered, 95), 3),
        "p99_ms": round(_pct(ordered, 99), 3),
        "mean_ms": round(statistics.fmean(ordered), 3),
        "max_ms": round(ordered[-1], 3),
    }


def _pct(ordered: list[float], pct: float) -> float:
    if not ordered:
        return 0.0
    rank = max(0, min(len(ordered) - 1, round(pct / 100 * len(ordered)) - 1))
    return ordered[rank]


def run_latency_bench(iterations: int = 300, warmup: int = 30) -> dict[str, Any]:
    ensure_seeded()
    client = make_client()

    search_ms: list[float] = []
    avail_ms: list[float] = []

    for i in range(iterations + warmup):
        q = SEARCH_QUERIES[i % len(SEARCH_QUERIES)]
        start = time.perf_counter()
        resp = client.get("/search", params={"q": q, "limit": 20})
        elapsed = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200, resp.text
        if i >= warmup:
            search_ms.append(elapsed)

        sku, region = AVAILABILITY_SKUS[i % len(AVAILABILITY_SKUS)]
        start = time.perf_counter()
        resp = client.get("/availability", params={"sku": sku, "region": region})
        elapsed = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200, resp.text
        if i >= warmup:
            avail_ms.append(elapsed)

    return {
        "methodology": "in-process ASGI TestClient (excludes network socket)",
        "iterations": iterations,
        "warmup_excluded": warmup,
        "search": _percentiles(search_ms),
        "availability": _percentiles(avail_ms),
    }
