"""
TIER 3 Stress Test Fixtures — Pytest Configuration
====================================================
Shared fixtures and configuration for stress tests.
"""

import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def project_root():
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def knowledge_dir():
    """Return the RL knowledge base directory."""
    return PROJECT_ROOT / ".claude" / "engine" / "feedback" / "knowledge"


@pytest.fixture(scope="session")
def findings_dir():
    """Return the RL findings directory."""
    return PROJECT_ROOT / ".claude" / "engine" / "feedback" / "findings"


@pytest.fixture(scope="session")
def stress_test_config():
    """Return stress test configuration."""
    return {
        "duration_seconds": 30,
        "concurrency": 4,
        "tier": 3,
        "services": [
            "gateway",
            "identity",
            "order",
            "payment",
            "catalog",
            "notification",
            "analytics",
            "schema-registry",
        ],
    }
