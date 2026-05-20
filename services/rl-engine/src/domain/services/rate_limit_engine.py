"""
Core rate limiting engine service for the RL Engine.

This module implements the central rate limiting engine that coordinates
all rate limit checking, request recording, and traffic pattern analysis.
The engine supports four rate limiting strategies — Token Bucket, Sliding
Window, Fixed Window, and Adaptive ML — and delegates state persistence
to the outbound RateLimitStorePort.

The engine is designed for correctness under concurrent access by relying
on the store adapter's atomicity guarantees (e.g., Redis Lua scripts or
PostgreSQL serializable transactions). The domain logic itself remains
stateless between requests; all mutable state lives in the store.

Traffic pattern analysis uses a sliding-window request counter to classify
traffic as NORMAL, BURST, SUSTAINED_HIGH, SPIKE, or LOW. For the ADAPTIVE_ML
strategy, this classification drives dynamic limit adjustments via
RateLimitRule.effective_limit_for_pattern().
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from ..models.rate_limit import (
    RateLimitKey,
    RateLimitRule,
    RateLimitStatus,
    RateLimitStrategy,
    TokenBucketState,
    TrafficPattern,
)
from ..ports.inbound.check_rate_limit import (
    CheckRateLimitPort,
    GetTrafficPatternPort,
    RecordRequestPort,
)
from ..ports.outbound.rate_limit_store import RateLimitStorePort

logger = logging.getLogger(__name__)


class RateLimitEngine(CheckRateLimitPort, RecordRequestPort, GetTrafficPatternPort):
    """Core rate limiting engine with ML-based adaptive pattern detection.

    This engine implements four rate limiting strategies and provides
    traffic pattern analysis for the Adaptive ML strategy. It depends
    only on the RateLimitStorePort for state persistence, maintaining
    the hexagonal architecture boundary.

    The engine is stateless between requests — all mutable rate limit
    state (token buckets, counters) is persisted via the store port.
    This enables horizontal scaling with shared state backends like Redis.

    Usage::

        store = RedisRateLimitStore(redis_client)
        engine = RateLimitEngine(store=store)

        key = RateLimitKey(client_id="user-42", route="/api/v1/products", method="GET")
        rule = RateLimitRule(max_requests=100, window_seconds=60, strategy=RateLimitStrategy.TOKEN_BUCKET)

        status = engine.check_rate_limit(key, rule)
        if not status.allowed:
            # Return 429 with Retry-After header
            ...
    """

    # Traffic analysis configuration
    _PATTERN_WINDOW_SECONDS: int = 60
    _PATTERN_BURST_RATIO: float = 2.0       # Requests/sec > 2x average → BURST
    _PATTERN_SPIKE_RATIO: float = 5.0       # Requests/sec > 5x average → SPIKE
    _PATTERN_SUSTAINED_RATIO: float = 1.5   # Sustained > 1.5x for 5+ windows → SUSTAINED_HIGH
    _PATTERN_LOW_RATIO: float = 0.3         # Requests/sec < 0.3x average → LOW
    _PATTERN_SUSTAINED_WINDOWS: int = 5     # Number of consecutive windows for SUSTAINED_HIGH

    def __init__(self, store: RateLimitStorePort) -> None:
        """Initialize the rate limiting engine with a state store.

        Args:
            store: The outbound port for persisting rate limit state.
                Must provide atomic read-modify-write semantics for
                correct concurrent operation.
        """
        self._store = store
        # In-memory request history for pattern analysis.
        # Keyed by compound key string; values are lists of (timestamp, allowed) tuples.
        self._request_history: dict[str, list[tuple[datetime, bool]]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Inbound port implementations
    # ------------------------------------------------------------------

    def check(self, key: RateLimitKey, rule: RateLimitRule) -> RateLimitStatus:
        """Inbound port implementation for CheckRateLimitPort.

        Delegates to check_rate_limit() which dispatches to the
        appropriate strategy-specific check method.
        """
        return self.check_rate_limit(key, rule)

    def record(self, key: RateLimitKey, allowed: bool) -> None:
        """Inbound port implementation for RecordRequestPort.

        Delegates to record_request() which maintains the request
        history for traffic pattern analysis.
        """
        self.record_request(key, allowed)

    def get_pattern(self, key: RateLimitKey) -> TrafficPattern:
        """Inbound port implementation for GetTrafficPatternPort.

        Delegates to analyze_traffic_pattern() which classifies the
        current traffic pattern for the given key.
        """
        return self.analyze_traffic_pattern(key)

    # ------------------------------------------------------------------
    # Core rate limiting methods
    # ------------------------------------------------------------------

    def check_rate_limit(self, key: RateLimitKey, rule: RateLimitRule) -> RateLimitStatus:
        """Check whether a request is allowed under the given rate limit rule.

        Dispatches to the appropriate strategy-specific check method based on
        the rule's strategy field. For ADAPTIVE_ML, the effective limit is
        first adjusted based on the current traffic pattern before applying
        the token bucket algorithm.

        Args:
            key: The composite rate limit key identifying the client/route/method.
            rule: The rate limit rule to apply.

        Returns:
            A RateLimitStatus indicating whether the request is allowed,
            remaining capacity, reset time, and retry-after if denied.
        """
        compound_key = key.to_compound_key()

        if rule.strategy == RateLimitStrategy.TOKEN_BUCKET:
            return self._check_token_bucket(compound_key, rule)
        elif rule.strategy == RateLimitStrategy.SLIDING_WINDOW:
            return self._check_sliding_window(compound_key, rule)
        elif rule.strategy == RateLimitStrategy.FIXED_WINDOW:
            return self._check_fixed_window(compound_key, rule)
        elif rule.strategy == RateLimitStrategy.ADAPTIVE_ML:
            return self._check_adaptive_ml(key, compound_key, rule)
        else:
            logger.warning(
                "unknown rate limit strategy, falling back to token bucket",
                extra={"strategy": rule.strategy, "rule_id": rule.rule_id},
            )
            return self._check_token_bucket(compound_key, rule)

    def record_request(self, key: RateLimitKey, allowed: bool) -> None:
        """Record a request outcome for traffic pattern analysis.

        This method must be called after every rate limit check to maintain
        the request history used by analyze_traffic_pattern(). The recorded
        data feeds the ML-based adaptive rate limiting by providing the
        temporal distribution of requests.

        Old entries outside the analysis window are pruned to bound memory
        usage. In a production deployment with multiple engine instances,
        this history would be shared via the store port or a dedicated
        analytics pipeline.

        Args:
            key: The rate limit key for the request.
            allowed: Whether the request was allowed by the rate limiter.
        """
        compound_key = key.to_compound_key()
        now = datetime.now(timezone.utc)

        self._request_history[compound_key].append((now, allowed))

        # Prune entries older than the analysis window to bound memory.
        cutoff = now - timedelta(seconds=self._PATTERN_WINDOW_SECONDS * 2)
        self._request_history[compound_key] = [
            (ts, a) for ts, a in self._request_history[compound_key]
            if ts > cutoff
        ]

    def analyze_traffic_pattern(self, key: RateLimitKey) -> TrafficPattern:
        """Analyze recent traffic to classify the current pattern.

        Examines the request history for the given key over the analysis
        window and classifies the traffic pattern based on rate changes.
        This classification drives the ADAPTIVE_ML strategy's dynamic
        limit adjustments.

        The analysis algorithm:
        1. Compute the requests-per-second rate for the current window.
        2. Compute the average rate over recent windows for comparison.
        3. Classify based on the ratio of current rate to average rate:
           - SPIKE: Current rate > 5x average
           - BURST: Current rate > 2x average
           - SUSTAINED_HIGH: Rate > 1.5x average for 5+ consecutive windows
           - LOW: Current rate < 0.3x average
           - NORMAL: None of the above

        Args:
            key: The rate limit key to analyze.

        Returns:
            The detected TrafficPattern for the key.
        """
        compound_key = key.to_compound_key()
        now = datetime.now(timezone.utc)
        history = self._request_history.get(compound_key, [])

        if not history:
            return TrafficPattern.LOW

        # Filter to the analysis window.
        window_start = now - timedelta(seconds=self._PATTERN_WINDOW_SECONDS)
        recent_requests = [(ts, a) for ts, a in history if ts > window_start]

        if not recent_requests:
            return TrafficPattern.LOW

        # Compute current requests per second.
        current_rate = len(recent_requests) / self._PATTERN_WINDOW_SECONDS

        # If we have enough history, compare against a longer baseline.
        baseline_start = now - timedelta(seconds=self._PATTERN_WINDOW_SECONDS * 2)
        baseline_requests = [(ts, a) for ts, a in history if ts > baseline_start]
        baseline_window = self._PATTERN_WINDOW_SECONDS * 2
        baseline_rate = len(baseline_requests) / baseline_window if baseline_requests else current_rate

        # Avoid division by zero for new keys.
        if baseline_rate == 0:
            if current_rate > 0:
                return TrafficPattern.BURST
            return TrafficPattern.LOW

        ratio = current_rate / baseline_rate

        # Check for sustained high traffic over multiple windows.
        # We approximate by checking if recent history shows consistently high rates.
        window_count = self._count_high_rate_windows(compound_key, now, baseline_rate)
        if window_count >= self._PATTERN_SUSTAINED_WINDOWS and ratio > self._PATTERN_SUSTAINED_RATIO:
            return TrafficPattern.SUSTAINED_HIGH

        if ratio > self._PATTERN_SPIKE_RATIO:
            return TrafficPattern.SPIKE

        if ratio > self._PATTERN_BURST_RATIO:
            return TrafficPattern.BURST

        if ratio < self._PATTERN_LOW_RATIO:
            return TrafficPattern.LOW

        return TrafficPattern.NORMAL

    def _refill_tokens(self, bucket: TokenBucketState) -> TokenBucketState:
        """Refill tokens in a token bucket based on elapsed time.

        The refill algorithm calculates how many tokens should be added
        based on the time elapsed since the last refill, capped at the
        bucket's maximum capacity. This ensures that the bucket gradually
        recovers after being drained, allowing new requests to be served
        once sufficient tokens have accumulated.

        The refill is computed as:
            tokens_to_add = elapsed_seconds * refill_rate
            new_tokens = min(current_tokens + tokens_to_add, max_tokens)

        Args:
            bucket: The current token bucket state.

        Returns:
            A new TokenBucketState with refilled tokens and updated timestamp.
        """
        now = datetime.now(timezone.utc)
        elapsed = (now - bucket.last_refill_at).total_seconds()

        if elapsed <= 0:
            return bucket

        tokens_to_add = elapsed * bucket.refill_rate
        new_tokens = min(bucket.tokens + tokens_to_add, bucket.max_tokens)

        return TokenBucketState(
            key=bucket.key,
            tokens=new_tokens,
            max_tokens=bucket.max_tokens,
            last_refill_at=now,
            refill_rate=bucket.refill_rate,
        )

    # ------------------------------------------------------------------
    # Strategy-specific check methods
    # ------------------------------------------------------------------

    def _check_token_bucket(self, key: str, rule: RateLimitRule) -> RateLimitStatus:
        """Check rate limit using the Token Bucket algorithm.

        Token bucket allows bursts up to max_burst tokens, with tokens
        replenished at a steady rate (max_requests / window_seconds).

        Args:
            key: The compound key for the rate limit scope.
            rule: The rate limit rule defining the bucket parameters.

        Returns:
            RateLimitStatus with the check result.
        """
        bucket = self._store.get_bucket(key)

        if bucket is None:
            # Initialize a new bucket with full capacity.
            bucket = TokenBucketState(
                key=key,
                tokens=float(rule.max_burst),
                max_tokens=float(rule.max_burst),
                last_refill_at=datetime.now(timezone.utc),
                refill_rate=rule.refill_rate,
            )

        # Refill tokens based on elapsed time.
        bucket = self._refill_tokens(bucket)

        # Check capacity and consume a token if allowed.
        if bucket.has_capacity(1):
            bucket.consume(1)
            self._store.save_bucket(bucket)
            now = datetime.now(timezone.utc)
            reset_at = now + timedelta(
                seconds=math.ceil((bucket.max_tokens - bucket.tokens) / bucket.refill_rate)
                if bucket.refill_rate > 0 else rule.window_seconds
            )
            return RateLimitStatus(
                key=key,
                allowed=True,
                remaining=int(bucket.tokens),
                limit=rule.max_requests,
                reset_at=reset_at,
                retry_after_ms=0,
                rule_id=rule.rule_id,
            )
        else:
            # Request denied — calculate retry-after.
            now = datetime.now(timezone.utc)
            tokens_needed = 1.0 - bucket.tokens
            retry_seconds = tokens_needed / bucket.refill_rate if bucket.refill_rate > 0 else float(rule.window_seconds)
            retry_ms = max(1, int(retry_seconds * 1000))
            reset_at = now + timedelta(seconds=math.ceil(retry_seconds))

            return RateLimitStatus(
                key=key,
                allowed=False,
                remaining=0,
                limit=rule.max_requests,
                reset_at=reset_at,
                retry_after_ms=retry_ms,
                rule_id=rule.rule_id,
            )

    def _check_sliding_window(self, key: str, rule: RateLimitRule) -> RateLimitStatus:
        """Check rate limit using the Sliding Window algorithm.

        Sliding window provides smoother rate enforcement than fixed windows
        by tracking the exact count of requests within a continuously moving
        time window. This avoids the boundary-doubling problem of fixed windows.

        The implementation uses the store's increment_counter with the rule's
        window_seconds to maintain a sliding count. Each increment returns the
        current count within the window, and the count is compared against
        max_requests.

        Args:
            key: The compound key for the rate limit scope.
            rule: The rate limit rule defining the window parameters.

        Returns:
            RateLimitStatus with the check result.
        """
        current_count = self._store.increment_counter(key, rule.window_seconds)
        now = datetime.now(timezone.utc)
        reset_at = now + timedelta(seconds=rule.window_seconds)

        if current_count <= rule.max_requests:
            remaining = max(0, rule.max_requests - current_count)
            return RateLimitStatus(
                key=key,
                allowed=True,
                remaining=remaining,
                limit=rule.max_requests,
                reset_at=reset_at,
                retry_after_ms=0,
                rule_id=rule.rule_id,
            )
        else:
            # Calculate retry-after based on when the oldest request in the
            # window will expire.
            retry_ms = max(1, int(rule.window_seconds / rule.max_requests * 1000))
            return RateLimitStatus(
                key=key,
                allowed=False,
                remaining=0,
                limit=rule.max_requests,
                reset_at=reset_at,
                retry_after_ms=retry_ms,
                rule_id=rule.rule_id,
            )

    def _check_fixed_window(self, key: str, rule: RateLimitRule) -> RateLimitStatus:
        """Check rate limit using the Fixed Window algorithm.

        Fixed window counts requests in discrete time intervals aligned to
        clock boundaries. For example, with a 60-second window, the counter
        resets at the start of each minute. This is the simplest strategy
        but susceptible to burst-at-boundary effects where 2x the limit
        can be sent at a window transition.

        The window alignment is based on the current time divided by the
        window duration, producing a window ID that changes at regular
        intervals. The counter is scoped to a specific window ID.

        Args:
            key: The compound key for the rate limit scope.
            rule: The rate limit rule defining the window parameters.

        Returns:
            RateLimitStatus with the check result.
        """
        # Align the key to the current fixed window.
        now = datetime.now(timezone.utc)
        window_id = int(now.timestamp()) // rule.window_seconds
        window_key = f"{key}:w{window_id}"

        current_count = self._store.increment_counter(window_key, rule.window_seconds)

        # Calculate when the current window resets.
        window_start_ts = window_id * rule.window_seconds
        reset_at = datetime.fromtimestamp(window_start_ts + rule.window_seconds, tz=timezone.utc)

        if current_count <= rule.max_requests:
            remaining = max(0, rule.max_requests - current_count)
            return RateLimitStatus(
                key=key,
                allowed=True,
                remaining=remaining,
                limit=rule.max_requests,
                reset_at=reset_at,
                retry_after_ms=0,
                rule_id=rule.rule_id,
            )
        else:
            retry_ms = max(1, int((reset_at - now).total_seconds() * 1000))
            return RateLimitStatus(
                key=key,
                allowed=False,
                remaining=0,
                limit=rule.max_requests,
                reset_at=reset_at,
                retry_after_ms=retry_ms,
                rule_id=rule.rule_id,
            )

    def _check_adaptive_ml(
        self,
        key: RateLimitKey,
        compound_key: str,
        rule: RateLimitRule,
    ) -> RateLimitStatus:
        """Check rate limit using the Adaptive ML strategy.

        The Adaptive ML strategy combines token bucket rate limiting with
        real-time traffic pattern analysis. Before checking the token bucket,
        it analyzes the current traffic pattern and adjusts the effective
        limit accordingly. This allows the system to:

        - Allow legitimate bursts from well-behaved clients (BURST → 1.5x)
        - Protect against attacks and runaway clients (SPIKE → 0.5x)
        - Prevent resource exhaustion from sustained high traffic (SUSTAINED_HIGH → 0.7x)
        - Relax limits during low traffic periods (LOW → 1.2x)

        The adjusted rule is then applied using the token bucket algorithm,
        providing both burst tolerance and smooth rate enforcement.

        Args:
            key: The composite rate limit key.
            compound_key: The string representation of the key.
            rule: The original rate limit rule.

        Returns:
            RateLimitStatus with the check result.
        """
        pattern = self.analyze_traffic_pattern(key)
        effective_max = rule.effective_limit_for_pattern(pattern)

        # Create an adjusted rule with the effective limit for pattern.
        adjusted_rule = RateLimitRule(
            rule_id=rule.rule_id,
            name=rule.name,
            max_requests=effective_max,
            window_seconds=rule.window_seconds,
            strategy=RateLimitStrategy.TOKEN_BUCKET,
            burst_multiplier=rule.burst_multiplier,
            priority=rule.priority,
        )

        status = self._check_token_bucket(compound_key, adjusted_rule)

        # Include pattern information in the status for observability.
        # The status itself is immutable, so we log the pattern for now.
        logger.debug(
            "adaptive_ml_rate_limit_check",
            extra={
                "key": compound_key,
                "pattern": pattern.value,
                "original_limit": rule.max_requests,
                "effective_limit": effective_max,
                "allowed": status.allowed,
            },
        )

        return status

    # ------------------------------------------------------------------
    # Pattern analysis helpers
    # ------------------------------------------------------------------

    def _count_high_rate_windows(
        self,
        compound_key: str,
        now: datetime,
        baseline_rate: float,
    ) -> int:
        """Count consecutive recent windows with above-baseline request rates.

        Divides the recent request history into sub-windows and counts how
        many consecutive sub-windows have a rate exceeding the sustained
        high threshold relative to the baseline.

        Args:
            compound_key: The compound key to analyze.
            now: The current timestamp.
            baseline_rate: The average request rate for comparison.

        Returns:
            Number of consecutive high-rate sub-windows.
        """
        history = self._request_history.get(compound_key, [])
        if not history:
            return 0

        sub_window_seconds = self._PATTERN_WINDOW_SECONDS // self._PATTERN_SUSTAINED_WINDOWS
        if sub_window_seconds <= 0:
            return 0

        consecutive = 0
        threshold = baseline_rate * self._PATTERN_SUSTAINED_RATIO

        for i in range(self._PATTERN_SUSTAINED_WINDOWS):
            window_end = now - timedelta(seconds=i * sub_window_seconds)
            window_start = window_end - timedelta(seconds=sub_window_seconds)

            count = sum(
                1 for ts, _ in history
                if window_start < ts <= window_end
            )
            rate = count / sub_window_seconds

            if rate > threshold:
                consecutive += 1
            else:
                break  # Consecutive count breaks at first non-high window.

        return consecutive
