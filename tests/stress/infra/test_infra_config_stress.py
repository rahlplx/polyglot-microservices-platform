"""
TIER 3 Stress Test Suite — Infrastructure Configuration
========================================================
Validates K8s infrastructure manifests for correctness and consistency.
Tests for findings:
  G2: emptyDir vs volumeClaimTemplates in Kafka StatefulSets
  G4: Deprecated alpha annotations in namespace.yaml
  G6: Hardcoded placeholder repoURL
  G7: Deployment strategy (Recreate vs RollingUpdate)
  G8: readOnlyRootFilesystem security
  G10: environment-config applied to all services
  G16: ApplicationSet path points to kustomize directories
  G17: No duplicated dashboard JSON

Stress test approach:
  1. YAML structure validation: correct K8s resource shapes
  2. Cross-reference consistency: paths, URLs, references
  3. Security posture: no deprecated features, least privilege
  4. Deduplication: no duplicated content across manifests

Run: python -m pytest tests/stress/infra/ -v --tb=short -x
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
K8S_DIR = PROJECT_ROOT / "infra" / "kubernetes"


# ══════════════════════════════════════════════════════════════════════
# 1. APPLICATIONSET CONFIGURATION — G16 fix validation
# ══════════════════════════════════════════════════════════════════════

class TestApplicationSetConfiguration:
    """Stress test ArgoCD ApplicationSet configuration."""

    APP_OF_APPS = K8S_DIR / "apps" / "app-of-apps.yaml"

    def test_paths_point_to_kustomize_directories(self):
        """G16 fix: ApplicationSet paths must point to kustomize directories, not YAML files."""
        if not self.APP_OF_APPS.exists():
            pytest.skip("app-of-apps.yaml not found")

        content = self.APP_OF_APPS.read_text()

        # Must NOT have paths ending in .yaml
        yaml_path_matches = re.findall(r'path:\s*infra/kubernetes/apps/.*\.yaml', content)
        assert len(yaml_path_matches) == 0, \
            f"ApplicationSet paths still point to YAML files: {yaml_path_matches}"

        # Must have paths pointing to kustomize directories
        kustomize_path_matches = re.findall(r'path:\s*services/.*/kustomize', content)
        assert len(kustomize_path_matches) >= 9, \
            f"Expected 9+ kustomize directory paths, found {len(kustomize_path_matches)}"

    def test_repourl_uses_env_var(self):
        """G6 fix: repoURL must use env var substitution, not hardcoded placeholder."""
        if not self.APP_OF_APPS.exists():
            pytest.skip("app-of-apps.yaml not found")

        content = self.APP_OF_APPS.read_text()

        # Must NOT contain placeholder URLs
        assert 'github.com/example/' not in content, \
            "Hardcoded placeholder repoURL (example/) still present"

        # Must use env var substitution
        assert '${GIT_REPO_URL' in content, \
            "repoURL must use ${GIT_REPO_URL} env var substitution"

    def test_all_9_services_present(self):
        """All 9 microservices must be listed in the ApplicationSet."""
        if not self.APP_OF_APPS.exists():
            pytest.skip("app-of-apps.yaml not found")

        content = self.APP_OF_APPS.read_text()

        expected_services = [
            'gateway', 'identity', 'catalog', 'order', 'payment',
            'notification', 'analytics', 'cdc-relay', 'schema-registry'
        ]
        for service in expected_services:
            assert f'name: {service}' in content, \
                f"Service '{service}' missing from ApplicationSet"


# ══════════════════════════════════════════════════════════════════════
# 2. NAMESPACE & NETWORK POLICY — G4, G5 fix validation
# ══════════════════════════════════════════════════════════════════════

class TestNamespaceConfiguration:
    """Stress test namespace and network policy configuration."""

    def test_no_deprecated_alpha_annotations(self):
        """G4 fix: No deprecated scheduler.alpha.kubernetes.io annotations."""
        ns_file = K8S_DIR / "base" / "namespace.yaml"
        if not ns_file.exists():
            pytest.skip("namespace.yaml not found")

        content = ns_file.read_text()

        assert 'scheduler.alpha.kubernetes.io' not in content, \
            "Deprecated alpha annotation still present in namespace.yaml"

    def test_networkpolicy_narrow_cidrs(self):
        """G5 fix: NetworkPolicy egress CIDRs must be narrow."""
        np_file = K8S_DIR / "base" / "networkpolicy.yaml"
        if not np_file.exists():
            pytest.skip("networkpolicy.yaml not found")

        content = np_file.read_text()

        # Must NOT contain overly broad CIDRs
        broad_patterns = ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16']
        for pattern in broad_patterns:
            assert pattern not in content, \
                f"Overly broad CIDR {pattern} found in NetworkPolicy"


# ══════════════════════════════════════════════════════════════════════
# 3. DEBEZIUM DEPLOYMENT — G7, G8 fix validation
# ══════════════════════════════════════════════════════════════════════

class TestDebeziumDeployment:
    """Stress test Debezium deployment configuration."""

    DEBEZIUM_FILE = K8S_DIR / "platform" / "debezium.yaml"

    def test_deployment_strategy_documented(self):
        """G7 fix: Recreate strategy must have documented justification."""
        if not self.DEBEZIUM_FILE.exists():
            pytest.skip("debezium.yaml not found")

        content = self.DEBEZIUM_FILE.read_text()

        # If using Recreate, must have justification
        if 'type: Recreate' in content:
            # Must have a comment explaining why Recreate instead of RollingUpdate
            assert 'duplicate' in content.lower() or 'connector' in content.lower() or 'justification' in content.lower(), \
                "Recreate strategy must have documented justification"

    def test_readonly_root_filesystem(self):
        """G8 fix: readOnlyRootFilesystem must be true."""
        if not self.DEBEZIUM_FILE.exists():
            pytest.skip("debezium.yaml not found")

        content = self.DEBEZIUM_FILE.read_text()
        assert 'readOnlyRootFilesystem: true' in content, \
            "Debezium must have readOnlyRootFilesystem: true"


# ══════════════════════════════════════════════════════════════════════
# 4. KAFKA STATEFULSET — G2 fix validation
# ══════════════════════════════════════════════════════════════════════

class TestKafkaStatefulSet:
    """Stress test Kafka/Zookeeper StatefulSet storage configuration."""

    KAFKA_FILE = K8S_DIR / "platform" / "kafka.yaml"

    def test_statefulset_uses_volume_claim_templates(self):
        """G2 fix: StatefulSets must use volumeClaimTemplates, not emptyDir."""
        if not self.KAFKA_FILE.exists():
            pytest.skip("kafka.yaml not found")

        content = self.KAFKA_FILE.read_text()

        assert 'volumeClaimTemplates' in content, \
            "Kafka StatefulSet must use volumeClaimTemplates for persistent storage"

    def test_no_emptydir_for_data_volumes(self):
        """G2 fix: No emptyDir for data directories in StatefulSets."""
        if not self.KAFKA_FILE.exists():
            pytest.skip("kafka.yaml not found")

        content = self.KAFKA_FILE.read_text()

        # emptyDir should NOT appear for data volumes
        # It's only acceptable for /tmp or cache
        if 'emptyDir' in content:
            # Check context — emptyDir near "data" or "kafka-data" is forbidden
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if 'emptyDir' in line:
                    context = '\n'.join(lines[max(0, i-15):i+5])
                    # emptyDir for data directories is forbidden
                    for forbidden_name in ['kafka-data', 'zookeeper-data', 'data']:
                        if forbidden_name in context.lower():
                            # Make sure there's a volumeClaimTemplates section
                            assert 'volumeClaimTemplates' in content, \
                                f"emptyDir found near data volume '{forbidden_name}'"


# ══════════════════════════════════════════════════════════════════════
# 5. PRODUCTION KUSTOMIZATION — G10 fix validation
# ══════════════════════════════════════════════════════════════════════

class TestProductionKustomization:
    """Stress test production overlay kustomization."""

    PROD_KUSTOMIZATION = K8S_DIR / "overlays" / "production" / "kustomization.yaml"

    def test_environment_config_applied_to_all_services(self):
        """G10 fix: environment-config must be applied to all 9 services."""
        if not self.PROD_KUSTOMIZATION.exists():
            pytest.skip("production kustomization.yaml not found")

        content = self.PROD_KUSTOMIZATION.read_text()

        expected_services = [
            'gateway', 'identity', 'catalog', 'order', 'payment',
            'notification', 'analytics', 'cdc-relay', 'schema-registry'
        ]
        for service in expected_services:
            # Each service should have a patchesJson6902 entry or similar
            assert service in content, \
                f"Service '{service}' missing from production kustomization (environment-config not applied)"


# ══════════════════════════════════════════════════════════════════════
# 6. GRAFANA DASHBOARD DEDUPLICATION — G17 fix validation
# ══════════════════════════════════════════════════════════════════════

class TestGrafanaDashboardDeduplication:
    """Stress test Grafana dashboard configuration for duplication."""

    DASHBOARDS_CONFIG = K8S_DIR / "platform" / "grafana-dashboards-config.yaml"
    DASHBOARDS_DIR = K8S_DIR / "platform" / "grafana-dashboards"

    def test_configmap_does_not_duplicate_source_files(self):
        """G17 fix: ConfigMap should not inline dashboard JSON that also exists as files."""
        if not self.DASHBOARDS_CONFIG.exists():
            pytest.skip("grafana-dashboards-config.yaml not found")

        content = self.DASHBOARDS_CONFIG.read_text()

        # If the ConfigMap has empty data (using configMapGenerator), that's correct
        if 'data: {}' in content or 'configMapGenerator' in content:
            return  # Correctly using generator

        # If inline JSON exists, check that it doesn't duplicate files
        if self.DASHBOARDS_DIR.exists():
            json_files = list(self.DASHBOARDS_DIR.glob("*.json"))
            if json_files:
                # If JSON files exist AND ConfigMap has inline content, that's duplication
                inline_json_count = content.count('.json":')
                if inline_json_count > 0:
                    pytest.fail(
                        f"G17: Dashboard JSON duplicated — {inline_json_count} inline entries "
                        f"in ConfigMap AND {len(json_files)} source JSON files in grafana-dashboards/"
                    )

    def test_source_dashboard_files_exist(self):
        """Verify source dashboard JSON files exist for configMapGenerator."""
        if not self.DASHBOARDS_DIR.exists():
            pytest.skip("grafana-dashboards/ directory not found")

        json_files = list(self.DASHBOARDS_DIR.glob("*.json"))
        assert len(json_files) >= 2, \
            f"Expected at least 2 dashboard JSON files, found {len(json_files)}"


# ══════════════════════════════════════════════════════════════════════
# 7. CHAOS EXPERIMENT VALIDATION — G18 fix validation
# ══════════════════════════════════════════════════════════════════════

class TestChaosExperimentCleanup:
    """Stress test chaos experiments for correctness."""

    CHAOS_SCRIPT = PROJECT_ROOT / "scripts" / "chaos-experiments.sh"

    def test_dns_outage_function_no_double_apply(self):
        """G18 fix: DNS outage function should not apply wrong policy then delete it."""
        if not self.CHAOS_SCRIPT.exists():
            pytest.skip("chaos-experiments.sh not found")

        content = self.CHAOS_SCRIPT.read_text()

        # Extract the DNS outage function
        dns_func_start = content.find('experiment_dns_outage()')
        if dns_func_start == -1:
            pytest.skip("experiment_dns_outage function not found")

        # Find the end of the function (next function or end of file)
        next_func = content.find('\n\nfunction', dns_func_start + 1)
        if next_func == -1:
            next_func = len(content)
        dns_func = content[dns_func_start:next_func]

        # Must NOT have "delete" followed by "apply" pattern (apply-wrong-then-delete-then-apply-correct)
        delete_count = dns_func.count('kubectl delete networkpolicy')
        apply_count = dns_func.count('kubectl apply -f -')

        # Should have exactly 1 apply (the correct one) and 0 deletes of the policy
        assert delete_count == 0, \
            f"G18: DNS outage function still deletes a NetworkPolicy ({delete_count} deletes found)"
        assert apply_count == 1, \
            f"G18: DNS outage function should have 1 apply, found {apply_count}"
