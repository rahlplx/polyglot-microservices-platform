"""
RL-specific domain ports for the RL Engine service.

These ports define the interfaces for the RL training and inference
subsystem, including environment simulation, model persistence, and
training engine capabilities. They complement the rate limiting ports
to support the dual-purpose nature of the RL Engine.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from ..models.policy import Action, EnvironmentType, Episode, Policy, State, TrainingJob, Transition


class EnvironmentPort(ABC):
    """Port for RL environment interaction.

    Defines the interface for simulated or real environments used
    during policy training. Implementations provide state reset and
    step functionality following the standard OpenAI Gym API pattern.
    """

    @abstractmethod
    async def reset(self, environment: EnvironmentType) -> State:
        """Reset the environment and return the initial state."""
        ...

    @abstractmethod
    async def step(
        self, environment: EnvironmentType, state: State, action: Action
    ) -> dict[str, Any]:
        """Take an action in the environment and return the result.

        Returns:
            A dict with keys: next_state (State), reward (Reward),
            done (bool), info (dict).
        """
        ...


class ModelRepositoryPort(ABC):
    """Port for policy and training job persistence.

    Provides the interface for storing and retrieving RL policies
    and training jobs. Implementations may use PostgreSQL, S3,
    or in-memory storage.
    """

    @abstractmethod
    async def save_policy(self, policy: Policy) -> Policy:
        """Persist a policy."""
        ...

    @abstractmethod
    async def get_policy(self, policy_id: str) -> Optional[Policy]:
        """Retrieve a policy by ID."""
        ...

    @abstractmethod
    async def get_production_policy(self, environment: EnvironmentType) -> Optional[Policy]:
        """Get the current production policy for an environment."""
        ...

    @abstractmethod
    async def save_training_job(self, job: TrainingJob) -> TrainingJob:
        """Persist a training job."""
        ...

    @abstractmethod
    async def get_training_job(self, job_id: str) -> Optional[TrainingJob]:
        """Retrieve a training job by ID."""
        ...


class TrainingEnginePort(ABC):
    """Port for RL training engine capabilities.

    Defines the interface for training, inference, and meta-learning
    operations. Implementations wrap ML frameworks like PyTorch,
    TensorFlow, or Ray RLlib.
    """

    @abstractmethod
    async def train_step(self, policy_id: str, episode: Episode) -> dict[str, float]:
        """Perform a single training step on an episode."""
        ...

    @abstractmethod
    async def predict(self, policy_id: str, state: State) -> dict[str, Any]:
        """Get action prediction for a given state."""
        ...

    @abstractmethod
    async def inner_loop_adapt(
        self, task: dict[str, Any], steps: int, learning_rate: float
    ) -> str:
        """MAML inner loop adaptation on a task."""
        ...

    @abstractmethod
    async def evaluate_adapted(self, params_id: str, task: dict[str, Any]) -> float:
        """Evaluate adapted parameters on a validation task."""
        ...

    @abstractmethod
    async def meta_update(self, meta_loss: float, learning_rate: float) -> None:
        """Perform a meta-gradient update."""
        ...

    @abstractmethod
    async def load_meta_params(self, environment: EnvironmentType) -> str:
        """Load meta-parameters for an environment type."""
        ...

    @abstractmethod
    async def adapt_step(
        self, policy_id: str, data: list[Transition], lr: float
    ) -> float:
        """Perform a single adaptation step on service-specific data."""
        ...
