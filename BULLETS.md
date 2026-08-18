# Résumé Bullets — StockFind (filled strictly from measured results)

> Target: **Grainger — GTG Intern Software Engineer**. Measured 2026-08-17 against a live
> docker-compose **Postgres 16**, with **synthetic seeded** data (839 SKUs, 5 warehouses).
> Every number traces to `results/*.json`. Unmeasured values would be the literal `___`
> (there are none). Honesty tags below.

## Filled bullets

- Built a **B2B industrial-catalog search + multi-warehouse availability API**
  (FastAPI / **Postgres 16** full-text + rapidfuzz) returning **faceted, typo-tolerant**
  results at **precision@1 1.00 / MRR 1.00** (precision@5 0.94) on a 16-query labeled set
  and **p95 11.3 ms** on `/search`, with **available-to-promise correct across 40
  scenarios (0 oversell across 95 concurrent reserves)**.
  <br>_(all MEASURED: clean MRR 1.000, P@1 1.000, P@5 0.9375; typo-query MRR 1.000 /
  recall@10 1.00; ATP 40/40; 0 oversell. Synthetic seeded catalog; **latency measured
  in-process via FastAPI TestClient (ASGI), not over a network socket**.)_

- Shipped it **secure-by-design + observable** — JWT/role authz (buyer vs admin), pydantic
  schema validation, token-bucket rate limiting, and parameterized psycopg queries
  (SQL-injection-proof), plus structured JSON logs with request IDs, Prometheus `/metrics`
  (latency histogram + request counter), and `/health` + `/ready` — with a **5-check
  security suite all passing** (401 · 403 · 422 · 429 · SQLi-no-leak).
  <br>_(all MEASURED: 5/5 controls proven by `results/security.json`; injection left the
  products table at 839→839 rows.)_

- Wired **GitHub Actions CI/CD** (ruff lint + pytest + a **94% coverage** gate on every
  push, Postgres spun up as a service) and **containerized** the service (Dockerfile +
  one-command docker-compose), delivering across search, inventory, security, and
  observability with **49 passing tests**.
  <br>_(MEASURED: coverage 94.06% (728/774 stmts), 49 passed; the same CI steps — ruff →
  seed → pytest → coverage≥80 — were also run locally and pass.)_

## Measured-value ledger

| Placeholder | Value | Status |
|---|---|---|
| precision@1 / precision@5 | 1.000 / 0.9375 | MEASURED |
| MRR (clean) | 1.000 | MEASURED |
| typo MRR / recall@10 | 1.000 / 1.00 | MEASURED |
| /search p95 | 11.3 ms | MEASURED (in-process TestClient) |
| /availability p95 | 4.1 ms | MEASURED (in-process TestClient) |
| ATP scenarios (0 oversell) | 40 (0 oversell / 95 concurrent) | MEASURED |
| security controls proven | 5 / 5 | MEASURED |
| test coverage | 94.06% | MEASURED |
| passing tests | 49 | MEASURED |
| catalog / warehouses / stock rows | 839 / 5 / 4,195 | MEASURED |

## Honesty tags
- ✅ MEASURED against live docker Postgres 16; **synthetic seeded** data (fictional brands,
  computed prices).
- ⚠️ **Latency measured in-process** (FastAPI TestClient / ASGI) — excludes the network
  socket. The docker-compose gateway does serve over a real HTTP socket, but the reported
  p50/p95 are the in-process numbers.
- ⚠️ **precision@10 (0.856 clean)** dips only because 6 queries have < 10 relevant SKUs
  (denominator artifact) — precision@1 and MRR are 1.000. Stated plainly, not hidden.
- ⚠️ Search relevance is a Postgres-FTS + rapidfuzz blend with **fixed weights**, no
  learned ranking model.
- ❌ Not a real Grainger system, catalog, or deployment; no cloud deploy.
