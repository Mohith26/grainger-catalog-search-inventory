"""Catalog search: Postgres full-text lexical ranking blended with rapidfuzz
typo-tolerance, plus faceted filtering.

Pipeline per query:
  1. Apply facet filters (category / brand / attribute) as **parameterized** SQL.
  2. Lexical pass — Postgres ``websearch_to_tsquery`` + ``ts_rank`` over a weighted
     ``tsvector`` (name > brand/part# > category/subtype/material/attrs > description).
  3. Typo-tolerant pass — rapidfuzz score of the raw query against each candidate's
     searchable text (catches misspellings the lexical index can't match).
  4. Blend: ``score = W_LEX * norm(ts_rank) + W_FUZZY * (fuzzy / 100)``.
  5. Facet counts over the matched set; bounded pagination.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from stockfind import db
from stockfind.config import get_settings
from stockfind.search.facets import facet_counts

_CORPUS_SQL = """
    SELECT p.id, p.part_no, p.name, p.brand, p.category, p.subtype, p.material,
           p.price_cents, p.lead_time_days, p.description, p.attributes, p.attr_text,
           ts_rank(p.search_vector, q) AS lex_rank,
           (p.search_vector @@ q) AS lex_match
    FROM products p, websearch_to_tsquery('english', %s) AS q
    WHERE TRUE
"""


@dataclass(frozen=True)
class SearchFilters:
    category: str | None = None
    brand: str | None = None
    material: str | None = None
    attrs: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SearchOutcome:
    query: str
    total: int
    results: list[dict[str, Any]]
    facets: dict[str, list[dict[str, Any]]]


def _searchable_text(row: dict[str, Any]) -> str:
    return " ".join((
        row["name"], row["brand"], row["category"],
        row["subtype"], row["material"], row["attr_text"], row["part_no"],
    ))


def fuzzy_score(query: str, text: str) -> float:
    """0-100 typo-tolerant similarity of a short query against product text.

    Each query token is matched to its **best** token in the product text
    (``fuzz.ratio``) and the per-token scores are averaged. Matching token-by-token
    (rather than whole-string) is what lets a misspelling like "grindng wheel" still
    score high against "... Grinding Wheel ...": ``grindng``≈``grinding`` (~93) and
    ``wheel``==``wheel`` (100) average to ~96, while a query needs *most* of its
    tokens to match for a high overall score.
    """
    q_tokens = query.lower().split()
    t_tokens = set(text.lower().split())
    if not q_tokens or not t_tokens:
        return 0.0
    total = 0.0
    for qt in q_tokens:
        total += max(fuzz.ratio(qt, tt) for tt in t_tokens)
    return total / len(q_tokens)


def _build_filter_sql(filters: SearchFilters) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if filters.category:
        clauses.append("p.category = %s")
        params.append(filters.category)
    if filters.brand:
        clauses.append("p.brand = %s")
        params.append(filters.brand)
    if filters.material:
        clauses.append("p.material = %s")
        params.append(filters.material)
    for key, value in filters.attrs:
        clauses.append("p.attributes @> %s::jsonb")
        params.append(json.dumps({key: value}))
    sql = "".join(f" AND {clause}" for clause in clauses)
    return sql, params


def _row_to_product(row: dict[str, Any], score: float | None) -> dict[str, Any]:
    return {
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
        "score": round(score, 4) if score is not None else None,
    }


def search(
    query: str,
    filters: SearchFilters | None = None,
    limit: int = 20,
    offset: int = 0,
) -> SearchOutcome:
    settings = get_settings()
    filters = filters or SearchFilters()
    filter_sql, filter_params = _build_filter_sql(filters)

    # Fetch the facet-filtered corpus once (with a per-row lexical rank).
    sql = _CORPUS_SQL + filter_sql
    rows = db.fetch_all(sql, (query, *filter_params))

    query = query.strip()
    if not query:
        # Browse mode: no text query -> return the filtered set ordered by part number.
        ordered = sorted(rows, key=lambda r: r["part_no"])
        facets = facet_counts(ordered)
        page = ordered[offset:offset + limit]
        return SearchOutcome(
            query="",
            total=len(ordered),
            results=[_row_to_product(r, None) for r in page],
            facets=facets,
        )

    max_rank = max((r["lex_rank"] for r in rows), default=0.0) or 1.0
    w_lex = settings.rank_weight_lexical
    w_fuzzy = settings.rank_weight_fuzzy

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        fuzzy = fuzzy_score(query, _searchable_text(row))
        if not row["lex_match"] and fuzzy < settings.fuzzy_min_score:
            continue  # neither a lexical hit nor a plausible typo match
        lex_norm = (row["lex_rank"] / max_rank) if row["lex_match"] else 0.0
        score = w_lex * lex_norm + w_fuzzy * (fuzzy / 100.0)
        scored.append((score, row))

    # Sort by score desc, tiebreak on part_no for determinism.
    scored.sort(key=lambda sr: (-sr[0], sr[1]["part_no"]))
    matched_rows = [row for _, row in scored]
    facets = facet_counts(matched_rows)

    page = scored[offset:offset + limit]
    results = [_row_to_product(row, score) for score, row in page]
    return SearchOutcome(query=query, total=len(scored), results=results, facets=facets)
