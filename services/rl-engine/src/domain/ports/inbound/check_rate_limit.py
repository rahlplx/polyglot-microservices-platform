"""
Inbound port interfaces for rate limit checking and traffic analysis.

This module defines the primary inbound ports that constitute the rate
limiting engine's API surface. These ports are implemented by the domain
services and invoked by inbound adapters (gRPC handlers, REST controllers,
API gateway middleware).

Each port follows the command/query separation principle:
- CheckRateLimitPort is a query that evaluates a rate limit without side
  effects beyond token consumption.
- RecordRequestPort is a command that records a request for analysis.
- GetTrafficPatternPort is a query that returns the current traffic pattern.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ...models.rate_limit import (
    RateLimitKey,
    RateLimitRule,
    RateLimitStatus,
    TrafficPattern,
)


class CheckRateLimitPort(ABC):
    """Use case port for checking whether a request is allowed.

    This port is the primary entry point for rate limit evaluation. It takes
    a rate limit key and rule, and returns a status indicating whether the
    request is permitted, along with metadata for HTTP response headers.

    Implementations must be thread-safe and rely on the outbound store port
    for atomic read-modify-write operations. The check is not purely
    idempotent: for token bucket and adaptive strategies, a successful
    check consumes a token, which is a side effect.
    """

    @abstractmethod
    def check(self, key: RateLimitKey, rule: RateLimitRule) -> RateLimitStatus:
        """Evaluate whether a request identified by the key is allowed.

        Args:
            key: The composite rate limit key identifying the client,
                route, method, and custom tags.
            rule: The rate limit rule to apply for this check.

        Returns:
            A RateLimitStatus with the evaluation result, including
            remaining capacity, reset time, and retry-after if denied.
        """
        ...


class RecordRequestPort(ABC):
    """Use case port for recording request outcomes for pattern analysis.

    This port must be called after every rate limit check to maintain the
    request history used by the traffic pattern analysis engine. The
    recorded data enables the Adaptive ML strategy to classify traffic
    patterns and adjust limits dynamically.

    Recording is a fire-and-forget operation: it should not block the
    request path. Implementations may use asynchronous write-behind
    batching for high-throughput scenarios.
    """

    @abstractmethod
    def record(self, key: RateLimitKey, allowed: bool) -> None:
        """Record the outcome of a rate limit check.

        Args:
            key: The rate limit key for the request.
            allowed: Whether the request was permitted by the rate limiter.
        """
        ...


class GetTrafficPatternPort(ABC):
    """Use case port for retrieving the current traffic pattern for a key.

    This port supports observability dashboards and alerting by exposing
    the traffic pattern classification for each rate limit key. It can
    also be used by the API gateway to make routing decisions based on
    traffic patterns (e.g., shedding load during SPIKE patterns).
    """

    @abstractmethod
    def get_pattern(self, key: RateLimitKey) -> TrafficPattern:
        """Get the current traffic pattern classification for a key.

        Args:
            key: The rate limit key to analyze.

        Returns:
            The detected TrafficPattern for the key.
        """
        ...
