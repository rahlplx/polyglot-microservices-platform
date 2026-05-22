"""In-memory RateLimitStorePort — for tests and dev without KeyDB."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from ...domain.models.rate_limit import TokenBucketState
from ...domain.ports.outbound.rate_limit_store import RateLimitStorePort


class InMemoryRateLimitStore(RateLimitStorePort):
    """Thread-safe in-memory store. No external dependencies."""

    def __init__(self) -> None:
        self._buckets: Dict[str, TokenBucketState] = {}
        self._counters: Dict[str, Tuple[int, float]] = {}  # key -> (count, expires_at)
        self._lock = threading.Lock()

    def get_bucket(self, key: str) -> Optional[TokenBucketState]:
        with self._lock:
            return self._buckets.get(key)

    def save_bucket(self, bucket: TokenBucketState) -> None:
        with self._lock:
            self._buckets[bucket.key] = bucket

    def increment_counter(self, key: str, window: int) -> int:
        now = time.monotonic()
        with self._lock:
            count, expires_at = self._counters.get(key, (0, now + window))
            if now > expires_at:
                count, expires_at = 0, now + window
            count += 1
            self._counters[key] = (count, expires_at)
            return count
