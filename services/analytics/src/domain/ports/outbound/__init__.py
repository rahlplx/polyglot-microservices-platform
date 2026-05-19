"""
Outbound ports (driven ports) for the Analytics service.

Outbound ports define the interfaces that the domain layer requires from
infrastructure adapters. The domain services depend on these abstractions
rather than concrete implementations, following the Dependency Inversion
Principle. Each outbound port is implemented by one or more adapters in
the adapters/outbound layer.
"""
