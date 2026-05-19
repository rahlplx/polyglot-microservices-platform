"""
Domain ports for the RL Engine (Rate Limiting) service.

Ports define the hexagonal architecture boundaries for the rate limiting
engine. Inbound ports are use case interfaces called by driving adapters
(gRPC, REST, API gateway middleware). Outbound ports are infrastructure
interfaces implemented by driven adapters (Redis, PostgreSQL, in-memory).

The key design decision is that storage implementation details (Redis
Lua scripts, PostgreSQL transactions) are isolated in adapter code,
keeping the domain layer pure and testable with simple mocks.
"""

from __future__ import annotations

from .inbound import CheckRateLimitPort, GetTrafficPatternPort, RecordRequestPort
from .outbound import RateLimitStorePort

__all__ = [
    "CheckRateLimitPort",
    "RecordRequestPort",
    "GetTrafficPatternPort",
    "RateLimitStorePort",
]
