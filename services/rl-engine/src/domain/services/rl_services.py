"""
RL-specific domain services for the RL Engine service.

Implements the core RL operations including policy management,
training orchestration, inference, and meta-learning. These services
depend only on domain ports, keeping infrastructure code isolated.
"""

from __future__ import annotations

from typing import Any, Optional

from ..models.policy import Action, EnvironmentType, Episode, Policy, State, TrainingJob, Transition
from ..ports.rl_ports import EnvironmentPort, ModelRepositoryPort, TrainingEnginePort


class PolicyService:
    """Domain service for policy lifecycle management.

    Handles policy CRUD operations, production promotion, and
    versioning. Delegates persistence to ModelRepositoryPort.
    """

    def __init__(self, model_repo: ModelRepositoryPort) -> None:
        self._repo = model_repo

    async def create_policy(self, name: str, environment: EnvironmentType, parameters: dict[str, Any] | None = None) -> Policy:
        """Create a new policy."""
        policy = Policy(name=name, environment=environment, parameters=parameters or {})
        return await self._repo.save_policy(policy)

    async def get_policy(self, policy_id: str) -> Optional[Policy]:
        """Retrieve a policy by ID."""
        return await self._repo.get_policy(policy_id)

    async def promote_to_production(self, policy_id: str) -> Optional[Policy]:
        """Promote a policy to production for its environment."""
        policy = await self._repo.get_policy(policy_id)
        if policy is None:
            return None
        policy.is_production = True
        return await self._repo.save_policy(policy)

    async def deploy_policy(self, policy_id: str) -> Optional[Policy]:
        """Alias for promote_to_production — deploy a policy to production."""
        return await self.promote_to_production(policy_id)

    async def get_production_policy(self, environment: EnvironmentType) -> Optional[Policy]:
        """Get the current production policy for an environment."""
        return await self._repo.get_production_policy(environment)


class TrainingService:
    """Domain service for RL training orchestration.

    Coordinates the training loop by managing episodes, invoking
    the training engine, and persisting training jobs.
    """

    def __init__(
        self,
        model_repo: ModelRepositoryPort,
        training_engine: TrainingEnginePort,
        environment: EnvironmentPort,
    ) -> None:
        self._repo = model_repo
        self._engine = training_engine
        self._environment = environment

    async def run_training_step(self, policy_id: str, environment: 'EnvironmentType') -> 'Episode':
        """Run a single training episode step."""
        return await self.run_episode(policy_id, environment)

    async def submit_training_job(self, policy_id: str, environment: EnvironmentType, episodes: int = 10) -> TrainingJob:
        """Alias for start_training — submit a training job."""
        return await self.start_training(policy_id, environment, episodes)

    async def start_training(self, policy_id: str, environment: EnvironmentType, episodes: int = 10) -> TrainingJob:
        """Start a training job for a policy."""
        job = TrainingJob(policy_id=policy_id, environment=environment, status="RUNNING")
        return await self._repo.save_training_job(job)

    async def run_episode(self, policy_id: str, environment: EnvironmentType) -> Episode:
        """Run a single training episode."""
        state = await self._environment.reset(environment)
        episode = Episode(environment=environment)
        done = False

        while not done:
            prediction = await self._engine.predict(policy_id, state)
            action = Action(action_id=prediction.get("action_id", 0), parameters=prediction.get("parameters", {}))
            result = await self._environment.step(environment, state, action)
            next_state = result["next_state"]
            reward = result["reward"]
            done = result.get("done", False)

            transition = Transition(state=state, action=action, reward=reward, next_state=next_state, done=done)
            episode.add_transition(transition)
            state = next_state

        await self._engine.train_step(policy_id, episode)
        return episode


class InferenceService:
    """Domain service for RL inference.

    Provides real-time action predictions using trained policies.
    """

    def __init__(self, model_repo: ModelRepositoryPort, training_engine: TrainingEnginePort) -> None:
        self._repo = model_repo
        self._engine = training_engine

    async def select_action(self, policy_id: str, state: State) -> dict[str, Any]:
        """Alias for predict — select an action given current state."""
        return await self.predict(policy_id, state)

    async def predict(self, policy_id: str, state: State) -> dict[str, Any]:
        """Get action prediction for a state using the specified policy."""
        return await self._engine.predict(policy_id, state)

    async def predict_production(self, environment: EnvironmentType, state: State) -> Optional[dict[str, Any]]:
        """Get prediction from the production policy for an environment."""
        policy = await self._repo.get_production_policy(environment)
        if policy is None:
            return None
        return await self._engine.predict(policy.id, state)


class MetaLearningService:
    """Domain service for meta-learning (MAML) operations.

    Coordinates the inner loop adaptation and outer loop meta-update
    for few-shot learning across service environments.
    """

    def __init__(self, training_engine: TrainingEnginePort, model_repo: ModelRepositoryPort) -> None:
        self._engine = training_engine
        self._repo = model_repo

    async def meta_train(self, environment: 'EnvironmentType', task: dict[str, Any], steps: int = 5, learning_rate: float = 0.01) -> str:
        """Alias for adapt_to_service — run meta-training for a service environment."""
        return await self.adapt_to_service(environment, task, steps, learning_rate)

    async def adapt_to_service(self, environment: EnvironmentType, task: dict[str, Any], steps: int = 5, learning_rate: float = 0.01) -> str:
        """Adapt the meta-policy to a specific service environment."""
        await self._engine.load_meta_params(environment)
        adapted_id = await self._engine.inner_loop_adapt(task, steps, learning_rate)
        return adapted_id

    async def meta_update(self, meta_loss: float, learning_rate: float = 0.001) -> None:
        """Perform a meta-gradient update across tasks."""
        await self._engine.meta_update(meta_loss, learning_rate)
