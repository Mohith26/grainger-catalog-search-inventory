"""Run every measurement and write results/*.json + a summary.

Usage: ``python -m bench.run_all``  (Postgres must be up and reachable).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bench.harness import ensure_seeded
from bench.inventory_scenarios import run_inventory_bench
from bench.latency import run_latency_bench
from bench.security_checks import run_security_checks
from eval.relevance import run_relevance_eval

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


def _write(name: str, payload: dict[str, Any]) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / name).write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote results/{name}")


def main() -> None:
    counts = ensure_seeded()
    now = datetime.now(UTC).isoformat()

    scale = {
        "measured_at": now,
        "synthetic": True,
        "seed": 42,
        **counts,
        "warehouse_codes": ["ILCHI", "TXDAL", "CALAX", "GAATL", "NJEWR"],
    }
    _write("scale.json", scale)

    relevance = run_relevance_eval().to_dict()
    relevance["measured_at"] = now
    _write("relevance.json", relevance)

    inventory = run_inventory_bench()
    inventory["measured_at"] = now
    _write("inventory.json", inventory)

    security = run_security_checks()
    security["measured_at"] = now
    _write("security.json", security)

    latency = run_latency_bench()
    latency["measured_at"] = now
    _write("latency.json", latency)

    summary = {
        "measured_at": now,
        "catalog": {"products": counts["products"], "warehouses": counts["warehouses"],
                    "inventory_rows": counts["inventory_rows"]},
        "relevance": {
            "num_queries": relevance["num_queries"],
            "precision_at_k": relevance["precision_at_k"],
            "mrr": relevance["mrr"],
            "typo": relevance["typo"],
        },
        "inventory": {
            "atp_accuracy": inventory["atp_scenarios"]["accuracy"],
            "atp_scenarios": inventory["atp_scenarios"]["total"],
            "reservation_lifecycle_ok": inventory["reservation_lifecycle"]["all_correct"],
            "oversell_units": inventory["oversell"]["total_oversell_units"],
            "oversell_all_ok": inventory["oversell"]["all_ok"],
        },
        "security": {
            "controls_total": security["controls_total"],
            "controls_passed": security["controls_passed"],
            "all_passed": security["all_passed"],
        },
        "latency": {
            "search_p50_ms": latency["search"]["p50_ms"],
            "search_p95_ms": latency["search"]["p95_ms"],
            "availability_p50_ms": latency["availability"]["p50_ms"],
            "availability_p95_ms": latency["availability"]["p95_ms"],
            "methodology": latency["methodology"],
        },
    }
    _write("summary.json", summary)
    print("\nSUMMARY:\n" + json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
