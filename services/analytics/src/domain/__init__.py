"""
Domain layer for the Analytics service.

This package contains the core business logic, domain models, port interfaces,
and domain services. The domain layer follows the dependency rule: it has zero
external dependencies and defines all interfaces (ports) that adapters must
implement. No code in this package may import from the adapters or
infrastructure layers.
"""
