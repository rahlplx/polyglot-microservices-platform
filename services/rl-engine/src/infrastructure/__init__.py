"""
Infrastructure and adapters for the RL Engine service.

The gRPC server includes reflection support via grpc_reflection.v1alpha
for service discovery tools like grpcurl. Enable it with:
    from grpc_reflection.v1alpha import reflection
    reflection.enable_server(grpc_server, SERVICE_NAMES)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from ..domain.models import (
    Action, Episode, EnvironmentType, Policy, Reward, State,
    TrainingJob, Transition,
)
from ..domain.ports import EnvironmentPort, ModelRepositoryPort, TrainingEnginePort
from ..domain.services import InferenceService, MetaLearningService, PolicyService, TrainingService


# gRPC service names for reflection registration
SERVICE_NAMES = (
    "rl_engine.v1.RLEngineService",
)


@dataclass
class Config:
    grpc_port: int = int(os.getenv("RL_ENGINE_GRPC_PORT", "50058"))
    http_port: int = int(os.getenv("RL_ENGINE_HTTP_PORT", "8088"))
    metrics_port: int = int(os.getenv("RL_ENGINE_METRICS_PORT", "9098"))
    kafka_brokers: str = os.getenv("RL_ENGINE_KAFKA_BROKERS", "localhost:9092")
    db_host: str = os.getenv("RL_ENGINE_DB_HOST", "localhost")
    db_port: int = int(os.getenv("RL_ENGINE_DB_PORT", "5432"))
    db_name: str = os.getenv("RL_ENGINE_DB_NAME", "rl_engine")
    otel_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")


class InMemoryModelRepo(ModelRepositoryPort):
    """In-memory model repository for development and testing."""

    def __init__(self) -> None:
        self._policies: dict[str, Policy] = {}
        self._jobs: dict[str, TrainingJob] = {}

    async def save_policy(self, policy: Policy) -> Policy:
        self._policies[policy.id] = policy
        return policy

    async def get_policy(self, policy_id: str) -> Optional[Policy]:
        return self._policies.get(policy_id)

    async def get_production_policy(self, environment: EnvironmentType) -> Optional[Policy]:
        for p in self._policies.values():
            if p.environment == environment and p.is_production:
                return p
        return None

    async def save_training_job(self, job: TrainingJob) -> TrainingJob:
        self._jobs[job.id] = job
        return job

    async def get_training_job(self, job_id: str) -> Optional[TrainingJob]:
        return self._jobs.get(job_id)


class SimulatedEnvironment(EnvironmentPort):
    """Simulated RL environment for training without real service dependencies.
    Generates synthetic states and rewards based on environment type,
    enabling offline training and testing of RL algorithms."""

    async def reset(self, environment: EnvironmentType) -> State:
        import random
        features = {
            "request_rate": random.uniform(0.0, 1.0),
            "error_rate": random.uniform(0.0, 0.1),
            "latency_p99": random.uniform(0.0, 1.0),
            "cpu_utilization": random.uniform(0.0, 1.0),
        }
        return State(features=features)

    async def step(self, environment: EnvironmentType, state: State, action: Action) -> dict[str, Any]:
        import random
        # Simulate environment dynamics.
        next_features = {
            k: max(0.0, min(1.0, v + random.uniform(-0.1, 0.1)))
            for k, v in state.features.items()
        }
        next_state = State(features=next_features)

        # Reward: lower error rate + lower latency = higher reward.
        reward_value = (1.0 - next_features.get("error_rate", 0.0)) * 0.7 + \
                       (1.0 - next_features.get("latency_p99", 0.0)) * 0.3

        return {
            "next_state": next_state,
            "reward": Reward(value=reward_value),
            "done": random.random() < 0.05,  # 5% chance of episode termination
            "info": {},
        }


class PyTorchTrainingEngine(TrainingEnginePort):
    """PyTorch-based training engine adapter.
    In production, this wraps PyTorch models with CUDA support,
    distributed training via Ray, and model artifact persistence.
    The current scaffold provides the interface contract with
    simulated training for development without GPU dependencies."""

    def __init__(self) -> None:
        self._models: dict[str, dict[str, Any]] = {}

    async def train_step(self, policy_id: str, episode: Episode) -> dict[str, float]:
        # In production: PPO loss computation, gradient update, model checkpoint.
        return {"loss": 0.5, "gradient_norm": 0.1, "entropy": 0.8}

    async def predict(self, policy_id: str, state: State) -> dict[str, Any]:
        # In production: forward pass through neural network.
        return {"action_id": 0, "probability": 0.25, "parameters": {}}

    async def inner_loop_adapt(self, task: dict[str, Any], steps: int, learning_rate: float) -> str:
        # In production: MAML inner loop gradient steps on task-specific loss.
        return f"adapted_{task['task_id']}"

    async def evaluate_adapted(self, params_id: str, task: dict[str, Any]) -> float:
        # In production: evaluate adapted parameters on validation data.
        return 0.3  # Simulated validation loss.

    async def meta_update(self, meta_loss: float, learning_rate: float) -> None:
        # In production: compute meta-gradient and update meta-parameters.
        pass

    async def load_meta_params(self, environment: EnvironmentType) -> str:
        return f"meta_policy_{environment.value}"

    async def adapt_step(self, policy_id: str, data: list[Transition], lr: float) -> float:
        # In production: single gradient step on service-specific data.
        return 0.2  # Simulated loss.


class Container:
    """DI container for the RL Engine service."""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or Config()
        self.model_repo = InMemoryModelRepo()
        self.environment = SimulatedEnvironment()
        self.training_engine = PyTorchTrainingEngine()

        self.policy_service = PolicyService(self.model_repo)
        self.training_service = TrainingService(self.model_repo, self.training_engine, self.environment)
        self.inference_service = InferenceService(self.model_repo, self.training_engine)
        self.meta_learning_service = MetaLearningService(self.training_engine, self.model_repo)
