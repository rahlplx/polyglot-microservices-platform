"""
Tests for the Debezium connector configuration in the CDC Relay K8s ConfigMap.

The CDC Relay service is a stub (Debezium connector with no application code).
These tests validate that the Debezium connector configuration defined in the
K8s ConfigMap is valid and contains all required fields.
"""

from __future__ import annotations

import os
import pytest
import yaml


CONFIGMAP_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "..",
    "infra",
    "kubernetes",
    "platform",
    "debezium.yaml",
)


def _load_debezium_config() -> list[dict]:
    """Load and parse the Debezium YAML file, returning all documents."""
    with open(CONFIGMAP_PATH, "r") as f:
        return list(yaml.safe_load_all(f))


class TestDebeziumConfigMap:
    """Tests for the Debezium ConfigMap validity."""

    @pytest.fixture
    def documents(self) -> list[dict]:
        return _load_debezium_config()

    @pytest.fixture
    def configmap(self, documents: list[dict]) -> dict:
        """Find the ConfigMap document among all K8s resources."""
        for doc in documents:
            if doc and doc.get("kind") == "ConfigMap":
                return doc
        pytest.fail("No ConfigMap found in debezium.yaml")

    def test_configmap_exists(self, documents: list[dict]) -> None:
        kinds = [doc.get("kind") for doc in documents if doc]
        assert "ConfigMap" in kinds

    def test_configmap_has_required_name(self, configmap: dict) -> None:
        assert configmap["metadata"]["name"] == "debezium-config"

    def test_configmap_has_kafka_bootstrap_servers(self, configmap: dict) -> None:
        data = configmap["data"]
        assert "CONNECT_BOOTSTRAP_SERVERS" in data
        assert "kafka" in data["CONNECT_BOOTSTRAP_SERVERS"].lower()

    def test_configmap_has_group_id(self, configmap: dict) -> None:
        data = configmap["data"]
        assert "CONNECT_GROUP_ID" in data
        assert len(data["CONNECT_GROUP_ID"]) > 0

    def test_configmap_has_storage_topics(self, configmap: dict) -> None:
        data = configmap["data"]
        assert "CONNECT_CONFIG_STORAGE_TOPIC" in data
        assert "CONNECT_OFFSET_STORAGE_TOPIC" in data
        assert "CONNECT_STATUS_STORAGE_TOPIC" in data

    def test_configmap_has_replication_factor(self, configmap: dict) -> None:
        data = configmap["data"]
        for key in (
            "CONNECT_CONFIG_STORAGE_REPLICATION_FACTOR",
            "CONNECT_OFFSET_STORAGE_REPLICATION_FACTOR",
            "CONNECT_STATUS_STORAGE_REPLICATION_FACTOR",
        ):
            assert key in data
            assert int(data[key]) >= 1

    def test_configmap_has_converters(self, configmap: dict) -> None:
        data = configmap["data"]
        assert "CONNECT_KEY_CONVERTER" in data
        assert "CONNECT_VALUE_CONVERTER" in data

    def test_configmap_has_plugin_path(self, configmap: dict) -> None:
        data = configmap["data"]
        assert "CONNECT_PLUGIN_PATH" in data

    def test_configmap_has_database_server_name(self, configmap: dict) -> None:
        data = configmap["data"]
        assert "DATABASE_SERVER_NAME" in data


class TestDebeziumDeployment:
    """Tests for the Debezium Deployment validity."""

    @pytest.fixture
    def documents(self) -> list[dict]:
        return _load_debezium_config()

    @pytest.fixture
    def deployment(self, documents: list[dict]) -> dict:
        for doc in documents:
            if doc and doc.get("kind") == "Deployment":
                return doc
        pytest.fail("No Deployment found in debezium.yaml")

    def test_deployment_exists(self, documents: list[dict]) -> None:
        kinds = [doc.get("kind") for doc in documents if doc]
        assert "Deployment" in kinds

    def test_deployment_uses_configmap(self, deployment: dict) -> None:
        containers = deployment["spec"]["template"]["spec"]["containers"]
        main_container = containers[0]
        env_from = main_container.get("envFrom", [])
        config_map_refs = [
            ef["configMapRef"]["name"]
            for ef in env_from
            if "configMapRef" in ef
        ]
        assert "debezium-config" in config_map_refs

    def test_deployment_has_health_probes(self, deployment: dict) -> None:
        containers = deployment["spec"]["template"]["spec"]["containers"]
        main_container = containers[0]
        assert "livenessProbe" in main_container
        assert "readinessProbe" in main_container

    def test_deployment_security_context(self, deployment: dict) -> None:
        containers = deployment["spec"]["template"]["spec"]["containers"]
        main_container = containers[0]
        sc = main_container.get("securityContext", {})
        assert sc.get("runAsNonRoot") is True
        assert "ALL" in sc.get("capabilities", {}).get("drop", [])
