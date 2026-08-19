# StockFind

A B2B industrial-catalog search and multi-warehouse inventory API I built to work through two problems that sit at the core of industrial-distribution e-commerce: finding the right part fast (faceted, typo-tolerant search over MRO-style SKUs) and knowing if and where it's in stock (per-warehouse available-to-promise with reserve/release that provably never oversells). Along the way I tried to make the "production envelope" first-class and measurable rather than an afterthought: automated tests, CI, structured logging and metrics, and secure-by-design request handling.

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

Or the one-command full stack (Postgres + gateway, seeds on boot):

```bash
docker compose up -d --build
curl -s localhost:8055/health
open http://localhost:8055/docs         # OpenAPI UI
```

## What it does

- **Search**: Postgres full-text (`tsvector` + `ts_rank`, GIN-indexed) for lexical relevance, blended with rapidfuzz per-token fuzzy scoring for typo tolerance. Faceted filters on category / brand / material / attributes, with bounded pagination.
- **Availability / ATP**: per-warehouse `on_hand` + ATP = on_hand minus reserved, nearest-warehouse by haversine distance from a region, lead-time and backorder flags.
- **Reserve / release**: `SELECT ... FOR UPDATE` row-locking so concurrent reservations can never oversell, with a DB `CHECK (reserved <= on_hand)` as a backstop.
- **Security**: pydantic schema validation (422), JWT with buyer/admin roles (401/403), token-bucket rate limiting (429), parameterized psycopg SQL everywhere.
- **Observability**: structlog JSON logs with a bound request id, Prometheus `/metrics` (latency histogram + request counter), `/health` and `/ready`.

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

Stack: Python 3.12, FastAPI + uvicorn, Postgres 16, psycopg 3 + pool, rapidfuzz, pydantic, PyJWT, prometheus-client, structlog, pytest + coverage, ruff, GitHub Actions, Docker. Free/local, CPU-only, no external API keys.

## API

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /search?q=&category=&brand=&material=&attr=k:v&limit=&offset=` | public | faceted, typo-tolerant search |
| `GET /products/{id}` | public | product detail |
| `GET /availability?sku=&region=` | public | per-warehouse ATP + nearest DC + backorder |
| `POST /reserve` | buyer/admin | reserve stock (FOR UPDATE, no oversell) |
| `DELETE /reservations/{id}` | buyer/admin | release a reservation |
| `GET /admin/reservations` | admin | list reservations (role-gated) |
| `POST /auth/token` | public | mint a demo JWT for a username + role |
| `GET /health` · `/ready` · `/metrics` | public | liveness · DB readiness · Prometheus |

```bash
# typo-tolerant search returns the right parts:
curl -s "localhost:8055/search?q=staineless%20steel%20hex%20bolt&limit=3"

# adversarial reach-arounds are refused / inert:
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8055/reserve \
  -d '{"sku":"IRO-HBH-00055","warehouse_code":"TXDAL","quantity":1}'  # -> 401 (no token)
```

## Repository layout

```
stockfind/
  config.py            env-driven settings (DSN, JWT secret, rate limits, seed)
  db.py                psycopg connection pool + schema loader (parameterized helpers)
  envelope.py          consistent {success,data,error,meta} + pagination meta
  models.py            pydantic request/response models (validation at the boundary)
  errors.py            domain errors -> HTTP status
  catalog/             schema.sql (GIN tsvector, no-oversell CHECK) + seed.py (seed=42)
  search/              FTS lexical + rapidfuzz typo blend + facet filters/aggregation
  inventory/           per-warehouse ATP, nearest warehouse, reserve/release (FOR UPDATE)
  security/            JWT issue/verify + role deps; in-process token-bucket limiter
  observability/       structlog JSON + request-id middleware; Prometheus middleware
  api/                 app factory + catalog / inventory / meta routers
eval/                  16 labeled queries (10 with typo variants) + relevance harness
bench/                 latency, ATP correctness + concurrency, security checks, run_all
tests/                 49 tests (search / ATP / concurrency / security / observability / api)
results/*.json         committed measured numbers (2026-08-17)
.github/workflows/ci.yml   Postgres service -> ruff -> seed -> pytest -> coverage gate
```

## Measured results (2026-08-17, Postgres 16)

| Metric | Value |
|---|---|
| Catalog / warehouses / stock rows | 839 / 5 / 4,195 (synthetic, seeded) |
| Search relevance (16 labeled queries) | MRR 1.000, precision@1 1.000, precision@5 0.9375 |
| Typo-tolerance (10 misspelled queries) | MRR 1.000, recall@10 1.00 |
| ATP correctness | 40/40 scenarios (100%) |
| Oversell under concurrency | 0 units across 95 concurrent reserves |
| Security controls proven | 5 / 5 (401 · 403 · 422 · 429 · SQLi-safe) |
| `/search` latency (in-process) | p50 8.4 ms, p95 11.3 ms |
| `/availability` latency (in-process) | p50 2.5 ms, p95 4.1 ms |
| Tests / coverage | 49 passed, 94.06% |

Full detail and exact reproduce steps in [RESULTS.md](RESULTS.md); raw numbers in `results/*.json`.

## Limitations

- The catalog is 100% synthetic and seeded (`stockfind/catalog/seed.py`, `seed=42`): fictional brands, computed prices. It is shaped like an industrial MRO catalog but is not real distributor data.
- Latency numbers are measured in-process (FastAPI `TestClient` / ASGI), not over a network socket, so they reflect the service's own per-request work without TCP overhead. The gateway does serve over a real socket and every endpoint was verified live via `uvicorn --factory`, but the p50/p95 figures are the in-process measurement.
- Search ranking is a lexical (Postgres FTS) + fuzzy (rapidfuzz) blend with fixed weights; there is no learned ranking model.
- The rate limiter is an in-process token bucket keyed per client IP + route, fine for a single instance but not a shared/distributed limiter.
- precision@10 lands below 1.0 only because several queries have fewer than 10 relevant SKUs (a denominator cap, not a ranking miss; see RESULTS.md).
- Not built: a UI, synonym/unit normalization (`1/2 in` == `0.5"`), autocomplete, payments/checkout, cloud deploy.
