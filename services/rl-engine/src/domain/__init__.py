"""
Domain layer for the RL Engine (Rate Limiting) service.

The domain layer contains the core business logic for adaptive rate limiting
with ML-based pattern detection. It follows hexagonal architecture principles:

- **models**: Pure Python dataclasses and enums representing rate limit rules,
  token bucket states, request keys, and traffic patterns. Zero external
  dependencies to maintain the architecture boundary.
- **services**: The RateLimitEngine that orchestrates rate limit checking,
  request recording, and traffic pattern analysis across four strategies.
- **ports**: Inbound (driving) and outbound (driven) port interfaces that
  define the hexagonal architecture boundaries. Inbound ports are use case
  interfaces implemented by the domain services. Outbound ports are
  infrastructure interfaces implemented by adapters.
"""
