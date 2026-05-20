"""
TIER 3 Stress Test Configuration
=================================
Shared fixtures and configuration for all stress test suites.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "stress: TIER 3 stress test (load, chaos, edge-case)"
    )
    config.addinivalue_line(
        "markers", "boundary: Boundary value stress test"
    )
    config.addinivalue_line(
        "markers", "concurrent: Concurrent access stress test"
    )
    config.addinivalue_line(
        "markers", "security: Security scanning stress test"
    )
    config.addinivalue_line(
        "markers", "infra: Infrastructure configuration stress test"
    )


@pytest.fixture(scope="session")
def project_root():
    """Provide project root path."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def k8s_dir(project_root):
    """Provide K8s infrastructure directory."""
    return project_root / "infra" / "kubernetes"


@pytest.fixture(scope="session")
def services_dir(project_root):
    """Provide services directory."""
    return project_root / "services"
