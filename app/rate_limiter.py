from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Callable

from fastapi import HTTPException, Request
from starlette.responses import Response


class InMemoryRateLimiter:
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self._max = max_requests
        self._window = window_seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _key(self, request: Request) -> str:
        user = request.session.get("canvas_user_id") or request.client.host or "unknown"
        return str(user)

    def check(self, request: Request) -> None:
        key = self._key(request)
        now = time.time()
        window_start = now - self._window
        with self._lock:
            timestamps = self._buckets[key]
            timestamps[:] = [t for t in timestamps if t > window_start]
            if len(timestamps) >= self._max:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Max {self._max} requests per {self._window}s.",
                )
            timestamps.append(now)


_generate_limiter = InMemoryRateLimiter(max_requests=10, window_seconds=60)


def rate_limit_generate(request: Request) -> None:
    _generate_limiter.check(request)
