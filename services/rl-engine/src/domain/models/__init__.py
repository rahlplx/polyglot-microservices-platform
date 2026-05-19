"""
Domain models for the RL Engine service.

These models represent the core concepts of reinforcement learning and
meta-learning, including state spaces, action spaces, reward functions,
policies, and training episodes. All models are pure Python with zero
ML framework dependencies, ensuring the hexagonal boundary is maintained.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class PolicyType(str, Enum):
    """Type of RL policy for action selection.
    EPSILON_GREEDY uses a simple exploration strategy with random actions
    taken with probability epsilon. SOFTMAX uses the Boltzmann distribution
    over action values for smooth exploration. THOMPSON_SAMPLING uses
    Bayesian posterior sampling for efficient exploration in bandit settings."""
    EPSILON_GREEDY = "EPSILON_GREEDY"
    SOFTMAX = "SOFTMAX"
    THOMPSON_SAMPLING = "THOMPSON_SAMPLING"


class TrainingStatus(str, Enum):
    """Status of a model training run.
    Training follows the lifecycle: PENDING → RUNNING → COMPLETED or FAILED.
    COMPLETED models are eligible for promotion to production after validation."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EnvironmentType(str, Enum):
    """Type of RL environment (simulation context).
    Each environment defines a distinct state space, action space, and
    reward function. NOTIFICATION_DELIVERY optimizes channel selection
    and timing. CIRCUIT_BREAKER tunes failure thresholds and timeouts.
    RESOURCE_ALLOCATION optimizes CPU/memory provisioning."""
    NOTIFICATION_DELIVERY = "NOTIFICATION_DELIVERY"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"
    RESOURCE_ALLOCATION = "RESOURCE_ALLOCATION"
    CUSTOM = "CUSTOM"


@dataclass
class State:
    """Observation of the environment at a given timestep.
    States are represented as dictionaries of feature name to float value,
    enabling flexible state spaces that can evolve without breaking the
    agent interface. Features are normalized to [0, 1] range for stable
    training across different environment scales."""
    features: dict[str, float] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_vector(self, feature_order: list[str]) -> list[float]:
        """Convert the state to a fixed-order feature vector for model input.
        Missing features default to 0.0, which is safe for normalized features."""
        return [self.features.get(f, 0.0) for f in feature_order]


@dataclass
class Action:
    """An action taken by the RL agent in the environment.
    Actions are discrete selections from a defined action space, with
    optional parameters that modify the action's effect. The action
    probability is recorded for policy gradient computation."""
    action_id: int = 0
    action_name: str = ""
    parameters: dict[str, float] = field(default_factory=dict)
    probability: float = 1.0


@dataclass
class Reward:
    """Reward signal from the environment after an action is taken.
    Rewards are scalar values that guide the agent toward desired behavior.
    The reward signal can be composed of multiple components (sparse + dense)
    to balance short-term and long-term optimization objectives."""
    value: float = 0.0
    components: dict[str, float] = field(default_factory=dict)
    info: dict[str, Any] = field(default_factory=dict)

    def total(self) -> float:
        """Return the total reward, which is the sum of all components
        if defined, otherwise the scalar value."""
        if self.components:
            return sum(self.components.values())
        return self.value


@dataclass
class Transition:
    """A single (state, action, reward, next_state) transition.
    Transitions are the fundamental unit of experience in RL, collected
    during environment interaction and used to update the policy. Each
    transition also stores whether the episode terminated (done flag)
    and the log probability of the action for policy gradient methods."""
    state: State = field(default_factory=State)
    action: Action = field(default_factory=Action)
    reward: Reward = field(default_factory=Reward)
    next_state: State = field(default_factory=State)
    done: bool = False
    log_probability: float = 0.0


@dataclass
class Episode:
    """A complete trajectory of transitions from reset to termination.
    Episodes are used for on-policy algorithms (PPO, A2C) that require
    complete trajectories for gradient computation. The episode also
    tracks aggregate statistics for monitoring training progress."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    environment: EnvironmentType = EnvironmentType.NOTIFICATION_DELIVERY
    transitions: list[Transition] = field(default_factory=list)
    total_reward: float = 0.0
    length: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    def add_transition(self, transition: Transition) -> None:
        """Add a transition and update episode statistics."""
        self.transitions.append(transition)
        self.total_reward += transition.reward.total()
        self.length += 1
        if transition.done:
            self.completed_at = datetime.now(timezone.utc)

    @property
    def average_reward(self) -> float:
        """Return the average reward per step in this episode."""
        if self.length == 0:
            return 0.0
        return self.total_reward / self.length


@dataclass
class Policy:
    """An RL policy that maps states to action probabilities.
    The policy encapsulates the decision-making model, including its
    type, version, and hyperparameters. Policies are versioned to
    support A/B testing and gradual rollout of new models."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    environment: EnvironmentType = EnvironmentType.NOTIFICATION_DELIVERY
    policy_type: PolicyType = PolicyType.EPSILON_GREEDY
    version: int = 1
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    feature_order: list[str] = field(default_factory=list)
    action_space_size: int = 4
    is_production: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    trained_at: Optional[datetime] = None


@dataclass
class TrainingJob:
    """A model training run with configuration and status tracking.
    Training jobs are submitted to the RL Engine and tracked through
    their lifecycle. Each job specifies the environment, policy type,
    training algorithm, and hyperparameters. Results include trained
    model artifacts and evaluation metrics."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    policy_id: str = ""
    environment: EnvironmentType = EnvironmentType.NOTIFICATION_DELIVERY
    algorithm: str = "PPO"
    status: TrainingStatus = TrainingStatus.PENDING
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    total_timesteps: int = 100000
    completed_timesteps: int = 0
    episodes_completed: int = 0
    mean_episode_reward: float = 0.0
    best_episode_reward: float = float("-inf")
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: str = ""


@dataclass
class MetaLearningConfig:
    """Configuration for MAML (Model-Agnostic Meta-Learning) adaptation.
    MAML enables rapid adaptation to new services by learning good
    initialization parameters that can be fine-tuned with minimal data.
    The inner loop adapts to a specific task, while the outer loop
    optimizes across tasks for generalization."""
    inner_lr: float = 0.01          # Inner loop learning rate
    outer_lr: float = 0.001         # Outer loop learning rate
    inner_steps: int = 5            # Number of gradient steps per task
    meta_batch_size: int = 10       # Number of tasks per meta-update
    adaptation_steps: int = 3       # Steps for test-time adaptation
    first_order: bool = True        # Use first-order MAML for efficiency
