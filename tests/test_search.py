"""Search: keyword ranking, facets, fuzzy typo-tolerance (unit + integration)."""

from __future__ import annotations

import pytest

from stockfind.search.facets import FACET_DIMENSIONS, facet_counts
from stockfind.search.query import SearchFilters, fuzzy_score, search

# ------------------------------- unit -------------------------------

@pytest.mark.unit
def test_fuzzy_score_high_for_typo():
    # 'grindng wheel' should score high against the real product text.
    score = fuzzy_score("grindng wheel", "IronClad Aluminum Oxide Grinding Wheel 4 inch")
    assert score > 85


@pytest.mark.unit
def test_fuzzy_score_low_for_unrelated():
    score = fuzzy_score("circuit breaker", "Titan Stainless Steel Hex Bolt 1/4-20")
    assert score < 60


@pytest.mark.unit
def test_facet_counts_sorted_by_count_desc():
    rows = [
        {"category": "Fasteners", "brand": "Titan", "material": "Steel"},
        {"category": "Fasteners", "brand": "Titan", "material": "Steel"},
        {"category": "Electrical", "brand": "Voltec", "material": "Plastic"},
    ]
    facets = facet_counts(rows)
    assert set(facets.keys()) == set(FACET_DIMENSIONS)
    assert facets["category"][0] == {"value": "Fasteners", "count": 2}
    assert facets["brand"][0]["value"] == "Titan"


# ---------------------------- integration ----------------------------

@pytest.mark.integration
def test_keyword_search_ranks_correct_subtype_first():
    out = search("stainless steel hex bolt", limit=10)
    assert out.total > 0
    top = out.results[0]
    assert top["subtype"] == "Hex Bolt"
    assert top["material"] == "Stainless Steel"
    # Exact lexical + fuzzy match should be a strong score.
    assert top["score"] >= 0.9


@pytest.mark.integration
def test_search_returns_all_three_facet_dimensions_with_counts():
    out = search("hex bolt", limit=5)
    for dim in FACET_DIMENSIONS:
        assert dim in out.facets
    # Facet counts over the matched set should sum to the total matched.
    cat_total = sum(f["count"] for f in out.facets["category"])
    assert cat_total == out.total


@pytest.mark.integration
def test_typo_query_still_finds_relevant_products():
    clean = search("circuit breaker", limit=10)
    typo = search("circut braker", limit=10)
    assert typo.total > 0
    assert typo.results[0]["subtype"] == "Circuit Breaker"
    # Typo path should surface the same subtype the clean query does.
    assert clean.results[0]["subtype"] == typo.results[0]["subtype"]


@pytest.mark.integration
def test_facet_filter_narrows_results():
    unfiltered = search("hex bolt", limit=100)
    filtered = search(
        "hex bolt",
        filters=SearchFilters(material="Brass"),
        limit=100,
    )
    assert 0 < filtered.total < unfiltered.total
    assert all(r["material"] == "Brass" for r in filtered.results)


@pytest.mark.integration
def test_attribute_filter_is_exact():
    out = search(
        "circuit breaker",
        filters=SearchFilters(attrs=(("voltage", "480V"),)),
        limit=50,
    )
    assert out.total > 0
    assert all(r["attributes"].get("voltage") == "480V" for r in out.results)


@pytest.mark.integration
def test_exact_match_outranks_fuzzy_only_match():
    out = search("nitrile work gloves", limit=20)
    # First result is a real nitrile glove (lexical + fuzzy), scored above any
    # fuzzy-only tail entry.
    assert out.results[0]["subtype"] == "Work Gloves"
    assert out.results[0]["material"] == "Nitrile"
    assert out.results[0]["score"] >= out.results[-1]["score"]


@pytest.mark.integration
def test_empty_query_is_browse_mode():
    out = search("", filters=SearchFilters(category="Fasteners"), limit=10)
    assert out.total > 0
    assert all(r["category"] == "Fasteners" for r in out.results)
