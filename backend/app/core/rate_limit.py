"""Small in-memory sliding-window rate limiter for the login endpoint.

State is per-process. With several backend workers/replicas each keeps its own
counters, which still bounds brute-force attempts. Replace with a shared store
(e.g. Redis) if the deployment scales horizontally.
"""

import threading
import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, window: float, now: float) -> deque[float]:
        hits = self._hits[key]
        while hits and hits[0] <= now - window:
            hits.popleft()
        return hits

    def is_limited(self, key: str, limit: int, window: float) -> bool:
        with self._lock:
            return len(self._prune(key, window, time.monotonic())) >= limit

    def record(self, key: str) -> None:
        with self._lock:
            self._hits[key].append(time.monotonic())

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = SlidingWindowRateLimiter()
