"""Relevance harness sanity: ground-truth math + eval produces plausible metrics."""

from __future__ import annotations

import pytest

from eval.relevance import (
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    relevant_ids,
    run_relevance_eval,
)
from stockfind.catalog.seed import generate_products


@pytest.mark.unit
def test_precision_and_rr_math():
    ranked = [10, 20, 30, 40]
    relevant = {20, 40}
    assert precision_at_k(ranked, relevant, 2) == 0.5
    assert reciprocal_rank(ranked, relevant) == 0.5
    assert recall_at_k(ranked, relevant, 4) == 1.0


@pytest.mark.unit
def test_relevant_ids_filters_by_criteria():
    products = generate_products()
    ids = relevant_ids(products, {"subtype": "Hex Bolt", "material": "Stainless Steel"})
    assert ids
    by_id = {p["id"]: p for p in products}
    assert all(
        by_id[i]["subtype"] == "Hex Bolt" and by_id[i]["material"] == "Stainless Steel"
        for i in ids
    )


@pytest.mark.integration
def test_relevance_eval_reports_strong_metrics():
    report = run_relevance_eval()
    d = report.to_dict()
    assert d["num_queries"] >= 15
    # Every labeled query's first relevant hit is near the top -> high MRR.
    assert d["mrr"] >= 0.8
    assert d["precision_at_k"]["1"] >= 0.8
    # Typo-tolerance recovers relevant results despite misspellings.
    assert d["typo"]["mrr"] >= 0.8
    assert d["typo"]["recall_at_k"]["10"] >= 0.7
