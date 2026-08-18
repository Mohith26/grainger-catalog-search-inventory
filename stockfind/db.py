"""Postgres access: a shared connection pool plus small helpers.

Every query in the codebase goes through psycopg with **parameterized** SQL
(``%s`` placeholders, never string interpolation of user input), which is what
makes the service SQL-injection safe by construction.
"""

from __future__ import annotations

from importlib import resources
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None


def init_pool(dsn: str, *, min_size: int = 1, max_size: int = 16) -> ConnectionPool:
    """Create (or return) the process-wide connection pool.

    ``max_size`` is deliberately > 1 so the concurrency test can hold several
    row locks at once and prove that reservations serialize correctly.
    """
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    return _pool


def get_pool() -> ConnectionPool:
    if _pool is None:
        raise RuntimeError("Connection pool is not initialized; call init_pool() first.")
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def load_schema_sql() -> str:
    return resources.files("stockfind.catalog").joinpath("schema.sql").read_text()


def reset_schema() -> None:
    """Drop and recreate every table. Destructive; used by seed + tests."""
    ddl = load_schema_sql()
    with get_pool().connection() as conn:
        conn.execute(ddl)
        conn.commit()


def fetch_all(sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
    with get_pool().connection() as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall()


def fetch_one(sql: str, params: tuple[Any, ...] | None = None) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        cur = conn.execute(sql, params)
        return cur.fetchone()
