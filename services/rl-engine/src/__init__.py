"""
RL Engine Service - Reinforcement Learning + Meta-Learning Intelligence Layer.

This service implements the AI/ML intelligence layer for the gstack platform,
providing reinforcement learning-based optimization for notification delivery,
circuit breaker tuning, and resource allocation. It also implements meta-learning
(MAML) for rapid adaptation to new services and changing traffic patterns.
The domain layer follows strict hexagonal architecture with zero ML framework
dependencies — all framework-specific code (PyTorch, Ray) lives in adapters.
"""

__version__ = "0.1.0"
