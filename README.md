# StockFind — Industrial Catalog Search + Multi-Warehouse Inventory Availability

A **B2B industrial-catalog product-search + real-time multi-warehouse inventory /
available-to-promise (ATP) API** — faceted, typo-tolerant search over MRO/industrial
SKUs plus a live per-warehouse availability check with reserve/release — built with the
**engineering envelope Grainger's GTG JD foregrounds**: automated tests, **CI/CD (GitHub
Actions)**, **observability** (structured logs + Prometheus metrics + health/readiness),
and **secure-by-design** (schema validation, JWT/role authz, rate limiting, parameterized
queries). Benchmarked for search relevance, ATP correctness, zero oversell, and latency.

> Built for a **Grainger Technology Group (GTG) Intern SWE** target. Catalog **search**
> ("find the right part fast") + **inventory availability** ("know if/where it's in
> stock") is the literal core of industrial-distribution digital commerce — and this
> repo makes the JD's practices (Agile-sized modules, tests, CI, observability,
> secure-by-design) first-class and **measurable**.

> ### Data & measurement notes (read me)
> - **100% synthetic, seeded** catalog (`stockfind/catalog/seed.py`, `seed=42`). Fictional
>   brands, computed prices — not real Grainger data.
> - **Latency is measured in-process** (FastAPI `TestClient` / ASGI), not over a network
>   socket. Full methodology + every measured number: **[RESULTS.md](RESULTS.md)**.

## What it does

| Capability | Detail |
|---|---|
| **Search** | Postgres full-text (`tsvector` + `ts_rank`, GIN) for lexical relevance, blended with **rapidfuzz** per-token fuzzy scoring for **typo tolerance**; **faceted** filters (category / brand / material / attribute); bounded pagination. |
| **Availability / ATP** | Per-warehouse `on_hand` + **ATP = on_hand − reserved**; **nearest-warehouse** by haversine distance from a region; lead-time / **backorder** flag. |
| **Reserve / release** | `SELECT ... FOR UPDATE` row-locking so concurrent reservations **can never oversell**; a DB `CHECK (reserved <= on_hand)` backstop. |
| **Secure-by-design** | pydantic schema validation (→422), JWT + roles buyer/admin (→401/403), token-bucket rate limiting (→429), parameterized psycopg SQL (SQLi-safe). |
| **Observability** | structlog JSON logs with a bound `request_id`; Prometheus `/metrics` (latency histogram + request counter); `/health` + `/ready`. |

## Architecture

```
                        ┌───────────────────────────────────────────────┐
   HTTP request         │            StockFind gateway (FastAPI)         │
   ───────────────────▶ │  middleware  request-id + JSON access log      │
                        │              Prometheus metrics (hist+counter)  │
                        │  security    JWT/role authz · token-bucket RL   │
                        │  search      Postgres FTS (ts_rank) ⊕ rapidfuzz │
                        │  inventory   ATP · nearest-DC · reserve(FOR UPD)│
                        │  envelope    {success,data,error,meta} + paging │
                        └───────────────────────┬───────────────────────┘
                                                │ psycopg 3 (parameterized)
                                        ┌───────▼────────┐
                                        │  Postgres 16   │
                                        │  products (GIN tsvector)
                                        │  warehouses · inventory · reservations
                                        └────────────────┘
```

## Tech stack
Python 3.12 · **FastAPI** + uvicorn · **Postgres 16** (full-text search) · **psycopg 3** +
pool · **rapidfuzz** · pydantic / pydantic-settings · **PyJWT** · token-bucket rate limiter ·
**prometheus-client** · **structlog** · pytest + coverage · **ruff** · **GitHub Actions** ·
Docker + docker-compose. Free/local, CPU-only, no external API keys.

## Layout
```
stockfind/
  config.py            env-driven settings (DSN, JWT secret, rate limits, seed)
  db.py                psycopg connection pool + schema loader (parameterized helpers)
  envelope.py          consistent {success,data,error,meta} + pagination meta
  models.py            pydantic request/response models (validation at the boundary)
  errors.py            domain errors -> HTTP status
  catalog/
    schema.sql         DDL: GIN tsvector, inventory no-oversell CHECK, reservations
    seed.py            deterministic synthetic industrial-SKU generator (seed=42)
  search/
    query.py           FTS lexical + rapidfuzz typo blend + facet filters
    facets.py          facet aggregation (category / brand / material)
  inventory/
    availability.py    per-warehouse ATP + nearest-warehouse + backorder
    reserve.py         reserve / release with SELECT ... FOR UPDATE (0 oversell)
  security/
    auth.py            JWT issue/verify + buyer/admin role dependencies
    ratelimit.py       in-process token-bucket limiter (per IP + route)
  observability/
    logging.py         structlog JSON + request-id middleware
    metrics.py         per-app Prometheus registry + middleware
  api/
    app.py             application factory: middleware, error envelope, routers
    routes_catalog.py  /search, /products/{id}
    routes_inventory.py /availability, /reserve, /reservations/{id}, /admin/reservations
    routes_meta.py     /auth/token, /health, /ready, /metrics
eval/
  labeled_queries.json 16 labeled queries (10 with typo variants), attribute ground truth
  relevance.py         precision@k / MRR / fuzzy recall harness
bench/
  latency.py           /search + /availability p50/p95 (in-process TestClient)
  inventory_scenarios.py  ATP correctness + concurrent 0-oversell
  security_checks.py   the 5 security controls -> results/security.json
  run_all.py           run everything -> results/*.json + summary.json
tests/                 49 tests (search / ATP / concurrency / security / observability / api)
results/*.json         committed measured numbers (2026-08-17)
.github/workflows/ci.yml   Postgres service -> ruff -> seed -> pytest -> coverage gate
```

## Quickstart

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

docker compose up -d db                 # Postgres 16 on host port 5470
export STOCKFIND_PG_DSN="postgresql://stockfind:stockfind@localhost:5470/stockfind"
export STOCKFIND_JWT_SECRET="local-secret-at-least-32-bytes-long-xx"

python -m stockfind.catalog.seed        # 839 SKUs · 5 warehouses · 4,195 stock rows
pytest                                  # 49 passed, 94% coverage
python -m bench.run_all                 # (re)generate results/*.json
```

### One-command full stack (Postgres + gateway)
```bash
docker compose up -d --build            # gateway seeds the catalog on boot
curl -s localhost:8055/health
open http://localhost:8055/docs         # OpenAPI UI
```

### API

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /search?q=&category=&brand=&material=&attr=k:v&limit=&offset=` | public | faceted, typo-tolerant search |
| `GET /products/{id}` | public | product detail |
| `GET /availability?sku=&region=` | public | per-warehouse ATP + nearest DC + backorder |
| `POST /reserve` | buyer/admin | reserve stock (FOR UPDATE, no oversell) |
| `DELETE /reservations/{id}` | buyer/admin | release a reservation |
| `GET /admin/reservations` | **admin** | list reservations (role-gated) |
| `POST /auth/token` | public | mint a demo JWT for a username + role |
| `GET /health` · `/ready` · `/metrics` | public | liveness · DB readiness · Prometheus |

```bash
# typo-tolerant search returns the right parts:
curl -s "localhost:8055/search?q=staineless%20steel%20hex%20bolt&limit=3"

# adversarial reach-arounds are refused / inert:
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8055/reserve \
  -d '{"sku":"IRO-HBH-00055","warehouse_code":"TXDAL","quantity":1}'  # -> 401 (no token)
```

## Measured results (2026-08-17, Postgres 16)

| Metric | Value |
|---|---|
| Catalog / warehouses / stock rows | 839 / 5 / 4,195 (synthetic, seeded) |
| Search relevance (16 labeled queries) | **MRR 1.000**, precision@1 **1.000**, precision@5 **0.9375** |
| Typo-tolerance (10 misspelled queries) | **MRR 1.000**, recall@10 **1.00** |
| ATP correctness | **40/40 scenarios (100%)** |
| Oversell under concurrency | **0 units** across 95 concurrent reserves |
| Security controls proven | **5 / 5** (401 · 403 · 422 · 429 · SQLi-safe) |
| `/search` latency (in-process) | p50 **8.4 ms**, p95 **11.3 ms** |
| `/availability` latency (in-process) | p50 **2.5 ms**, p95 **4.1 ms** |
| Tests / coverage | **49 passed**, **94.06%** |

Full detail + exact reproduce steps in **[RESULTS.md](RESULTS.md)**; raw numbers in
`results/*.json`; résumé bullets in **[BULLETS.md](BULLETS.md)**.
