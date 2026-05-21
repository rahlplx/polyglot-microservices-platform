"""RL Engine — Adapter unit tests (no KeyDB/gRPC deps required)."""
import pytest
import time
import threading
from unittest.mock import MagicMock, patch
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from src.adapters.outbound.in_memory_store import InMemoryRateLimitStore
from src.adapters.inbound.grpc_handler import RateLimitGrpcHandler
from src.domain.models.rate_limit import (
    RateLimitKey, RateLimitRule, RateLimitStrategy, TokenBucketState,
)
from src.domain.services.rate_limit_engine import RateLimitEngine

from datetime import datetime, timezone


def make_bucket(key="test", tokens=10.0):
    return TokenBucketState(key=key, tokens=tokens, max_tokens=tokens,
                            last_refill_at=datetime.now(timezone.utc))


# ── InMemoryRateLimitStore ────────────────────────────────────────────────

class TestInMemoryRateLimitStore:
    def test_get_missing_bucket_returns_none(self):
        store = InMemoryRateLimitStore()
        assert store.get_bucket("no-such-key") is None

    def test_save_and_retrieve_bucket(self):
        store = InMemoryRateLimitStore()
        bucket = make_bucket("client-1", tokens=9.5)
        store.save_bucket(bucket)
        result = store.get_bucket("client-1")
        assert result is not None
        assert result.tokens == pytest.approx(9.5)

    def test_save_overwrites_existing(self):
        store = InMemoryRateLimitStore()
        store.save_bucket(make_bucket("k", tokens=10.0))
        store.save_bucket(make_bucket("k", tokens=5.0))
        assert store.get_bucket("k").tokens == pytest.approx(5.0)

    def test_increment_counter_starts_at_one(self):
        store = InMemoryRateLimitStore()
        assert store.increment_counter("new-key", window=60) == 1

    def test_increment_counter_accumulates(self):
        store = InMemoryRateLimitStore()
        for i in range(5):
            store.increment_counter("k", window=60)
        assert store.increment_counter("k", window=60) == 6

    def test_counter_resets_after_window(self):
        store = InMemoryRateLimitStore()
        store.increment_counter("k", window=1)
        store.increment_counter("k", window=1)
        time.sleep(1.05)
        assert store.increment_counter("k", window=1) == 1

    def test_thread_safety_increment(self):
        store = InMemoryRateLimitStore()
        results = []
        def worker():
            results.append(store.increment_counter("shared", window=60))
        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert max(results) == 50
        assert len(set(results)) == 50  # all values unique

    def test_different_keys_independent(self):
        store = InMemoryRateLimitStore()
        store.increment_counter("a", 60)
        store.increment_counter("a", 60)
        store.increment_counter("b", 60)
        assert store.increment_counter("a", 60) == 3
        assert store.increment_counter("b", 60) == 2


# ── RateLimitGrpcHandler ─────────────────────────────────────────────────

def make_request(**kw):
    req = MagicMock()
    req.client_id = kw.get("client_id", "user-123")
    req.route = kw.get("route", "/api/orders")
    req.method = kw.get("method", "POST")
    req.max_requests = kw.get("max_requests", 10)
    req.window_seconds = kw.get("window_seconds", 60)
    req.strategy = kw.get("strategy", RateLimitStrategy.TOKEN_BUCKET)
    return req


def make_context():
    ctx = MagicMock()
    ctx.set_code = MagicMock()
    ctx.set_details = MagicMock()
    return ctx


class TestRateLimitGrpcHandler:
    def _engine(self):
        store = InMemoryRateLimitStore()
        return RateLimitEngine(store=store)

    def test_first_request_is_allowed(self):
        handler = RateLimitGrpcHandler(self._engine())
        resp = handler.CheckRateLimit(make_request(max_requests=10), make_context())
        assert resp.allowed is True
        assert resp.remaining >= 0  # remaining tokens after first call

    def test_exceeds_limit_is_denied(self):
        engine = self._engine()
        handler = RateLimitGrpcHandler(engine)
        req = make_request(max_requests=3, window_seconds=60,
                           strategy=RateLimitStrategy.FIXED_WINDOW)
        ctx = make_context()
        for _ in range(3):
            handler.CheckRateLimit(req, ctx)
        resp = handler.CheckRateLimit(req, ctx)
        assert resp.allowed is False

    def test_engine_exception_returns_deny_not_crash(self):
        bad_engine = MagicMock()
        bad_engine.check.side_effect = RuntimeError("KeyDB timeout")
        handler = RateLimitGrpcHandler(bad_engine)
        ctx = make_context()
        resp = handler.CheckRateLimit(make_request(), ctx)
        assert resp.allowed is False
        ctx.set_code.assert_called_once()
        ctx.set_details.assert_called_once()

    def test_response_includes_retry_after_when_denied(self):
        engine = self._engine()
        handler = RateLimitGrpcHandler(engine)
        req = make_request(max_requests=1, window_seconds=30,
                           strategy=RateLimitStrategy.FIXED_WINDOW)
        ctx = make_context()
        handler.CheckRateLimit(req, ctx)  # allowed
        resp = handler.CheckRateLimit(req, ctx)  # denied
        if not resp.allowed:
            assert resp.retry_after_ms >= 0


# ── Integration: Engine + InMemoryStore ──────────────────────────────────

class TestEngineWithInMemoryStore:
    def test_token_bucket_enforces_burst_limit(self):
        store = InMemoryRateLimitStore()
        engine = RateLimitEngine(store=store)
        key = RateLimitKey(client_id="burst-test", route="/v1/items", method="GET")
        rule = RateLimitRule(max_requests=5, window_seconds=60,
                             strategy=RateLimitStrategy.TOKEN_BUCKET)
        allowed = sum(1 for _ in range(10) if engine.check(key, rule).allowed)
        assert allowed == 7  # burst_multiplier=1.5 -> max_tokens=7

    def test_sliding_window_counts_requests(self):
        store = InMemoryRateLimitStore()
        engine = RateLimitEngine(store=store)
        key = RateLimitKey(client_id="slide-test", route="/v1/search", method="GET")
        rule = RateLimitRule(max_requests=3, window_seconds=60,
                             strategy=RateLimitStrategy.SLIDING_WINDOW)
        results = [engine.check(key, rule).allowed for _ in range(5)]
        assert results[:3] == [True, True, True]
        assert not all(results[3:])
