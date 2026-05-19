"""
Domain services for the RL Engine.

Implements the core RL training loop, policy evaluation, meta-learning
adaptation, and inference serving. All services depend only on domain
ports, keeping ML framework code isolated in adapters.
"""

from __future__ import annotations

import logging
import math
import random
from typing import Any, Optional

from .models import (
    Action, Episode, EnvironmentType, MetaLearningConfig, Policy,
    PolicyType, Reward, State, TrainingJob, TrainingStatus, Transition,
)
from .ports import (
    EnvironmentPort, ModelRepositoryPort, TrainingEnginePort,
)

logger = logging.getLogger(__name__)


class PolicyService:
    """Policy management service for creating, evaluating, and deploying
    RL policies. Handles policy CRUD, version management, and the
    promotion workflow from training to production deployment."""

    def __init__(self, model_repo: ModelRepositoryPort) -> None:
        self._repo = model_repo

    async def create_policy(
        self,
        name: str,
        environment: EnvironmentType,
        policy_type: PolicyType,
        action_space_size: int = 4,
        hyperparameters: Optional[dict[str, Any]] = None,
    ) -> Policy:
        """Create a new RL policy with default configuration.
        The policy starts at version 1 and is not promoted to production
        until explicitly deployed after training and evaluation."""
        policy = Policy(
            name=name,
            environment=environment,
            policy_type=policy_type,
            action_space_size=action_space_size,
            hyperparameters=hyperparameters or {},
        )
        await self._repo.save_policy(policy)
        logger.info("policy created", extra={"policy_id": policy.id, "name": name})
        return policy

    async def get_policy(self, policy_id: str) -> Optional[Policy]:
        """Retrieve a policy by ID."""
        return await self._repo.get_policy(policy_id)

    async def deploy_policy(self, policy_id: str) -> Policy:
        """Promote a policy to production, demoting any existing production policy.
        Production policies are used by the inference service for action selection."""
        policy = await self._repo.get_policy(policy_id)
        if not policy:
            raise ValueError(f"policy {policy_id} not found")
        if policy.trained_at is None:
            raise ValueError("policy must be trained before deployment")

        # Demote existing production policy.
        existing = await self._repo.get_production_policy(policy.environment)
        if existing and existing.id != policy_id:
            existing.is_production = False
            await self._repo.save_policy(existing)

        policy.is_production = True
        await self._repo.save_policy(policy)
        logger.info("policy deployed to production", extra={"policy_id": policy_id})
        return policy


class TrainingService:
    """RL training orchestration service. Manages the training lifecycle,
    including job submission, progress tracking, and evaluation. The actual
    training computation is delegated to the TrainingEnginePort adapter,
    which wraps the ML framework (PyTorch, Ray RLlib) implementation."""

    def __init__(
        self,
        model_repo: ModelRepositoryPort,
        training_engine: TrainingEnginePort,
        environment: EnvironmentPort,
    ) -> None:
        self._repo = model_repo
        self._engine = training_engine
        self._environment = environment

    async def submit_training_job(
        self,
        policy_id: str,
        algorithm: str = "PPO",
        total_timesteps: int = 100000,
        hyperparameters: Optional[dict[str, Any]] = None,
    ) -> TrainingJob:
        """Submit a new training job for a policy.
        The job is created in PENDING status and started asynchronously."""
        policy = await self._repo.get_policy(policy_id)
        if not policy:
            raise ValueError(f"policy {policy_id} not found")

        job = TrainingJob(
            policy_id=policy_id,
            environment=policy.environment,
            algorithm=algorithm,
            total_timesteps=total_timesteps,
            hyperparameters=hyperparameters or policy.hyperparameters,
        )
        await self._repo.save_training_job(job)
        logger.info("training job submitted", extra={"job_id": job.id, "policy_id": policy_id})
        return job

    async def run_training_step(self, job: TrainingJob, batch_size: int = 256) -> TrainingJob:
        """Execute a single training step (collect experience + update policy).
        This method is called repeatedly by the training loop until the
        job reaches its total timestep target."""
        # Collect experience from the environment.
        episode = Episode(environment=job.environment)
        state = await self._environment.reset(job.environment)

        for _ in range(batch_size):
            action = await self._select_action(job, state)
            result = await self._environment.step(job.environment, state, action)
            transition = Transition(
                state=state,
                action=action,
                reward=result["reward"],
                next_state=result["next_state"],
                done=result["done"],
            )
            episode.add_transition(transition)
            state = result["next_state"]

            if result["done"]:
                state = await self._environment.reset(job.environment)

        # Update the policy using the collected experience.
        metrics = await self._engine.train_step(job.policy_id, episode)

        # Update job progress.
        job.completed_timesteps += batch_size
        job.episodes_completed += 1
        job.mean_episode_reward = episode.average_reward
        if episode.total_reward > job.best_episode_reward:
            job.best_episode_reward = episode.total_reward

        if job.completed_timesteps >= job.total_timesteps:
            job.status = TrainingStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)

        await self._repo.save_training_job(job)
        return job

    async def _select_action(self, job: TrainingJob, state: State) -> Action:
        """Select an action using the current policy with exploration.
        Implements epsilon-greedy exploration for epsilon_greedy policies,
        with the epsilon value decaying as training progresses."""
        policy = await self._repo.get_policy(job.policy_id)
        if not policy:
            return Action(action_id=0, action_name="default")

        # Epsilon-greedy exploration.
        epsilon = max(0.01, 0.5 * (1.0 - job.completed_timesteps / job.total_timesteps))
        if random.random() < epsilon:
            action_id = random.randint(0, policy.action_space_size - 1)
        else:
            # Use the trained model for action selection.
            prediction = await self._engine.predict(job.policy_id, state)
            action_id = prediction.get("action_id", 0)

        return Action(
            action_id=action_id,
            action_name=f"action_{action_id}",
            parameters={},
            probability=1.0 / policy.action_space_size,
        )


class InferenceService:
    """RL inference service for real-time action selection.
    Serves trained policies for production use, selecting actions
    based on the current environment state. Supports A/B testing
    between different policy versions with configurable traffic splits."""

    def __init__(self, model_repo: ModelRepositoryPort, training_engine: TrainingEnginePort) -> None:
        self._repo = model_repo
        self._engine = training_engine

    async def select_action(
        self,
        environment: EnvironmentType,
        state: State,
        policy_id: Optional[str] = None,
    ) -> Action:
        """Select an action for the given state using the production policy.
        If no specific policy is provided, the current production policy
        for the environment is used. The action is selected deterministically
        (no exploration) for production inference."""
        policy = await self._repo.get_production_policy(environment) if not policy_id else await self._repo.get_policy(policy_id)
        if not policy:
            logger.warning("no production policy found", extra={"environment": environment})
            return Action(action_id=0, action_name="default")

        prediction = await self._engine.predict(policy.id, state)
        return Action(
            action_id=prediction.get("action_id", 0),
            action_name=f"action_{prediction.get('action_id', 0)}",
            parameters=prediction.get("parameters", {}),
            probability=prediction.get("probability", 1.0),
        )


class MetaLearningService:
    """Meta-learning service using MAML for rapid adaptation.
    Implements Model-Agnostic Meta-Learning to learn policy initializations
    that can be quickly adapted to new services with minimal fine-tuning.
    This is critical for the gstack platform's polyglot architecture, where
    new services with different traffic patterns are frequently deployed."""

    def __init__(self, training_engine: TrainingEnginePort, model_repo: ModelRepositoryPort) -> None:
        self._engine = training_engine
        self._repo = model_repo

    async def meta_train(
        self,
        environment: EnvironmentType,
        config: MetaLearningConfig,
        num_iterations: int = 1000,
    ) -> dict[str, Any]:
        """Execute the MAML meta-training loop.
        For each iteration, sample a batch of tasks (different services),
        perform inner loop adaptation on each task, then compute the
        meta-gradient across all tasks and update the meta-parameters."""
        logger.info("starting meta-training", extra={
            "environment": environment,
            "iterations": num_iterations,
        })

        metrics_history: list[dict[str, float]] = []

        for iteration in range(num_iterations):
            # Sample a batch of tasks (simulated as different reward functions).
            task_batch = self._sample_tasks(environment, config.meta_batch_size)

            iteration_metrics: dict[str, float] = {}
            total_meta_loss = 0.0

            for task in task_batch:
                # Inner loop: adapt to the specific task.
                adapted_params = await self._engine.inner_loop_adapt(
                    task=task,
                    steps=config.inner_steps,
                    learning_rate=config.inner_lr,
                )

                # Evaluate the adapted parameters on the task's validation set.
                val_loss = await self._engine.evaluate_adapted(adapted_params, task)
                total_meta_loss += val_loss

            # Outer loop: meta-update across all tasks.
            meta_loss = total_meta_loss / len(task_batch)
            await self._engine.meta_update(meta_loss, config.outer_lr)

            iteration_metrics["meta_loss"] = meta_loss
            iteration_metrics["iteration"] = float(iteration)
            metrics_history.append(iteration_metrics)

            if iteration % 100 == 0:
                logger.info("meta-training progress", extra={
                    "iteration": iteration,
                    "meta_loss": meta_loss,
                })

        return {
            "status": "completed",
            "iterations": num_iterations,
            "final_meta_loss": metrics_history[-1]["meta_loss"] if metrics_history else 0.0,
        }

    async def adapt_to_service(
        self,
        environment: EnvironmentType,
        service_name: str,
        adaptation_data: list[Transition],
        config: MetaLearningConfig,
    ) -> str:
        """Adapt the meta-learned policy to a specific new service.
        Uses the pre-trained meta-parameters as initialization and
        performs a few gradient steps on the service-specific data.
        This enables rapid onboarding of new services without training
        from scratch, which is essential for the polyglot architecture."""
        logger.info("adapting policy to service", extra={
            "environment": environment,
            "service": service_name,
            "data_size": len(adaptation_data),
        })

        # Load meta-learned parameters.
        policy_id = await self._engine.load_meta_params(environment)

        # Fine-tune on service-specific data.
        for step in range(config.adaptation_steps):
            loss = await self._engine.adapt_step(policy_id, adaptation_data, config.inner_lr)
            logger.debug("adaptation step", extra={"step": step, "loss": loss})

        logger.info("service adaptation complete", extra={"policy_id": policy_id})
        return policy_id

    def _sample_tasks(self, environment: EnvironmentType, batch_size: int) -> list[dict[str, Any]]:
        """Sample a batch of tasks for meta-training.
        Each task represents a different service configuration with
        its own reward function and state distribution."""
        tasks = []
        for i in range(batch_size):
            task = {
                "task_id": f"task_{i}",
                "environment": environment,
                "reward_scale": random.uniform(0.5, 2.0),
                "noise_level": random.uniform(0.0, 0.1),
            }
            tasks.append(task)
        return tasks


# Need datetime import for training service
from datetime import datetime, timezone as _tz  # noqa: E402
