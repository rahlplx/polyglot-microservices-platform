"""
Rate limiting domain models for the RL Engine service.

This module defines the core entities and value objects for adaptive rate
limiting with ML-based pattern detection. The models represent rate limit
rules, bucket states, request keys, and traffic patterns — all pure Python
with zero external dependencies to maintain the hexagonal architecture boundary.

The rate limiting engine supports four strategies: Token Bucket, Sliding Window,
Fixed Window, and Adaptive ML. The Adaptive ML strategy leverages traffic pattern
analysis to dynamically adjust rate limits based on observed behavior, enabling
the system to handle legitimate bursts while protecting against abuse.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class RateLimitStrategy(str, Enum):
    """Rate limiting algorithm selection.

    TOKEN_BUCKET allows bursts up to burst_multiplier * max_requests, with
    tokens replenished at a steady rate. Best for APIs with variable traffic
    where short bursts should be permitted.

    SLIDING_WINDOW tracks requests within a continuously sliding time window,
    providing smoother rate enforcement than fixed windows. Ideal for
    preventing abrupt boundary effects.

    FIXED_WINDOW counts requests in discrete time intervals (e.g., per minute).
    Simple and memory-efficient, but susceptible to burst-at-boundary effects
    where 2x the limit can be sent at a window boundary.

    ADAPTIVE_ML combines token bucket with real-time traffic pattern analysis
    using the ML model to dynamically adjust limits. The engine detects
    NORMAL, BURST, SUSTAINED_HIGH, SPIKE, and LOW patterns and adjusts
    the effective rate limit accordingly.
    """

    TOKEN_BUCKET = "TOKEN_BUCKET"
    SLIDING_WINDOW = "SLIDING_WINDOW"
    FIXED_WINDOW = "FIXED_WINDOW"
    ADAPTIVE_ML = "ADAPTIVE_ML"


class TrafficPattern(str, Enum):
    """Observed traffic pattern classification for adaptive rate limiting.

    The ML model classifies incoming traffic into one of these patterns,
    which the adaptive rate limiting engine uses to adjust limits dynamically:

    NORMAL: Steady, predictable request rate within expected bounds.
        Rate limits remain at their configured baseline.

    BURST: Short-lived spike in request rate, typically from a legitimate
        user performing a batch operation. The engine temporarily increases
        the burst allowance while monitoring for sustained elevation.

    SUSTAINED_HIGH: Prolonged high request rate that exceeds the baseline
        for an extended period. The engine may tighten limits proactively
        to prevent resource exhaustion.

    SPIKE: Sudden, dramatic increase in request rate that may indicate
        an attack or runaway client. The engine applies stricter limits
        and may trigger alerting.

    LOW: Request rate well below the configured limit. The engine may
        relax limits slightly to reduce unnecessary throttling overhead.
    """

    NORMAL = "NORMAL"
    BURST = "BURST"
    SUSTAINED_HIGH = "SUSTAINED_HIGH"
    SPIKE = "SPIKE"
    LOW = "LOW"


@dataclass(frozen=True)
class RateLimitKey:
    """Composite key that identifies a rate-limited entity.

    The key combines client identity (client_id), the API route being accessed,
    the HTTP method, and optional custom tags for dimensional rate limiting.
    Together these dimensions define a unique rate limit scope — for example,
    client "user-42" making GET requests to "/api/v1/products" with tag
    {"tier": "premium"} would be rate-limited independently from the same
    client making POST requests to a different endpoint.

    The frozen dataclass ensures immutability, which is critical for using
    keys as dictionary entries and for thread-safe sharing across the
    rate limiting engine's concurrent request processing.
    """

    client_id: str
    route: str = ""
    method: str = ""
    custom_tags: dict[str, str] = field(default_factory=dict)

    def to_compound_key(self) -> str:
        """Produce a deterministic string representation for storage lookup.

        The compound key format ensures that different dimension combinations
        produce distinct keys while remaining human-readable for debugging.
        Tags are sorted by key to guarantee deterministic ordering regardless
        of insertion order.

        Returns:
            A string in the format "client_id:route:method:k1=v1;k2=v2".
        """
        tag_part = ";".join(f"{k}={v}" for k, v in sorted(self.custom_tags.items()))
        return f"{self.client_id}:{self.route}:{self.method}:{tag_part}"


@dataclass
class RateLimitRule:
    """Configuration for a rate limit policy.

    A rule defines the maximum number of requests allowed within a time window,
    the enforcement strategy, burst tolerance, and priority for conflict
    resolution when multiple rules match the same key.

    Attributes:
        rule_id: Unique identifier for the rule, auto-generated if not provided.
        name: Human-readable name for observability and configuration management.
        max_requests: Maximum number of requests allowed within the window.
        window_seconds: Duration of the rate limit window in seconds.
        strategy: The algorithm used to enforce the rate limit.
        burst_multiplier: For TOKEN_BUCKET and ADAPTIVE_ML strategies, this
            multiplier determines the maximum burst size relative to max_requests.
            A value of 2.0 allows up to 2x max_requests in a single burst.
        priority: Numeric priority for rule conflict resolution. Higher values
            take precedence when multiple rules match the same key.
    """

    rule_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    max_requests: int = 100
    window_seconds: int = 60
    strategy: RateLimitStrategy = RateLimitStrategy.TOKEN_BUCKET
    burst_multiplier: float = 1.5
    priority: int = 0

    @property
    def refill_rate(self) -> float:
        """Calculate the token refill rate (tokens per second).

        For token bucket strategies, this determines how quickly tokens
        are replenished. The rate is derived from max_requests divided by
        window_seconds, providing a steady replenishment that enforces
        the average rate over time.

        Returns:
            Tokens replenished per second as a float.
        """
        if self.window_seconds <= 0:
            return 0.0
        return self.max_requests / self.window_seconds

    @property
    def max_burst(self) -> int:
        """Calculate the maximum burst size for token bucket strategies.

        The burst capacity is max_requests multiplied by the burst_multiplier,
        allowing temporary spikes above the steady-state rate. This is the
        maximum number of tokens the bucket can hold.

        Returns:
            Maximum burst capacity as an integer.
        """
        return int(self.max_requests * self.burst_multiplier)

    def effective_limit_for_pattern(self, pattern: TrafficPattern) -> int:
        """Adjust the rate limit based on the detected traffic pattern.

        The adaptive ML strategy uses this method to dynamically adjust
        limits based on real-time traffic analysis. Each pattern applies
        a different multiplier to the base max_requests:

        - NORMAL: No adjustment (1.0x)
        - BURST: Temporary increase to accommodate legitimate bursts (1.5x)
        - SUSTAINED_HIGH: Tighten limits to prevent resource exhaustion (0.7x)
        - SPIKE: Apply strict limits to protect against attacks (0.5x)
        - LOW: Relax limits slightly to reduce unnecessary throttling (1.2x)

        Args:
            pattern: The detected traffic pattern for the key.

        Returns:
            The adjusted maximum request count.
        """
        pattern_multipliers: dict[TrafficPattern, float] = {
            TrafficPattern.NORMAL: 1.0,
            TrafficPattern.BURST: 1.5,
            TrafficPattern.SUSTAINED_HIGH: 0.7,
            TrafficPattern.SPIKE: 0.5,
            TrafficPattern.LOW: 1.2,
        }
        multiplier = pattern_multipliers.get(pattern, 1.0)
        return max(1, int(self.max_requests * multiplier))


@dataclass
class TokenBucketState:
    """Mutable state of a token bucket for rate limiting.

    The token bucket algorithm maintains a pool of tokens that is replenished
    at a steady rate. Each request consumes one token. When the bucket is
    empty, requests are denied until enough tokens have been refilled.

    This dataclass holds the mutable state that must be persisted across
    requests. The refill calculation is idempotent: given the same
    last_refill_at timestamp, the same number of tokens will be computed.

    Attributes:
        key: The compound rate limit key this bucket belongs to.
        tokens: Current number of available tokens in the bucket.
        max_tokens: Maximum bucket capacity (equals the burst size).
        last_refill_at: Timestamp of the last token refill calculation.
        refill_rate: Tokens added per second during refill.
    """

    key: str = ""
    tokens: float = 0.0
    max_tokens: float = 0.0
    last_refill_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    refill_rate: float = 0.0

    def is_empty(self) -> bool:
        """Check whether the bucket has no available tokens.

        Returns:
            True if tokens <= 0, False otherwise.
        """
        return self.tokens <= 0.0

    def has_capacity(self, count: int = 1) -> bool:
        """Check whether the bucket has enough tokens for the given count.

        Args:
            count: Number of tokens required.

        Returns:
            True if tokens >= count, False otherwise.
        """
        return self.tokens >= count

    def consume(self, count: int = 1) -> None:
        """Consume tokens from the bucket.

        Should only be called after confirming has_capacity() returns True.
        Does not enforce the capacity check to avoid double computation in
        the hot path.

        Args:
            count: Number of tokens to consume.
        """
        self.tokens = max(0.0, self.tokens - count)


@dataclass(frozen=True)
class RateLimitStatus:
    """Result of a rate limit check for a single request.

    This immutable value object captures the complete outcome of a rate limit
    evaluation, including whether the request is allowed, remaining capacity,
    the applicable limit, and timing information for the Retry-After header.

    The frozen dataclass ensures that status results cannot be modified after
    creation, preventing accidental mutation in concurrent processing pipelines.

    Attributes:
        key: The rate limit key that was checked.
        allowed: Whether the request is permitted under the rate limit.
        remaining: Number of requests remaining in the current window.
        limit: The effective maximum request count for the current window.
        reset_at: Timestamp when the rate limit window resets and the
            full quota becomes available again.
        retry_after_ms: Milliseconds until the client should retry, if
            the request was denied. Zero if the request was allowed.
        rule_id: Identifier of the rate limit rule that was applied.
    """

    key: str = ""
    allowed: bool = True
    remaining: int = 0
    limit: int = 0
    reset_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    retry_after_ms: int = 0
    rule_id: str = ""

    def to_headers(self) -> dict[str, str]:
        """Convert the rate limit status to standard HTTP response headers.

        Produces the headers specified by IETF RFC drafts for rate limiting:
        X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset, and
        Retry-After (when the request is denied).

        Returns:
            Dictionary of HTTP header names to string values.
        """
        headers: dict[str, str] = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(remaining := self.remaining),
            "X-RateLimit-Reset": str(int(self.reset_at.timestamp())),
        }
        if not self.allowed and self.retry_after_ms > 0:
            headers["Retry-After"] = str(max(1, self.retry_after_ms // 1000))
        return headers
