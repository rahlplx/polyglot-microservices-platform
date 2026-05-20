"""
Outbound port interface for rate limit state persistence.

This module defines the RateLimitStorePort, which abstracts the storage
backend for rate limiting state. The domain engine depends on this port
rather than a concrete storage implementation, following
the Dependency Inversion Principle.

Implementations must provide atomic read-modify-write semantics for
correct concurrent operation. This is typically achieved using atomic
store operations or transactional guarantees provided by the storage backend.

The store manages two types of state:
1. Token bucket state — keyed by compound rate limit key, persisted as
   TokenBucketState objects with token counts and refill timestamps.
2. Window counters — keyed by compound key + window identifier, persisted
   as integer counters with automatic expiration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ...models.rate_limit import TokenBucketState


class RateLimitStorePort(ABC):
    """Outbound port for rate limit state storage and retrieval.

    This port abstracts the persistence layer for rate limiting state,
    supporting both token bucket and sliding/fixed window strategies.
    Implementations must ensure atomicity for concurrent access patterns.

    Typical implementations use atomic increment-and-expire operations
    for window counters and atomic compare-and-swap for token bucket state.

    The port is deliberately synchronous to ensure that rate limit checks
    are fast and deterministic. Asynchronous store operations should be
    handled at the adapter level using thread pools or async wrappers.
    """

    @abstractmethod
    def get_bucket(self, key: str) -> Optional[TokenBucketState]:
        """Retrieve the current token bucket state for a key.

        Returns None if no bucket exists for the key, which indicates
        that a new bucket should be initialized by the engine.

        Args:
            key: The compound rate limit key string.

        Returns:
            The current TokenBucketState, or None if not found.
        """
        ...

    @abstractmethod
    def save_bucket(self, bucket: TokenBucketState) -> None:
        """Persist the token bucket state.

        This method performs an upsert: if a bucket exists for the key,
        it is replaced; otherwise, a new entry is created. The save must
        be atomic to prevent lost updates from concurrent requests.

        Implementations should set a TTL on the key equal to the time
        it would take for the bucket to fully refill from empty, plus
        a safety margin, to prevent unbounded growth of stale state.

        Args:
            bucket: The token bucket state to persist.
        """
        ...

    @abstractmethod
    def increment_counter(self, key: str, window: int) -> int:
        """Atomically increment a window counter and return the new value.

        This method supports the sliding window and fixed window strategies
        by maintaining a counter for a given key within a time window.
        The counter must automatically expire after the window duration
        to prevent stale data from affecting future windows.

        The operation must be atomic: the increment and read must happen
        as a single operation to prevent race conditions between concurrent
        requests. Atomic increment-with-expiry is a typical implementation.

        Args:
            key: The counter key, typically including a window identifier.
            window: The window duration in seconds. The counter should
                automatically expire after this duration.

        Returns:
            The counter value after incrementing (i.e., the new count).
        """
        ...
