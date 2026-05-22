"""
RL policy and training domain models for the RL Engine service.

This module defines the reinforcement learning models including policies,
training jobs, states, actions, rewards, transitions, and episodes.
These models represent the core concepts of the RL-based adaptive control
system. All models are pure Python dataclasses and enums with zero external
dependencies, ensuring the hexagonal architecture boundary is maintained.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EnvironmentType(str, Enum):
    """RL environment type for policy scoping.

    Each environment type corresponds to a service or subsystem that
    the RL engine can manage with its own policy and state space.
    """

    GATEWAY = "GATEWAY"
    PAYMENT = "PAYMENT"
    ORDER = "ORDER"
    CATALOG = "CATALOG"
    ANALYTICS = "ANALYTICS"
    NOTIFICATION = "NOTIFICATION"


@dataclass
class State:
    """RL state representation.

    Encodes the observable features of the environment at a given time step.
    The features dict maps feature names (e.g., request_rate, error_rate,
    latency_p99, cpu_utilization) to normalized float values in [0, 1].
    """

    features: dict[str, float] = field(default_factory=dict)


@dataclass
class Action:
    """RL action representation.

    Represents a decision made by the policy, such as adjusting a rate
    limit threshold, scaling a parameter, or selecting a configuration.
    """

    action_id: int = 0
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class Reward:
    """RL reward signal.

    Scalar feedback from the environment after taking an action in a state.
    Higher values indicate better outcomes (e.g., lower error rates, lower
    latency).
    """

    value: float = 0.0


@dataclass
class Transition:
    """A single RL transition (s, a, r, s').

    Records one step of interaction with the environment, storing the
    state, action taken, reward received, and resulting next state.
    """

    state: State = field(default_factory=State)
    action: Action = field(default_factory=Action)
    reward: Reward = field(default_factory=Reward)
    next_state: State = field(default_factory=State)
    done: bool = False


@dataclass
class Episode:
    """A complete RL episode consisting of multiple transitions.

    An episode represents a full trajectory from the initial state to
    a terminal state, collected during training or evaluation.
    """

    episode_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    environment: EnvironmentType = EnvironmentType.GATEWAY
    transitions: list[Transition] = field(default_factory=list)
    total_reward: float = 0.0

    def add_transition(self, transition: Transition) -> None:
        """Add a transition and update the total reward."""
        self.transitions.append(transition)
        self.total_reward += transition.reward.value


@dataclass
class Policy:
    """RL policy model.

    Represents a learned policy that maps states to actions. The policy
    can be promoted to production for a given environment type, enabling
    the RL engine to make real-time control decisions.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    environment: EnvironmentType = EnvironmentType.GATEWAY
    version: int = 1
    is_production: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrainingJob:
    """RL training job model.

    Tracks the state and configuration of a policy training run,
    including the environment, algorithm, hyperparameters, and
    training progress.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    policy_id: str = ""
    environment: EnvironmentType = EnvironmentType.GATEWAY
    algorithm: str = "PPO"
    status: str = "PENDING"
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
