"""Operational routes: token minting, health, readiness, and Prometheus metrics."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from stockfind import db
from stockfind.envelope import ok
from stockfind.models import TokenRequest
from stockfind.security.auth import issue_token

router = APIRouter()


@router.post("/auth/token")
def mint_token(payload: TokenRequest, request: Request):
    """Demo token endpoint: hands out a signed JWT for a username + role.

    A real deployment would verify a password / IdP here; the JWT + role
    enforcement it feeds is identical either way.
    """
    settings = request.app.state.settings
    token, ttl = issue_token(payload.username, payload.role, settings)
    return ok({
        "access_token": token,
        "token_type": "bearer",
        "role": payload.role,
        "expires_in": ttl,
    })


@router.get("/health")
def health():
    """Liveness: the process is up and serving."""
    return ok({"status": "ok"})


@router.get("/ready")
def ready(response: Response):
    """Readiness: the database is reachable (a real dependency check)."""
    try:
        db.fetch_one("SELECT 1 AS ok")
    except Exception as exc:  # noqa: BLE001 - report readiness, do not crash
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"success": False, "data": {"status": "not_ready"},
                "error": str(exc), "meta": None}
    return ok({"status": "ready"})


@router.get("/metrics")
def metrics(request: Request):
    payload, content_type = request.app.state.metrics.render()
    return Response(content=payload, media_type=content_type)
