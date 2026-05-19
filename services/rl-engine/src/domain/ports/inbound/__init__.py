"""
Inbound ports (driving ports) for the RL Engine (Rate Limiting) service.

Inbound ports define the use case interfaces that external callers use to
interact with the rate limiting domain. Each port represents a distinct
capability: checking rate limits, recording requests, and querying traffic
patterns. Adapters in the inbound layer (gRPC handlers, REST controllers,
API gateway middleware) invoke these ports to fulfill client requests.
"""

from __future__ import annotations

from .check_rate_limit import CheckRateLimitPort, GetTrafficPatternPort, RecordRequestPort

__all__ = [
    "CheckRateLimitPort",
    "RecordRequestPort",
    "GetTrafficPatternPort",
]
