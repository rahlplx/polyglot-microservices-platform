"""
Domain ports for the RL Engine service.

Ports define the hexagonal architecture boundaries for both the rate
limiting engine and the RL training/inference subsystem. Inbound ports
are use case interfaces called by driving adapters (gRPC, REST, API
gateway middleware). Outbound ports are infrastructure interfaces
implemented by driven adapters (Redis, PostgreSQL, in-memory, PyTorch).

The key design decision is that storage and compute implementation
details (Redis Lua scripts, PostgreSQL transactions, PyTorch models)
are isolated in adapter code, keeping the domain layer pure and
testable with simple mocks.
"""

from __future__ import annotations

from .inbound import CheckRateLimitPort, GetTrafficPatternPort, RecordRequestPort
from .outbound import RateLimitStorePort
from .rl_ports import EnvironmentPort, ModelRepositoryPort, TrainingEnginePort

__all__ = [
    "CheckRateLimitPort",
    "EnvironmentPort",
    "GetTrafficPatternPort",
    "ModelRepositoryPort",
    "RateLimitStorePort",
    "RecordRequestPort",
    "TrainingEnginePort",
]
