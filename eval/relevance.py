"""Search relevance evaluation: precision@k, MRR, and fuzzy (typo) recall.

Ground truth is computed from the deterministic catalog by matching each query's
structured ``criteria`` (subtype / material / attributes). The search engine only
sees the free-text query, so this is a fair, non-circular measurement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from stockfind.catalog.seed import generate_products
from stockfind.search.query import search


def load_labeled_queries() -> dict[str, Any]:
    text = resources.files("eval").joinpath("labeled_queries.json").read_text()
    return json.loads(text)


def relevant_ids(products: list[dict[str, Any]], criteria: dict[str, Any]) -> set[int]:
    subtype = criteria.get("subtype")
    material = criteria.get("material")
    attrs = criteria.get("attributes", {})
    ids: set[int] = set()
    for p in products:
        if subtype is not None and p["subtype"] != subtype:
            continue
        if material is not None and p["material"] != material:
            continue
        if any(p["attributes"].get(k) != v for k, v in attrs.items()):
            continue
        ids.add(p["id"])
    return ids


def precision_at_k(ranked: list[int], relevant: set[int], k: int) -> float:
    if k == 0:
        return 0.0
    top = ranked[:k]
    hits = sum(1 for pid in top if pid in relevant)
    return hits / k


def reciprocal_rank(ranked: list[int], relevant: set[int]) -> float:
    for idx, pid in enumerate(ranked, start=1):
        if pid in relevant:
            return 1.0 / idx
    return 0.0


def recall_at_k(ranked: list[int], relevant: set[int], k: int) -> float:
    if not relevant:
        return 0.0
    top = set(ranked[:k])
    return len(top & relevant) / min(k, len(relevant))


@dataclass
class RelevanceReport:
    k_values: list[int]
    num_queries: int
    num_typo_queries: int
    precision_at_k: dict[int, float]
    mrr: float
    typo_precision_at_k: dict[int, float]
    typo_mrr: float
    typo_recall_at_k: dict[int, float]
    per_query: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "k_values": self.k_values,
            "num_queries": self.num_queries,
            "num_typo_queries": self.num_typo_queries,
            "precision_at_k": {str(k): round(v, 4) for k, v in self.precision_at_k.items()},
            "mrr": round(self.mrr, 4),
            "typo": {
                "num_queries": self.num_typo_queries,
                "precision_at_k": {
                    str(k): round(v, 4) for k, v in self.typo_precision_at_k.items()
                },
                "mrr": round(self.typo_mrr, 4),
                "recall_at_k": {
                    str(k): round(v, 4) for k, v in self.typo_recall_at_k.items()
                },
            },
            "per_query": self.per_query,
        }


def run_relevance_eval(max_k: int | None = None) -> RelevanceReport:
    spec = load_labeled_queries()
    k_values: list[int] = spec["k_values"]
    top_k = max_k or max(k_values)
    products = generate_products()

    clean_p: dict[int, list[float]] = {k: [] for k in k_values}
    clean_rr: list[float] = []
    typo_p: dict[int, list[float]] = {k: [] for k in k_values}
    typo_rr: list[float] = []
    typo_recall: dict[int, list[float]] = {k: [] for k in k_values}
    per_query: list[dict[str, Any]] = []

    for entry in spec["queries"]:
        relevant = relevant_ids(products, entry["criteria"])
        ranked = [r["id"] for r in search(entry["query"], limit=top_k).results]
        row: dict[str, Any] = {
            "id": entry["id"],
            "query": entry["query"],
            "num_relevant": len(relevant),
            "precision_at_k": {},
            "rr": round(reciprocal_rank(ranked, relevant), 4),
        }
        for k in k_values:
            p = precision_at_k(ranked, relevant, k)
            clean_p[k].append(p)
            row["precision_at_k"][str(k)] = round(p, 4)
        clean_rr.append(reciprocal_rank(ranked, relevant))

        if entry.get("typo"):
            t_ranked = [r["id"] for r in search(entry["typo"], limit=top_k).results]
            row["typo"] = entry["typo"]
            row["typo_precision_at_k"] = {}
            for k in k_values:
                tp = precision_at_k(t_ranked, relevant, k)
                typo_p[k].append(tp)
                typo_recall[k].append(recall_at_k(t_ranked, relevant, k))
                row["typo_precision_at_k"][str(k)] = round(tp, 4)
            typo_rr.append(reciprocal_rank(t_ranked, relevant))
            row["typo_rr"] = round(reciprocal_rank(t_ranked, relevant), 4)
        per_query.append(row)

    def _mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    num_typo = sum(1 for e in spec["queries"] if e.get("typo"))
    return RelevanceReport(
        k_values=k_values,
        num_queries=len(spec["queries"]),
        num_typo_queries=num_typo,
        precision_at_k={k: _mean(clean_p[k]) for k in k_values},
        mrr=_mean(clean_rr),
        typo_precision_at_k={k: _mean(typo_p[k]) for k in k_values},
        typo_mrr=_mean(typo_rr),
        typo_recall_at_k={k: _mean(typo_recall[k]) for k in k_values},
        per_query=per_query,
    )
