"""Security bench: exercise each secure-by-design control and record the result.

The same controls are asserted by the pytest security suite; this bench captures a
machine-readable ``results/security.json`` artifact from a real run.
"""

from __future__ import annotations

from typing import Any

from bench.harness import ensure_seeded, make_client, make_settings
from stockfind import db


def _token(client, role: str) -> str:
    resp = client.post("/auth/token", json={"username": f"{role}-user", "role": role})
    return resp.json()["data"]["access_token"]


def run_security_checks() -> dict[str, Any]:
    ensure_seeded()
    client = make_client()
    controls: list[dict[str, Any]] = []

    # 1. authN — protected route with no credential -> 401.
    reserve_body = {"sku": "IRO-HBH-00055", "warehouse_code": "TXDAL", "quantity": 1}
    r = client.post("/reserve", json=reserve_body)
    controls.append({
        "control": "authentication_required",
        "check": "POST /reserve without a token",
        "expected_status": 401,
        "actual_status": r.status_code,
        "passed": r.status_code == 401,
    })

    # 2. authZ — buyer token on an admin-only route -> 403; admin -> 200.
    buyer = _token(client, "buyer")
    admin = _token(client, "admin")
    r_buyer = client.get("/admin/reservations", headers={"Authorization": f"Bearer {buyer}"})
    r_admin = client.get("/admin/reservations", headers={"Authorization": f"Bearer {admin}"})
    controls.append({
        "control": "role_based_authorization",
        "check": "buyer -> /admin/reservations (403), admin -> 200",
        "expected_status": 403,
        "actual_status": r_buyer.status_code,
        "admin_status": r_admin.status_code,
        "passed": r_buyer.status_code == 403 and r_admin.status_code == 200,
    })

    # 3. input validation — schema violation -> 422.
    r_bad_qty = client.post(
        "/reserve",
        headers={"Authorization": f"Bearer {buyer}"},
        json={"sku": "IRO-HBH-00055", "warehouse_code": "TXDAL", "quantity": 0},
    )
    r_bad_attr = client.get("/search", params={"q": "bolt", "attr": "brokenfilter"})
    controls.append({
        "control": "input_validation",
        "check": "quantity=0 body (422) and malformed attr filter (422)",
        "expected_status": 422,
        "reserve_qty0_status": r_bad_qty.status_code,
        "bad_attr_status": r_bad_attr.status_code,
        "passed": r_bad_qty.status_code == 422 and r_bad_attr.status_code == 422,
    })

    # 4. rate limiting — a tight limiter must return 429 once drained.
    limited = make_client(make_settings(search_rate_limit="3/minute"))
    statuses = [limited.get("/search", params={"q": "bolt"}).status_code for _ in range(6)]
    controls.append({
        "control": "rate_limiting",
        "check": "6 rapid /search calls against a 3/minute limiter",
        "statuses": statuses,
        "expected_status": 429,
        "passed": 429 in statuses and statuses[:3] == [200, 200, 200],
    })

    # 5. SQL injection — parameterized queries: attempts return normal data, no leak,
    #    and the products table is untouched.
    before = db.fetch_one("SELECT count(*) AS n FROM products")["n"]
    inj_q = client.get("/search", params={"q": "'; DROP TABLE products; --"})
    inj_attr = client.get("/search", params={"q": "bolt", "attr": "category:Fasteners' OR '1'='1"})
    after = db.fetch_one("SELECT count(*) AS n FROM products")["n"]
    body = inj_q.json()
    controls.append({
        "control": "sql_injection_safe",
        "check": "injection in q + attribute filter; parameterized queries",
        "products_before": before,
        "products_after": after,
        "injection_query_status": inj_q.status_code,
        "injection_attr_status": inj_attr.status_code,
        "envelope_ok": body.get("success") is True and body.get("error") is None,
        "passed": (
            before == after
            and inj_q.status_code == 200
            and inj_attr.status_code == 200
            and body.get("success") is True
        ),
    })

    passed = sum(1 for c in controls if c["passed"])
    return {
        "controls_total": len(controls),
        "controls_passed": passed,
        "all_passed": passed == len(controls),
        "controls": controls,
    }
