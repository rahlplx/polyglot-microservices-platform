"""
Unit tests for the RL Engine domain services.

Tests the RL engine with mocked inference/training ports. Validates
policy evaluation, action selection, reward computation, and training
job lifecycle.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from src.domain.models import (
    Action,
    Episode,
    EnvironmentType,
    MetaLearningConfig,
    Policy,
    PolicyType,
    Reward,
    State,
    TrainingJob,
    TrainingStatus,
    Transition,
)
from src.domain.ports import EnvironmentPort, ModelRepositoryPort, TrainingEnginePort
from src.domain.services import (
    InferenceService,
    MetaLearningService,
    PolicyService,
    TrainingService,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_model_repo() -> AsyncMock:
    repo = AsyncMock(spec=ModelRepositoryPort)
    repo.save_policy = AsyncMock(side_effect=lambda p: p)
    repo.get_policy = AsyncMock(return_value=None)
    repo.get_production_policy = AsyncMock(return_value=None)
    repo.save_training_job = AsyncMock(side_effect=lambda j: j)
    repo.get_training_job = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_training_engine() -> AsyncMock:
    engine = AsyncMock(spec=TrainingEnginePort)
    engine.predict.return_value = {
        "action_id": 1,
        "probability": 0.75,
        "parameters": {},
    }
    engine.train_step.return_value = {
        "loss": 0.42,
        "gradient_norm": 0.05,
        "entropy": 0.9,
    }
    engine.inner_loop_adapt.return_value = "adapted_task_0"
    engine.evaluate_adapted.return_value = 0.25
    engine.load_meta_params.return_value = "meta_policy_NOTIFICATION_DELIVERY"
    engine.adapt_step.return_value = 0.15
    return engine


@pytest.fixture
def mock_environment() -> AsyncMock:
    env = AsyncMock(spec=EnvironmentPort)
    env.reset.return_value = State(
        features={"request_rate": 0.5, "error_rate": 0.02, "latency_p99": 0.3}
    )
    env.step.return_value = {
        "next_state": State(features={"request_rate": 0.6, "error_rate": 0.01, "latency_p99": 0.2}),
        "reward": Reward(value=0.85),
        "done": False,
        "info": {},
    }
    return env


@pytest.fixture
def policy_service(mock_model_repo: AsyncMock) -> PolicyService:
    return PolicyService(model_repo=mock_model_repo)


@pytest.fixture
def training_service(
    mock_model_repo: AsyncMock,
    mock_training_engine: AsyncMock,
    mock_environment: AsyncMock,
) -> TrainingService:
    return TrainingService(
        model_repo=mock_model_repo,
        training_engine=mock_training_engine,
        environment=mock_environment,
    )


@pytest.fixture
def inference_service(
    mock_model_repo: AsyncMock,
    mock_training_engine: AsyncMock,
) -> InferenceService:
    return InferenceService(
        model_repo=mock_model_repo,
        training_engine=mock_training_engine,
    )


@pytest.fixture
def meta_learning_service(
    mock_training_engine: AsyncMock,
    mock_model_repo: AsyncMock,
) -> MetaLearningService:
    return MetaLearningService(
        training_engine=mock_training_engine,
        model_repo=mock_model_repo,
    )


# ---------------------------------------------------------------------------
# PolicyService
# ---------------------------------------------------------------------------

class TestPolicyService:
    """Tests for PolicyService."""

    @pytest.mark.asyncio
    async def test_create_policy(self, policy_service: PolicyService) -> None:
        policy = await policy_service.create_policy(
            name="test-policy",
            environment=EnvironmentType.NOTIFICATION_DELIVERY,
            policy_type=PolicyType.EPSILON_GREEDY,
        )
        assert policy.name == "test-policy"
        assert policy.environment == EnvironmentType.NOTIFICATION_DELIVERY
        assert policy.policy_type == PolicyType.EPSILON_GREEDY
        assert policy.is_production is False

    @pytest.mark.asyncio
    async def test_get_policy(self, policy_service: PolicyService, mock_model_repo: AsyncMock) -> None:
        mock_model_repo.get_policy.return_value = Policy(name="existing")
        result = await policy_service.get_policy("some-id")
        assert result is not None
        assert result.name == "existing"

    @pytest.mark.asyncio
    async def test_deploy_policy(
        self, policy_service: PolicyService, mock_model_repo: AsyncMock
    ) -> None:
        trained_policy = Policy(
            id="p-1",
            name="trained",
            environment=EnvironmentType.NOTIFICATION_DELIVERY,
            trained_at=datetime.now(timezone.utc),
        )
        mock_model_repo.get_policy.return_value = trained_policy
        mock_model_repo.get_production_policy.return_value = None

        result = await policy_service.deploy_policy("p-1")
        assert result.is_production is True

    @pytest.mark.asyncio
    async def test_deploy_untrained_policy_raises(
        self, policy_service: PolicyService, mock_model_repo: AsyncMock
    ) -> None:
        untrained = Policy(id="p-2", name="untrained", trained_at=None)
        mock_model_repo.get_policy.return_value = untrained
        with pytest.raises(ValueError, match="trained before deployment"):
            await policy_service.deploy_policy("p-2")


# ---------------------------------------------------------------------------
# InferenceService — action selection
# ---------------------------------------------------------------------------

class TestActionSelection:
    """Tests for InferenceService.select_action()."""

    @pytest.mark.asyncio
    async def test_selects_action_from_production_policy(
        self,
        inference_service: InferenceService,
        mock_model_repo: AsyncMock,
    ) -> None:
        production_policy = Policy(
            id="prod-1",
            environment=EnvironmentType.NOTIFICATION_DELIVERY,
            is_production=True,
        )
        mock_model_repo.get_production_policy.return_value = production_policy

        state = State(features={"error_rate": 0.05})
        action = await inference_service.select_action(
            environment=EnvironmentType.NOTIFICATION_DELIVERY,
            state=state,
        )
        assert isinstance(action, Action)
        assert action.action_id == 1

    @pytest.mark.asyncio
    async def test_returns_default_action_when_no_policy(
        self,
        inference_service: InferenceService,
        mock_model_repo: AsyncMock,
    ) -> None:
        mock_model_repo.get_production_policy.return_value = None
        state = State(features={"error_rate": 0.05})
        action = await inference_service.select_action(
            environment=EnvironmentType.NOTIFICATION_DELIVERY,
            state=state,
        )
        assert action.action_id == 0
        assert action.action_name == "default"


# ---------------------------------------------------------------------------
# Reward computation
# ---------------------------------------------------------------------------

class TestRewardComputation:
    """Tests for reward-related logic in the domain models."""

    def test_reward_total_returns_scalar_value(self) -> None:
        reward = Reward(value=0.9)
        assert reward.total() == 0.9

    def test_reward_total_returns_sum_of_components(self) -> None:
        reward = Reward(value=0.0, components={"latency": 0.6, "error_rate": 0.3})
        assert abs(reward.total() - 0.9) < 1e-9

    def test_episode_accumulates_reward(self) -> None:
        episode = Episode()
        t1 = Transition(reward=Reward(value=0.5))
        t2 = Transition(reward=Reward(value=0.3))
        episode.add_transition(t1)
        episode.add_transition(t2)
        assert abs(episode.total_reward - 0.8) < 1e-9
        assert episode.length == 2
        assert abs(episode.average_reward - 0.4) < 1e-9


# ---------------------------------------------------------------------------
# TrainingService
# ---------------------------------------------------------------------------

class TestTrainingService:
    """Tests for TrainingService."""

    @pytest.mark.asyncio
    async def test_submit_training_job(
        self, training_service: TrainingService, mock_model_repo: AsyncMock
    ) -> None:
        policy = Policy(id="p-1", environment=EnvironmentType.CIRCUIT_BREAKER)
        mock_model_repo.get_policy.return_value = policy

        job = await training_service.submit_training_job(policy_id="p-1")
        assert job.policy_id == "p-1"
        assert job.status == TrainingStatus.PENDING

    @pytest.mark.asyncio
    async def test_submit_training_job_raises_for_missing_policy(
        self, training_service: TrainingService, mock_model_repo: AsyncMock
    ) -> None:
        mock_model_repo.get_policy.return_value = None
        with pytest.raises(ValueError, match="not found"):
            await training_service.submit_training_job(policy_id="missing")


# ---------------------------------------------------------------------------
# MetaLearningService
# ---------------------------------------------------------------------------

class TestMetaLearningService:
    """Tests for MetaLearningService."""

    @pytest.mark.asyncio
    async def test_meta_train_returns_completed_status(
        self, meta_learning_service: MetaLearningService
    ) -> None:
        config = MetaLearningConfig(inner_steps=1, meta_batch_size=2)
        result = await meta_learning_service.meta_train(
            environment=EnvironmentType.NOTIFICATION_DELIVERY,
            config=config,
            num_iterations=2,
        )
        assert result["status"] == "completed"
        assert result["iterations"] == 2

    @pytest.mark.asyncio
    async def test_adapt_to_service(
        self,
        meta_learning_service: MetaLearningService,
        mock_training_engine: AsyncMock,
    ) -> None:
        config = MetaLearningConfig(adaptation_steps=2)
        data = [Transition(reward=Reward(value=0.5))]
        policy_id = await meta_learning_service.adapt_to_service(
            environment=EnvironmentType.NOTIFICATION_DELIVERY,
            service_name="catalog",
            adaptation_data=data,
            config=config,
        )
        assert policy_id is not None
        assert mock_training_engine.adapt_step.call_count == 2
