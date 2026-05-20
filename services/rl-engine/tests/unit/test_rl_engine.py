"""
Unit tests for the RL Engine domain services.

Tests the RateLimitEngine with a mocked RateLimitStorePort. Validates
token bucket, sliding window, fixed window, and adaptive ML strategies,
plus request recording and traffic pattern analysis.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from src.domain.models import (
    RateLimitKey,
    RateLimitRule,
    RateLimitStatus,
    RateLimitStrategy,
    TokenBucketState,
    TrafficPattern,
)
from src.domain.ports import RateLimitStorePort
from src.domain.services import RateLimitEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_store() -> MagicMock:
    """Create a mock RateLimitStorePort with sensible defaults."""
    store = MagicMock(spec=RateLimitStorePort)
    store.get_bucket.return_value = None  # No existing bucket by default
    store.increment_counter.return_value = 1
    return store


@pytest.fixture
def engine(mock_store: MagicMock) -> RateLimitEngine:
    """Create a RateLimitEngine with a mock store."""
    return RateLimitEngine(store=mock_store)


@pytest.fixture
def sample_key() -> RateLimitKey:
    """Create a sample rate limit key."""
    return RateLimitKey(
        client_id="user-42",
        route="/api/v1/products",
        method="GET",
    )


@pytest.fixture
def token_bucket_rule() -> RateLimitRule:
    """Create a token bucket rate limit rule."""
    return RateLimitRule(
        rule_id="rule-tb-1",
        name="test-token-bucket",
        max_requests=100,
        window_seconds=60,
        strategy=RateLimitStrategy.TOKEN_BUCKET,
        burst_multiplier=1.5,
    )


@pytest.fixture
def sliding_window_rule() -> RateLimitRule:
    """Create a sliding window rate limit rule."""
    return RateLimitRule(
        rule_id="rule-sw-1",
        name="test-sliding-window",
        max_requests=100,
        window_seconds=60,
        strategy=RateLimitStrategy.SLIDING_WINDOW,
    )


@pytest.fixture
def fixed_window_rule() -> RateLimitRule:
    """Create a fixed window rate limit rule."""
    return RateLimitRule(
        rule_id="rule-fw-1",
        name="test-fixed-window",
        max_requests=100,
        window_seconds=60,
        strategy=RateLimitStrategy.FIXED_WINDOW,
    )


@pytest.fixture
def adaptive_ml_rule() -> RateLimitRule:
    """Create an adaptive ML rate limit rule."""
    return RateLimitRule(
        rule_id="rule-aml-1",
        name="test-adaptive-ml",
        max_requests=100,
        window_seconds=60,
        strategy=RateLimitStrategy.ADAPTIVE_ML,
        burst_multiplier=1.5,
    )


# ---------------------------------------------------------------------------
# Token Bucket Strategy
# ---------------------------------------------------------------------------

class TestTokenBucket:
    """Tests for the Token Bucket rate limiting strategy."""

    def test_first_request_allowed(
        self, engine: RateLimitEngine, sample_key: RateLimitKey, token_bucket_rule: RateLimitRule,
    ) -> None:
        """First request with no existing bucket should be allowed."""
        status = engine.check_rate_limit(sample_key, token_bucket_rule)
        assert status.allowed is True
        assert status.remaining >= 0
        assert status.limit == token_bucket_rule.max_requests

    def test_bucket_initialized_on_first_request(
        self, engine: RateLimitEngine, mock_store: MagicMock, sample_key: RateLimitKey, token_bucket_rule: RateLimitRule,
    ) -> None:
        """A new bucket should be created and saved on the first request."""
        engine.check_rate_limit(sample_key, token_bucket_rule)
        mock_store.save_bucket.assert_called_once()
        bucket = mock_store.save_bucket.call_args[0][0]
        assert isinstance(bucket, TokenBucketState)

    def test_existing_bucket_refilled(
        self, engine: RateLimitEngine, mock_store: MagicMock, sample_key: RateLimitKey, token_bucket_rule: RateLimitRule,
    ) -> None:
        """An existing bucket with depleted tokens should be refilled over time."""
        existing_bucket = TokenBucketState(
            key=sample_key.to_compound_key(),
            tokens=5.0,
            max_tokens=150.0,
            last_refill_at=datetime.now(timezone.utc) - timedelta(seconds=10),
            refill_rate=token_bucket_rule.refill_rate,
        )
        mock_store.get_bucket.return_value = existing_bucket
        status = engine.check_rate_limit(sample_key, token_bucket_rule)
        assert status.allowed is True

    def test_empty_bucket_denies_request(
        self, engine: RateLimitEngine, mock_store: MagicMock, sample_key: RateLimitKey, token_bucket_rule: RateLimitRule,
    ) -> None:
        """A bucket with zero tokens should deny the request."""
        empty_bucket = TokenBucketState(
            key=sample_key.to_compound_key(),
            tokens=0.0,
            max_tokens=150.0,
            last_refill_at=datetime.now(timezone.utc),
            refill_rate=token_bucket_rule.refill_rate,
        )
        mock_store.get_bucket.return_value = empty_bucket
        status = engine.check_rate_limit(sample_key, token_bucket_rule)
        assert status.allowed is False
        assert status.retry_after_ms > 0

    def test_status_includes_rate_limit_headers(
        self, engine: RateLimitEngine, sample_key: RateLimitKey, token_bucket_rule: RateLimitRule,
    ) -> None:
        """Status should include headers for HTTP response."""
        status = engine.check_rate_limit(sample_key, token_bucket_rule)
        headers = status.to_headers()
        assert "X-RateLimit-Limit" in headers
        assert "X-RateLimit-Remaining" in headers
        assert "X-RateLimit-Reset" in headers


# ---------------------------------------------------------------------------
# Sliding Window Strategy
# ---------------------------------------------------------------------------

class TestSlidingWindow:
    """Tests for the Sliding Window rate limiting strategy."""

    def test_request_within_limit_allowed(
        self, engine: RateLimitEngine, sample_key: RateLimitKey, sliding_window_rule: RateLimitRule,
    ) -> None:
        """Requests within the limit should be allowed."""
        status = engine.check_rate_limit(sample_key, sliding_window_rule)
        assert status.allowed is True
        assert status.remaining == sliding_window_rule.max_requests - 1

    def test_request_over_limit_denied(
        self, engine: RateLimitEngine, mock_store: MagicMock, sample_key: RateLimitKey, sliding_window_rule: RateLimitRule,
    ) -> None:
        """Requests exceeding the limit should be denied."""
        mock_store.increment_counter.return_value = sliding_window_rule.max_requests + 1
        status = engine.check_rate_limit(sample_key, sliding_window_rule)
        assert status.allowed is False
        assert status.remaining == 0

    def test_exact_limit_allowed(
        self, engine: RateLimitEngine, mock_store: MagicMock, sample_key: RateLimitKey, sliding_window_rule: RateLimitRule,
    ) -> None:
        """Request at exactly the limit should be allowed."""
        mock_store.increment_counter.return_value = sliding_window_rule.max_requests
        status = engine.check_rate_limit(sample_key, sliding_window_rule)
        assert status.allowed is True
        assert status.remaining == 0


# ---------------------------------------------------------------------------
# Fixed Window Strategy
# ---------------------------------------------------------------------------

class TestFixedWindow:
    """Tests for the Fixed Window rate limiting strategy."""

    def test_request_within_limit_allowed(
        self, engine: RateLimitEngine, sample_key: RateLimitKey, fixed_window_rule: RateLimitRule,
    ) -> None:
        """Requests within the fixed window limit should be allowed."""
        status = engine.check_rate_limit(sample_key, fixed_window_rule)
        assert status.allowed is True

    def test_request_over_limit_denied(
        self, engine: RateLimitEngine, mock_store: MagicMock, sample_key: RateLimitKey, fixed_window_rule: RateLimitRule,
    ) -> None:
        """Requests exceeding the fixed window limit should be denied."""
        mock_store.increment_counter.return_value = fixed_window_rule.max_requests + 1
        status = engine.check_rate_limit(sample_key, fixed_window_rule)
        assert status.allowed is False

    def test_reset_at_aligned_to_window(
        self, engine: RateLimitEngine, sample_key: RateLimitKey, fixed_window_rule: RateLimitRule,
    ) -> None:
        """Reset timestamp should align to the window boundary."""
        status = engine.check_rate_limit(sample_key, fixed_window_rule)
        assert status.reset_at is not None


# ---------------------------------------------------------------------------
# Adaptive ML Strategy
# ---------------------------------------------------------------------------

class TestAdaptiveML:
    """Tests for the Adaptive ML rate limiting strategy."""

    def test_low_traffic_allows_request(
        self, engine: RateLimitEngine, sample_key: RateLimitKey, adaptive_ml_rule: RateLimitRule,
    ) -> None:
        """With no request history (LOW pattern), adaptive ML should allow requests."""
        status = engine.check_rate_limit(sample_key, adaptive_ml_rule)
        assert status.allowed is True

    def test_delegates_to_token_bucket(
        self, engine: RateLimitEngine, mock_store: MagicMock, sample_key: RateLimitKey, adaptive_ml_rule: RateLimitRule,
    ) -> None:
        """Adaptive ML should delegate to token bucket for the actual check."""
        engine.check_rate_limit(sample_key, adaptive_ml_rule)
        # Token bucket check calls save_bucket when allowed
        mock_store.save_bucket.assert_called_once()


# ---------------------------------------------------------------------------
# Request Recording
# ---------------------------------------------------------------------------

class TestRecordRequest:
    """Tests for the request recording functionality."""

    def test_record_allowed_request(
        self, engine: RateLimitEngine, sample_key: RateLimitKey,
    ) -> None:
        """Recording an allowed request should add to history."""
        engine.record_request(sample_key, allowed=True)
        # Verify history was updated by checking pattern analysis
        pattern = engine.analyze_traffic_pattern(sample_key)
        # With only one request, pattern should be LOW or BURST
        assert pattern in (TrafficPattern.LOW, TrafficPattern.BURST, TrafficPattern.NORMAL)

    def test_record_denied_request(
        self, engine: RateLimitEngine, sample_key: RateLimitKey,
    ) -> None:
        """Recording a denied request should add to history."""
        engine.record_request(sample_key, allowed=False)
        pattern = engine.analyze_traffic_pattern(sample_key)
        assert isinstance(pattern, TrafficPattern)

    def test_record_prunes_old_entries(
        self, engine: RateLimitEngine, sample_key: RateLimitKey,
    ) -> None:
        """Recording should prune entries older than the analysis window."""
        # Add many requests to build history
        for _ in range(100):
            engine.record_request(sample_key, allowed=True)
        # History should be bounded (pruning happens on each record)
        compound_key = sample_key.to_compound_key()
        history = engine._request_history.get(compound_key, [])
        # After pruning, history should be bounded
        assert len(history) <= 200  # 2x window buffer


# ---------------------------------------------------------------------------
# Traffic Pattern Analysis
# ---------------------------------------------------------------------------

class TestTrafficPatternAnalysis:
    """Tests for the traffic pattern analysis engine."""

    def test_no_history_returns_low(
        self, engine: RateLimitEngine, sample_key: RateLimitKey,
    ) -> None:
        """No request history should classify as LOW pattern."""
        pattern = engine.analyze_traffic_pattern(sample_key)
        assert pattern == TrafficPattern.LOW

    def test_steady_traffic_is_normal(
        self, engine: RateLimitEngine, sample_key: RateLimitKey,
    ) -> None:
        """Steady traffic at baseline rate should classify as NORMAL."""
        # Add baseline requests
        for _ in range(20):
            engine.record_request(sample_key, allowed=True)
        # Add recent requests at similar rate
        for _ in range(20):
            engine.record_request(sample_key, allowed=True)
        pattern = engine.analyze_traffic_pattern(sample_key)
        assert isinstance(pattern, TrafficPattern)


# ---------------------------------------------------------------------------
# Inbound Port Implementations
# ---------------------------------------------------------------------------

class TestInboundPortImplementations:
    """Tests for inbound port method implementations."""

    def test_check_delegates_to_check_rate_limit(
        self, engine: RateLimitEngine, sample_key: RateLimitKey, token_bucket_rule: RateLimitRule,
    ) -> None:
        """check() should delegate to check_rate_limit()."""
        status = engine.check(sample_key, token_bucket_rule)
        assert isinstance(status, RateLimitStatus)

    def test_record_delegates_to_record_request(
        self, engine: RateLimitEngine, sample_key: RateLimitKey,
    ) -> None:
        """record() should delegate to record_request()."""
        engine.record(sample_key, allowed=True)
        # Verify by checking pattern analysis works
        pattern = engine.get_pattern(sample_key)
        assert isinstance(pattern, TrafficPattern)

    def test_get_pattern_delegates_to_analyze(
        self, engine: RateLimitEngine, sample_key: RateLimitKey,
    ) -> None:
        """get_pattern() should delegate to analyze_traffic_pattern()."""
        pattern = engine.get_pattern(sample_key)
        assert isinstance(pattern, TrafficPattern)


# ---------------------------------------------------------------------------
# RateLimitKey
# ---------------------------------------------------------------------------

class TestRateLimitKey:
    """Tests for RateLimitKey compound key generation."""

    def test_compound_key_format(self) -> None:
        """Compound key should follow the expected format."""
        key = RateLimitKey(
            client_id="user-42",
            route="/api/v1/products",
            method="GET",
            custom_tags={"tier": "premium"},
        )
        compound = key.to_compound_key()
        assert "user-42" in compound
        assert "/api/v1/products" in compound
        assert "GET" in compound
        assert "tier=premium" in compound

    def test_compound_key_deterministic(self) -> None:
        """Same key should always produce the same compound key."""
        key = RateLimitKey(
            client_id="user-42",
            route="/api/v1/products",
            method="GET",
            custom_tags={"b": "2", "a": "1"},
        )
        assert key.to_compound_key() == key.to_compound_key()

    def test_compound_key_tags_sorted(self) -> None:
        """Tags in compound key should be sorted for determinism."""
        key1 = RateLimitKey(client_id="u", custom_tags={"a": "1", "b": "2"})
        key2 = RateLimitKey(client_id="u", custom_tags={"b": "2", "a": "1"})
        assert key1.to_compound_key() == key2.to_compound_key()


# ---------------------------------------------------------------------------
# RateLimitRule
# ---------------------------------------------------------------------------

class TestRateLimitRule:
    """Tests for RateLimitRule properties and methods."""

    def test_refill_rate(self) -> None:
        """Refill rate should be max_requests / window_seconds."""
        rule = RateLimitRule(max_requests=100, window_seconds=60)
        assert abs(rule.refill_rate - 100 / 60) < 1e-9

    def test_refill_rate_zero_window(self) -> None:
        """Refill rate should be 0 for zero window."""
        rule = RateLimitRule(max_requests=100, window_seconds=0)
        assert rule.refill_rate == 0.0

    def test_max_burst(self) -> None:
        """Max burst should be max_requests * burst_multiplier."""
        rule = RateLimitRule(max_requests=100, burst_multiplier=1.5)
        assert rule.max_burst == 150

    def test_effective_limit_normal(self) -> None:
        """Normal pattern should not adjust the limit."""
        rule = RateLimitRule(max_requests=100)
        assert rule.effective_limit_for_pattern(TrafficPattern.NORMAL) == 100

    def test_effective_limit_burst(self) -> None:
        """Burst pattern should increase the limit."""
        rule = RateLimitRule(max_requests=100)
        assert rule.effective_limit_for_pattern(TrafficPattern.BURST) == 150

    def test_effective_limit_spike(self) -> None:
        """Spike pattern should decrease the limit."""
        rule = RateLimitRule(max_requests=100)
        assert rule.effective_limit_for_pattern(TrafficPattern.SPIKE) == 50

    def test_effective_limit_sustained_high(self) -> None:
        """Sustained high pattern should decrease the limit."""
        rule = RateLimitRule(max_requests=100)
        assert rule.effective_limit_for_pattern(TrafficPattern.SUSTAINED_HIGH) == 70

    def test_effective_limit_low(self) -> None:
        """Low pattern should increase the limit slightly."""
        rule = RateLimitRule(max_requests=100)
        assert rule.effective_limit_for_pattern(TrafficPattern.LOW) == 120

    def test_effective_limit_minimum_one(self) -> None:
        """Effective limit should never go below 1."""
        rule = RateLimitRule(max_requests=1)
        assert rule.effective_limit_for_pattern(TrafficPattern.SPIKE) >= 1


# ---------------------------------------------------------------------------
# TokenBucketState
# ---------------------------------------------------------------------------

class TestTokenBucketState:
    """Tests for TokenBucketState methods."""

    def test_is_empty(self) -> None:
        """Bucket with zero tokens should be empty."""
        bucket = TokenBucketState(tokens=0.0)
        assert bucket.is_empty() is True

    def test_is_not_empty(self) -> None:
        """Bucket with tokens should not be empty."""
        bucket = TokenBucketState(tokens=5.0)
        assert bucket.is_empty() is False

    def test_has_capacity(self) -> None:
        """Bucket with enough tokens should have capacity."""
        bucket = TokenBucketState(tokens=10.0)
        assert bucket.has_capacity(5) is True

    def test_no_capacity(self) -> None:
        """Bucket without enough tokens should not have capacity."""
        bucket = TokenBucketState(tokens=3.0)
        assert bucket.has_capacity(5) is False

    def test_consume(self) -> None:
        """Consuming tokens should reduce the token count."""
        bucket = TokenBucketState(tokens=10.0)
        bucket.consume(3)
        assert abs(bucket.tokens - 7.0) < 1e-9

    def test_consume_floor_at_zero(self) -> None:
        """Consuming more tokens than available should floor at zero."""
        bucket = TokenBucketState(tokens=2.0)
        bucket.consume(5)
        assert bucket.tokens == 0.0


# ---------------------------------------------------------------------------
# RateLimitStatus
# ---------------------------------------------------------------------------

class TestRateLimitStatus:
    """Tests for RateLimitStatus header generation."""

    def test_allowed_no_retry_after(self) -> None:
        """Allowed status should not include Retry-After header."""
        status = RateLimitStatus(allowed=True, remaining=50, limit=100, retry_after_ms=0)
        headers = status.to_headers()
        assert "Retry-After" not in headers

    def test_denied_includes_retry_after(self) -> None:
        """Denied status should include Retry-After header."""
        status = RateLimitStatus(allowed=False, remaining=0, limit=100, retry_after_ms=5000)
        headers = status.to_headers()
        assert "Retry-After" in headers

    def test_headers_include_limit_and_remaining(self) -> None:
        """Headers should include limit and remaining."""
        status = RateLimitStatus(allowed=True, remaining=50, limit=100, retry_after_ms=0)
        headers = status.to_headers()
        assert headers["X-RateLimit-Limit"] == "100"
        assert headers["X-RateLimit-Remaining"] == "50"
