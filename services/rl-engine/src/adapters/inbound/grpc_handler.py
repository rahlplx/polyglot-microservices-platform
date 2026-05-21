"""
gRPC inbound adapter for RL Engine rate-limit service.

Implements the CheckRateLimit gRPC method. Uses grpc.ServicerContext
protocol so tests can inject fakes without real gRPC dependency.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

from ...domain.models.rate_limit import RateLimitKey, RateLimitRule, RateLimitStrategy
from ...domain.ports.inbound.check_rate_limit import CheckRateLimitPort

logger = logging.getLogger(__name__)


class GrpcContext(Protocol):
    """Minimal gRPC ServicerContext interface for typing."""
    def set_code(self, code: Any) -> None: ...
    def set_details(self, details: str) -> None: ...


class RateLimitGrpcHandler:
    """
    Handles incoming gRPC CheckRateLimit calls.

    Translates proto request -> domain model -> domain service -> proto response.
    Zero business logic here — all logic lives in RateLimitEngine.
    """

    def __init__(self, engine: CheckRateLimitPort) -> None:
        self._engine = engine

    def CheckRateLimit(self, request: Any, context: GrpcContext) -> Any:
        """Handle a rate limit check request."""
        try:
            key = RateLimitKey(
                client_id=getattr(request, "client_id", ""),
                route=getattr(request, "route", "/"),
                method=getattr(request, "method", "GET"),
            )
            rule = RateLimitRule(
                max_requests=getattr(request, "max_requests", 100),
                window_seconds=getattr(request, "window_seconds", 60),
                strategy=RateLimitStrategy(
                    getattr(request, "strategy", RateLimitStrategy.TOKEN_BUCKET)
                ),
            )
            status = self._engine.check(key, rule)
            return _RateLimitResponse(
                allowed=status.allowed,
                remaining=status.remaining,
                retry_after_ms=status.retry_after_ms or 0,
            )
        except Exception as exc:
            logger.exception("CheckRateLimit failed: %s", exc)
            context.set_code(2)  # StatusCode.UNKNOWN
            context.set_details(str(exc))
            return _RateLimitResponse(allowed=False, remaining=0, retry_after_ms=1000)


class _RateLimitResponse:
    """Minimal response object — replaced by proto-generated class in production."""
    def __init__(self, allowed: bool, remaining: int, retry_after_ms: int) -> None:
        self.allowed = allowed
        self.remaining = remaining
        self.retry_after_ms = retry_after_ms
