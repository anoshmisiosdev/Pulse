"""Lightweight in-memory IP rate limiter middleware.

Protects auth endpoints (brute-force) and expensive LLM endpoints (cost abuse)
without adding a Redis dependency for single-instance deployments. For multi-
instance production, replace the in-memory store with Redis (the interface stays
the same — only ``_Bucket`` changes).
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


@dataclass
class _Bucket:
    """Sliding-window counter for one IP + path-prefix."""

    timestamps: list[float] = field(default_factory=list)

    def hit(self, now: float, window: float, limit: int) -> bool:
        """Record a hit. Returns True if allowed, False if rate-limited."""
        cutoff = now - window
        self.timestamps = [t for t in self.timestamps if t > cutoff]
        if len(self.timestamps) >= limit:
            return False
        self.timestamps.append(now)
        return True

    def retry_after(self, now: float, window: float) -> float:
        """Seconds until the oldest request exits the window."""
        if not self.timestamps:
            return 0.0
        return max(0.0, self.timestamps[0] + window - now)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP, per-path-prefix rate limiter.

    ``rules`` maps a URL prefix to (limit, window_seconds). Example::

        rules={"/api/auth": (5, 60), "/api/competitor-prices": (3, 60)}
    """

    def __init__(self, app, rules: dict[str, tuple[int, int]] | None = None) -> None:
        super().__init__(app)
        self.rules = rules or {}
        self._buckets: dict[str, _Bucket] = defaultdict(_Bucket)

    def _client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _matching_rule(self, path: str) -> tuple[int, int] | None:
        for prefix, rule in self.rules.items():
            if path.startswith(prefix):
                return rule
        return None

    async def dispatch(self, request: Request, call_next):
        rule = self._matching_rule(request.url.path)
        if rule is None:
            return await call_next(request)

        # OPTIONS preflight should never be rate-limited.
        if request.method == "OPTIONS":
            return await call_next(request)

        limit, window = rule
        ip = self._client_ip(request)
        key = f"{ip}:{request.url.path}"
        bucket = self._buckets[key]
        now = time.monotonic()

        if not bucket.hit(now, window, limit):
            retry = bucket.retry_after(now, window)
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": str(int(retry) + 1)},
            )

        return await call_next(request)