"""Shared bench harness: build a configured app + ensure the catalog is seeded."""

from __future__ import annotations

import os

from starlette.testclient import TestClient

from stockfind import db
from stockfind.api.app import create_app
from stockfind.config import Settings

DSN = os.environ.get(
    "STOCKFIND_PG_DSN", "postgresql://stockfind:stockfind@localhost:5470/stockfind"
)


def make_settings(**overrides) -> Settings:
    base = {
        "pg_dsn": DSN,
        "jwt_secret": "bench-secret-key-at-least-32-bytes-long!!",
        "debug": True,
        # Effectively unlimited unless a bench overrides it.
        "search_rate_limit": "1000000/minute",
        "reserve_rate_limit": "1000000/minute",
        "seed_on_start": False,
    }
    base.update(overrides)
    return Settings(**base)


def ensure_seeded(seed: int = 42) -> dict[str, int]:
    from stockfind.catalog.seed import seed_database

    db.init_pool(DSN)
    return seed_database(seed)


def make_client(settings: Settings | None = None) -> TestClient:
    settings = settings or make_settings()
    db.init_pool(settings.pg_dsn)
    app = create_app(settings)
    return TestClient(app)
