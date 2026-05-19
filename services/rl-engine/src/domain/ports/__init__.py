"""
Domain ports for the RL Engine service.

Ports define the hexagonal architecture boundaries for the AI/ML
intelligence layer. The key design decision is that ML framework
code (PyTorch, Ray RLlib) is isolated in adapter implementations,
keeping the domain layer pure and testable with simple mocks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from .models import (
    Action, Episode, EnvironmentType, Policy, Reward,
    State, TrainingJob, Transition,
)


class EnvironmentPort(ABC):
    """Interface for RL environment simulation.
    Environments provide the state space, action space, and reward
    function for RL training. Implementations wrap real system
    telemetry or simulated environments for safe training."""

    @abstractmethod
    async def reset(self, environment: EnvironmentType) -> State:
        """Reset the environment and return the initial state."""
        ...

    @abstractmethod
    async def step(self, environment: EnvironmentType, state: State, action: Action) -> dict[str, Any]:
        """Take an action in the environment and return the result.
        Returns dict with keys: next_state, reward, done, info."""
        ...


class TrainingEnginePort(ABC):
    """Interface for ML framework operations (training, inference).
    This is the primary port that isolates PyTorch/Ray code from the
    domain layer. Implementations wrap the specific ML framework,
    handling tensor operations, gradient computation, and model persistence."""

    @abstractmethod
    async def train_step(self, policy_id: str, episode: Episode) -> dict[str, float]:
        """Execute a single training step using collected episode data.
        Returns training metrics (loss, gradient_norm, etc.)."""
        ...

    @abstractmethod
    async def predict(self, policy_id: str, state: State) -> dict[str, Any]:
        """Select an action for the given state using the trained policy.
        Returns action_id, probability, and optional parameters."""
        ...

    @abstractmethod
    async def inner_loop_adapt(self, task: dict[str, Any], steps: int, learning_rate: float) -> str:
        """MAML inner loop: adapt parameters to a specific task.
        Returns the adapted parameter identifier."""
        ...

    @abstractmethod
    async def evaluate_adapted(self, params_id: str, task: dict[str, Any]) -> float:
        """Evaluate adapted parameters on a task's validation set.
        Returns the validation loss for meta-gradient computation."""
        ...

    @abstractmethod
    async def meta_update(self, meta_loss: float, learning_rate: float) -> None:
        """MAML outer loop: update meta-parameters using meta-gradient."""
        ...

    @abstractmethod
    async def load_meta_params(self, environment: EnvironmentType) -> str:
        """Load meta-learned parameters for an environment.
        Returns the policy ID initialized with meta-parameters."""
        ...

    @abstractmethod
    async def adapt_step(self, policy_id: str, data: list[Transition], lr: float) -> float:
        """Perform a single adaptation gradient step on service-specific data.
        Returns the training loss for monitoring adaptation progress."""
        ...


class ModelRepositoryPort(ABC):
    """Interface for persisting and querying RL models and training jobs.
    Stores policy configurations, training job metadata, and model artifacts.
    PostgreSQL is used for metadata, while model weights are stored in
    object storage (S3/MinIO) with references in the database."""

    @abstractmethod
    async def save_policy(self, policy: Policy) -> Policy:
        """Persist a policy configuration and its current state."""
        ...

    @abstractmethod
    async def get_policy(self, policy_id: str) -> Optional[Policy]:
        """Retrieve a policy by its unique identifier."""
        ...

    @abstractmethod
    async def get_production_policy(self, environment: EnvironmentType) -> Optional[Policy]:
        """Retrieve the current production policy for an environment."""
        ...

    @abstractmethod
    async def save_training_job(self, job: TrainingJob) -> TrainingJob:
        """Persist a training job's configuration and status."""
        ...

    @abstractmethod
    async def get_training_job(self, job_id: str) -> Optional[TrainingJob]:
        """Retrieve a training job by ID."""
        ...
