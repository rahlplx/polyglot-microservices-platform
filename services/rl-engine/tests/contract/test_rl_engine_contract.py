"""
Contract test for the RL Engine gRPC interface.

Verifies that the RL Engine service implements the gRPC service
interface required by the proto specification. Since the RL Engine
uses a custom proto, this contract test validates the handler
surface area and request/response patterns.
"""

from __future__ import annotations

import pytest

from src.infrastructure import Container, Config
from src.domain.services import (
    InferenceService,
    MetaLearningService,
    PolicyService,
    TrainingService,
)


# ---------------------------------------------------------------------------
# Contract: Service surface area
# ---------------------------------------------------------------------------

class TestRLEngineServiceContract:
    """Contract tests for the RL Engine gRPC service.

    Validates that the service container exposes all required services
    for the gRPC handler to delegate to:
    - PolicyService: create_policy, get_policy, deploy_policy
    - TrainingService: submit_training_job, run_training_step
    - InferenceService: select_action
    - MetaLearningService: meta_train, adapt_to_service
    """

    def test_container_exposes_policy_service(self) -> None:
        container = Container(Config())
        assert hasattr(container, "policy_service")
        assert isinstance(container.policy_service, PolicyService)

    def test_container_exposes_training_service(self) -> None:
        container = Container(Config())
        assert hasattr(container, "training_service")
        assert isinstance(container.training_service, TrainingService)

    def test_container_exposes_inference_service(self) -> None:
        container = Container(Config())
        assert hasattr(container, "inference_service")
        assert isinstance(container.inference_service, InferenceService)

    def test_container_exposes_meta_learning_service(self) -> None:
        container = Container(Config())
        assert hasattr(container, "meta_learning_service")
        assert isinstance(container.meta_learning_service, MetaLearningService)

    def test_policy_service_has_required_methods(self) -> None:
        container = Container(Config())
        ps = container.policy_service
        assert callable(getattr(ps, "create_policy", None))
        assert callable(getattr(ps, "get_policy", None))
        assert callable(getattr(ps, "deploy_policy", None))

    def test_training_service_has_required_methods(self) -> None:
        container = Container(Config())
        ts = container.training_service
        assert callable(getattr(ts, "submit_training_job", None))
        assert callable(getattr(ts, "run_training_step", None))

    def test_inference_service_has_required_methods(self) -> None:
        container = Container(Config())
        isvc = container.inference_service
        assert callable(getattr(isvc, "select_action", None))

    def test_meta_learning_service_has_required_methods(self) -> None:
        container = Container(Config())
        mls = container.meta_learning_service
        assert callable(getattr(mls, "meta_train", None))
        assert callable(getattr(mls, "adapt_to_service", None))
