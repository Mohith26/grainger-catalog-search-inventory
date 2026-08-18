"""In-process token-bucket rate limiter (per client IP + route).

A token bucket gives each key a small burst allowance that refills at a steady
rate; when a caller drains it, further requests get ``429 Too Many Requests``.
Buckets live per-app (on ``app.state``) so tests can stand up an isolated limiter.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

_PERIOD_SECONDS = {"second": 1, "minute": 60, "hour": 3600}


def parse_limit(limit: str) -> tuple[int, float]:
    """Parse an "N/period" string into (capacity, refill_tokens_per_second)."""
    count_str, _, period = limit.partition("/")
    count = int(count_str.strip())
    seconds = _PERIOD_SECONDS[period.strip().lower()]
    return count, count / seconds


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class TokenBucketLimiter:
    def __init__(self, limit: str):
        self.capacity, self.refill_rate = parse_limit(limit)
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, *, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=float(self.capacity), last_refill=now)
                self._buckets[key] = bucket
            elapsed = now - bucket.last_refill
            bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.refill_rate)
            bucket.last_refill = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True
            return False


def rate_limited(limiter_name: str):
    """Build a FastAPI dependency enforcing the named app-state limiter."""

    def dependency(request: Request) -> None:
        limiter: TokenBucketLimiter = getattr(request.app.state, limiter_name)
        client = request.client.host if request.client else "anonymous"
        route = request.scope.get("route")
        path = getattr(route, "path", None) or request.url.path
        key = f"{client}:{path}"
        if not limiter.allow(key):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={"Retry-After": "1"},
            )

    return dependency
