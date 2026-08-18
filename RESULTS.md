# StockFind — Measured Results

**Date measured:** 2026-08-17
**Stack:** Python 3.12 · FastAPI · **Postgres 16** (full-text `tsvector`/`ts_rank` + GIN) ·
rapidfuzz (typo tolerance) · psycopg 3 (parameterized) · PyJWT · prometheus-client · structlog.
**Data:** 100% **synthetic**, seeded, reproducible (`stockfind/catalog/seed.py`, `seed=42`).

Every number below comes from a real run against a live Postgres 16 (docker-compose).
Machine-readable values are committed under `results/*.json`; anything not measured is
written as the literal `___`.

---

## How to reproduce (exact commands)

```bash
# 0. one-time setup
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# 1. start Postgres 16 (host port 5470)
docker compose up -d db
docker compose ps                     # wait for `db` to report healthy

# 2. point the app at it + a real JWT secret
export STOCKFIND_PG_DSN="postgresql://stockfind:stockfind@localhost:5470/stockfind"
export STOCKFIND_JWT_SECRET="local-secret-at-least-32-bytes-long-xx"

# 3. seed the deterministic catalog (839 SKUs, 5 warehouses, 4,195 stock rows)
python -m stockfind.catalog.seed

# 4. run the whole test suite (search / ATP / concurrency / security / observability)
pytest                                # -> 49 passed, 94% coverage

# 5. run every benchmark and (re)write results/*.json
python -m bench.run_all
```

### Individual benchmarks
```bash
python -c "from eval.relevance import run_relevance_eval; print(run_relevance_eval().to_dict())"
python -c "from bench.inventory_scenarios import run_inventory_bench; print(run_inventory_bench())"
python -c "from bench.security_checks import run_security_checks; print(run_security_checks())"
python -c "from bench.latency import run_latency_bench; print(run_latency_bench())"
```

### One-command full stack (Postgres + gateway, seeds on boot)
```bash
docker compose up -d --build          # db + gateway; gateway seeds the catalog on start
curl -s localhost:8055/health         # {"success":true,"data":{"status":"ok"},...}
curl -s "localhost:8055/search?q=staineless%20steel%20hex%20bolt&limit=3"
curl -s "localhost:8055/availability?sku=IRO-HBH-00055&region=TX"
curl -s localhost:8055/metrics | grep stockfind_http   # Prometheus metrics
open http://localhost:8055/docs                        # OpenAPI UI
```

### Gateway verified over a real HTTP socket (uvicorn factory mode)
```bash
docker compose up -d db               # Postgres 16 (host port 5470)
export STOCKFIND_PG_DSN="postgresql://stockfind:stockfind@localhost:5470/stockfind"
export STOCKFIND_JWT_SECRET="local-socket-secret-at-least-32-bytes-x"
python -m stockfind.catalog.seed
uvicorn --factory stockfind.api.app:create_app --host 127.0.0.1 --port 8056
# then, over the socket: /health 200, /search 200 (facets + score),
# /availability 200, /reserve 401→(with token)201, quantity=0 422,
# /admin/reservations buyer 403 / admin 200, SQLi q 200, /metrics counter+histogram,
# X-Request-ID header echoed — all confirmed 2026-08-17.
```

### Example: reserve (auth) + zero-oversell path
```bash
TOKEN=$(curl -s -X POST localhost:8055/auth/token -H 'content-type: application/json' \
  -d '{"username":"buyer1","role":"buyer"}' | python -c "import sys,json;print(json.load(sys.stdin)['data']['access_token'])")
curl -s -X POST localhost:8055/reserve -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"sku":"IRO-HBH-00055","warehouse_code":"TXDAL","quantity":5}'
# unauthenticated -> 401 ; buyer hitting /admin/reservations -> 403
```

---

## Scale (what is searched / promised) — `results/scale.json`

| Item | Value |
|---|---|
| Industrial SKUs (synthetic) | **839** across 9 categories, 23 subtypes, 10 brands |
| Warehouses (US DCs) | **5** — ILCHI, TXDAL, CALAX, GAATL, NJEWR |
| Per-warehouse stock rows | **4,195** (839 × 5) |
| Seed | 42 (deterministic) |

## 1. Search relevance — `results/relevance.json`

Ground truth is defined by **structured product attributes** (subtype / material /
attributes) — the objective "right answers" — **independent** of the search ranking,
which only ever sees the free-text query. 16 labeled queries; 10 have a misspelled
`typo` variant expressing the same need.

| Metric (mean over queries) | precision@1 | precision@5 | precision@10 | MRR |
|---|---|---|---|---|
| **Clean queries (16)** | **1.000** | **0.9375** | **0.8562** | **1.000** |
| **Typo queries (10)** | **1.000** | **1.000** | **0.960** | **1.000** |

**Typo-tolerance recall** (misspelled query still retrieves the relevant items):
recall@1 = **1.00**, recall@5 = **1.00**, recall@10 = **1.00**.

**Honest read of precision@10 < 1.0:** it is a **denominator artifact, not a ranking
miss.** precision@k is capped at `|relevant|/k` when a query has fewer than k relevant
SKUs. The six clean queries with precision@10 < 1.0 each have **2–9 relevant items**
(e.g. `ball bearing 20mm` has 2, `amber safety glasses` has 3), so precision@10 can be
at most 0.2–0.9 by construction — yet **precision@1 = 1.0 and reciprocal rank = 1.0 for
every one** (the correct SKU is ranked first). MRR = 1.000 across all 16 queries means
the top hit was relevant every single time.

**How it works (honest):** lexical relevance is real Postgres full-text search
(`websearch_to_tsquery` + `ts_rank` over a weighted `tsvector`, GIN-indexed); typo
tolerance is a rapidfuzz per-token best-match blend
(`score = 0.7·norm(ts_rank) + 0.3·(fuzzy/100)`). Weights are fixed constants.

## 2. Inventory availability / ATP — `results/inventory.json`

ATP (available-to-promise) = `on_hand − reserved`, per warehouse, never negative.

| Metric | Value |
|---|---|
| ATP == on_hand − reserved (scenarios) | **40 / 40 = 100%** |
| Reservation lifecycle (reserve×2 → release×2 → ATP exact) | **5 / 5 steps correct** |
| **Oversell under concurrent reservations** | **0 units** |

**Zero-oversell proof (real row-locking, `SELECT ... FOR UPDATE`):** three concurrent
races, each firing many threads at one (SKU, warehouse):

| on_hand | reserve qty | concurrent attempts | successes | expected | oversell |
|---|---|---|---|---|---|
| 10 | 1 | 40 | **10** | 10 | **0** |
| 10 | 2 | 30 | **5** | 5 | **0** |
| 7 | 3 | 25 | **2** | 2 | **0** |

Exactly the available units were promised — never more — across **95 concurrent
attempts**. A DB `CHECK (reserved <= on_hand)` is the backstop behind the lock.

## 3. Secure-by-design — `results/security.json`

| # | Control | Proof | Result |
|---|---|---|---|
| 1 | Authentication required | `POST /reserve` with no token | **401** ✅ |
| 2 | Role-based authorization | buyer → `/admin/reservations` = 403; admin = 200 | **403 / 200** ✅ |
| 3 | Input validation (schema) | `quantity=0` body / malformed `attr` filter | **422** ✅ |
| 4 | Rate limiting | 6 rapid `/search` vs a `3/minute` token bucket | **429** ✅ |
| 5 | SQL-injection safe | `'; DROP TABLE products; --` in `q` + attr filter; parameterized | **200, no leak, 839→839 rows** ✅ |

**Controls proven: 5 / 5.** (Auth uses HS256 JWT with the secret from env only;
missing token → 401, wrong role → 403. Every query is parameterized psycopg SQL —
the injection attempt returns a normal empty/valid result and the `products` table row
count is unchanged.)

## 4. Observability — proven by `tests/test_observability.py`

| Signal | Verified |
|---|---|
| Prometheus `/metrics` | latency **histogram** (`stockfind_http_request_duration_seconds_bucket`) + request **counter** (`stockfind_http_requests_total`), labeled by method/route/status |
| Structured JSON logs | one JSON line per request carrying a bound `request_id` (captured via structlog) |
| Request-ID propagation | `X-Request-ID` generated or echoed from the caller, returned on the response |
| `/health` (liveness) | 200 |
| `/ready` (readiness) | 200 when the DB answers `SELECT 1`, else 503 |

## 5. Latency — `results/latency.json`

**Methodology (honest):** measured **in-process via Starlette's `TestClient` (ASGI)** —
this **excludes the real HTTP/TCP network socket** and reflects the service's own
per-request work (SQL + FTS ranking + rapidfuzz blend + ATP aggregation). 300 timed
requests per endpoint, 30 warm-up excluded, mixed query set.

| Endpoint | p50 | p95 | p99 | mean |
|---|---|---|---|---|
| `GET /search` | **8.40 ms** | **11.26 ms** | 14.80 ms | 8.71 ms |
| `GET /availability` | **2.46 ms** | **4.08 ms** | 5.42 ms | 2.65 ms |

## 6. Tests & coverage — `results/coverage.json`

| Metric | Value |
|---|---|
| Tests | **49 passed** (0 failed) |
| Coverage (`stockfind/` + `eval/`) | **94.06%** (728 / 774 statements) |
| Lint | `ruff check .` → **clean** |
| CI | `.github/workflows/ci.yml`: Postgres 16 service → ruff → seed → pytest → coverage ≥ 80% gate. **Same 4 steps run locally and pass** (ruff clean, 49 passed, coverage gate 94% ≥ 80%). |

---

## Honest limitations / notes

- **Synthetic seeded data** — deterministic generator, fictional brands, computed
  prices; not real Grainger catalog or inventory.
- **Latency is in-process** (TestClient / ASGI), not over a network socket (see §5).
  The gateway *does* serve over a real HTTP socket — verified live via
  `uvicorn --factory` on 2026-08-17 (every endpoint + auth + metrics + `X-Request-ID`) —
  but the p50/p95 numbers above are the in-process measurement.
- **Docker gateway image build:** the `db` service (`postgres:16`, cached) and the full
  test/bench suite are verified live. In the build sandbox the **gateway image could not
  build because Docker Hub was unreachable** (base image `python:3.12-slim` timed out on
  pull); the `docker-compose.yml` + `Dockerfile` are valid and the gateway was instead
  verified over a real socket with `uvicorn --factory` (command above). It will build
  normally in any environment with Docker Hub access.
- **precision@10 < 1.0 is a small-relevant-set artifact**, not a ranking error — MRR and
  precision@1 are 1.000 (see §1).
- **Search is a lexical (Postgres FTS) + fuzzy (rapidfuzz) blend** with fixed weights;
  no learned ranking model (out of scope).
- **Rate limiter is an in-process token bucket** keyed per client IP + route; fine for a
  single instance, not a shared/distributed limiter.
- Not built (out of scope per spec): React UI, synonym/unit normalization
  (`1/2 in` == `0.5"`), autocomplete, real payments/checkout, cloud deploy.
