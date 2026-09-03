"""In-process sliding-window rate limiting, keyed per Canvas user.

Covers the expensive endpoints (LLM calls) so a single user or stray loop
cannot exhaust the threadpool or run up provider bills. Buckets are evicted
once they go fully idle for ``_BUCKET_TTL`` so the map cannot grow without
bound. Process-local by design — multi-worker deployments need a shared store.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Callable

from fastapi import HTTPException, Request

from app import config


class InMemoryRateLimiter:
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self._max = max_requests
        self._window = window_seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._last_seen: dict[str, float] = {}

    # A bucket that has seen no activity for this long is dropped entirely.
    _BUCKET_TTL = 30 * 60

    def _key(self, request: Request) -> str:
        user = request.session.get("canvas_user_id")
        if not user:
            raise HTTPException(
                status_code=401,
                detail="User identity not found. Re-launch EasyLearn from Canvas.",
            )
        return f"user:{user}"

    def check(self, request: Request, max_requests: int | None = None) -> None:
        key = self._key(request)
        now = time.time()
        window_start = now - self._window
        limit = self._max if max_requests is None else max_requests
        with self._lock:
            if len(self._buckets) > 4096:
                stale = [
                    k for k, last in self._last_seen.items() if now - last > self._BUCKET_TTL
                ]
                for k in stale:
                    self._buckets.pop(k, None)
                    self._last_seen.pop(k, None)

            timestamps = self._buckets[key]
            timestamps[:] = [t for t in timestamps if t > window_start]
            if len(timestamps) >= limit:
                retry_after = int(self._window - (now - timestamps[0])) + 1
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Rate limit exceeded. Max {limit} requests per "
                        f"{self._window}s. Retry in ~{retry_after}s."
                    ),
                    headers={"Retry-After": str(max(retry_after, 1))},
                )
            timestamps.append(now)
            self._last_seen[key] = now


# Quiz generation is the most expensive call (download + extract + LLM).
_generate_limiter = InMemoryRateLimiter(max_requests=10, window_seconds=60)
# Feedback processing/preview each make several LLM calls per invocation.
_feedback_limiter = InMemoryRateLimiter(max_requests=6, window_seconds=60)


def rate_limit_generate(request: Request) -> None:
    _generate_limiter.check(request, max_requests=int(config.RATE_LIMIT_GENERATE_PER_MIN))


def rate_limit_feedback_llm(request: Request) -> None:
    _feedback_limiter.check(request, max_requests=int(config.RATE_LIMIT_FEEDBACK_PER_MIN))


def require_llm_budget(request: Request) -> None:
    """Reject the request before any Canvas/LLM work if today's spend cap is hit."""
    from app.ops.budgets import assert_within_budget

    user_id = request.session.get("canvas_user_id")
    assert_within_budget(str(user_id) if user_id else None)


def rate_limit_factory(limiter: InMemoryRateLimiter) -> Callable[[Request], None]:
    """Dependency factory for additional named limiters."""
    return limiter.check
