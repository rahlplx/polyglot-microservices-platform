"""
Outbound ports (driven ports) for the RL Engine (Rate Limiting) service.

Outbound ports define the infrastructure interfaces that the domain depends on.
These are implemented by adapters in the outer layers, providing concrete
implementations for rate limit state storage (Redis, PostgreSQL, in-memory).
The domain layer only depends on these port interfaces, never on concrete
adapter implementations.
"""

from __future__ import annotations

from .rate_limit_store import RateLimitStorePort

__all__ = [
    "RateLimitStorePort",
]
