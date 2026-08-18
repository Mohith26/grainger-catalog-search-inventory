"""Shared pytest fixtures: settings, seeded DB, per-test app/client, tokens."""

from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient

from stockfind import db
from stockfind.api.app import create_app
from stockfind.catalog.seed import seed_database
from stockfind.config import Settings

DSN = os.environ.get(
    "STOCKFIND_PG_DSN", "postgresql://stockfind:stockfind@localhost:5470/stockfind"
)
JWT_SECRET = "test-secret-key-at-least-32-bytes-long-x"


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        pg_dsn=DSN,
        jwt_secret=JWT_SECRET,
        debug=True,
        search_rate_limit="1000000/minute",
        reserve_rate_limit="1000000/minute",
        seed_on_start=False,
    )


@pytest.fixture(scope="session", autouse=True)
def _seed(settings: Settings):
    db.init_pool(settings.pg_dsn)
    seed_database(settings.seed)
    yield


@pytest.fixture
def reseed(settings: Settings):
    """Restore the pristine catalog (use in tests that mutate inventory)."""
    seed_database(settings.seed)
    yield


def make_settings(settings: Settings, **overrides) -> Settings:
    data = settings.model_dump()
    data.update(overrides)
    return Settings(**data)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    # Fresh app per test -> isolated metrics registry + rate-limiter state.
    return TestClient(create_app(settings))


def _mint(client: TestClient, role: str) -> str:
    resp = client.post("/auth/token", json={"username": f"{role}1", "role": role})
    assert resp.status_code == 200
    return resp.json()["data"]["access_token"]


@pytest.fixture
def buyer_token(client: TestClient) -> str:
    return _mint(client, "buyer")


@pytest.fixture
def admin_token(client: TestClient) -> str:
    return _mint(client, "admin")
