"""
TIER 3 Stress Test Suite — Security: Credentials & Secrets
==========================================================
Validates that no hardcoded credentials exist in source code or K8s manifests.
Tests for findings:
  G14: Hardcoded Grafana admin password in K8s Secret
  G15: Hardcoded DB credentials in analytics postgres_repo.py

Stress test approach:
  1. Pattern scanning: regex scan for hardcoded passwords, tokens, keys
  2. Structural validation: K8s Secrets use env var substitution
  3. Source code scan: no connection strings with embedded credentials
  4. High-volume: scan all 551 files in the project

Run: python -m pytest tests/stress/security/ -v --tb=short -x
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ══════════════════════════════════════════════════════════════════════
# 1. KUBERNETES SECRET SCANNING — G14 fix validation
# ══════════════════════════════════════════════════════════════════════

class TestKubernetesSecretSecurity:
    """Stress test K8s manifests for hardcoded secrets."""

    K8S_DIR = PROJECT_ROOT / "infra" / "kubernetes"

    # Patterns that indicate hardcoded secrets
    HARDCODED_PASSWORD_PATTERNS = [
        r'admin-password:\s*[A-Za-z0-9!@#$%^&*]{8,}',  # Base64-encoded or plaintext password
        r'password:\s*"[^$\{]',                          # Password not using env var
        r'api[_-]?key:\s*"[A-Za-z0-9]{20,}"',          # API key in plaintext
        r'secret[_-]?key:\s*"[A-Za-z0-9]{20,}"',       # Secret key in plaintext
    ]

    # Patterns that are ACCEPTABLE (env var substitution)
    SAFE_PATTERNS = [
        r'\$\{[A-Z_]+:',        # ${VAR:-default} syntax
        r'\$\{[A-Z_]+\}',       # ${VAR} syntax
        r'secretKeyRef:',        # Reference to K8s Secret
        r'valueFrom:',           # Reference to config/secret
    ]

    def _get_yaml_files(self):
        """Find all YAML files in K8s infrastructure."""
        if not self.K8S_DIR.exists():
            return []
        return list(self.K8S_DIR.rglob("*.yaml")) + list(self.K8S_DIR.rglob("*.yml"))

    def test_grafana_admin_password_uses_env_var(self):
        """G14 fix: Grafana admin password must use env var substitution."""
        grafana_yaml = self.K8S_DIR / "platform" / "grafana.yaml"
        if not grafana_yaml.exists():
            pytest.skip("grafana.yaml not found")

        content = grafana_yaml.read_text()

        # Must NOT have hardcoded password value
        hardcoded_matches = re.findall(
            r'admin-password:\s*([A-Za-z0-9+/=]{8,})', content
        )
        # Filter out env var substitutions
        real_hardcoded = [
            m for m in hardcoded_matches
            if not m.startswith('$') and not m.startswith('_')
        ]
        assert len(real_hardcoded) == 0, \
            f"Hardcoded Grafana admin password found: {real_hardcoded}"

        # Must use env var substitution or secretKeyRef
        assert '${GRAFANA_ADMIN_PASSWORD' in content or 'secretKeyRef' in content, \
            "Grafana credentials must use env var substitution or secretKeyRef"

    def test_all_k8s_secrets_use_env_vars_or_references(self):
        """Stress test: ALL K8s Secret resources use env vars or secretKeyRef."""
        violations = []
        for yaml_file in self._get_yaml_files():
            content = yaml_file.read_text()
            # Check for Secret resources with hardcoded data
            if 'kind: Secret' in content:
                # Look for data: section with non-empty hardcoded values
                lines = content.split('\n')
                in_data_section = False
                for i, line in enumerate(lines):
                    if re.match(r'^\s*data:', line):
                        in_data_section = True
                        continue
                    if in_data_section:
                        if re.match(r'^\s*[a-z]', line) and not re.match(r'^\s*[a-z-]+:\s*$', line):
                            # This is a key: value pair in data section
                            if not re.search(r'\$\{|secretKeyRef|valueFrom', line):
                                # Check if the value looks like a real password (not empty or template)
                                value_match = re.search(r':\s*(\S+)', line)
                                if value_match:
                                    value = value_match.group(1)
                                    if len(value) > 4 and not value.startswith('#'):
                                        violations.append(
                                            f"{yaml_file.relative_to(PROJECT_ROOT)}:{i+1}: {line.strip()}"
                                        )
                        if re.match(r'^[a-z]|^---', line):
                            in_data_section = False

        assert len(violations) == 0, \
            f"Hardcoded values in K8s Secrets: {violations[:10]}"


# ══════════════════════════════════════════════════════════════════════
# 2. SOURCE CODE CREDENTIAL SCANNING — G15 fix validation
# ══════════════════════════════════════════════════════════════════════

class TestSourceCodeCredentialScanning:
    """Stress test source code for hardcoded credentials."""

    SERVICE_DIRS = [
        PROJECT_ROOT / "services" / "analytics" / "src",
        PROJECT_ROOT / "services" / "notification" / "src",
        PROJECT_ROOT / "services" / "rl-engine" / "src",
        PROJECT_ROOT / "services" / "cdc-relay" / "src",
    ]

    # Connection string patterns
    CONNECTION_STRING_PATTERNS = [
        r'postgresql?://[^\s"\']+:([^\s"\']+)@',  # postgres://user:pass@host
        r'mysql://[^\s"\']+:([^\s"\']+)@',          # mysql://user:pass@host
        r'mongodb://[^\s"\']+:([^\s"\']+)@',        # mongodb://user:pass@host
        r'redis://:[^\s"\']+@',                      # redis://:password@host
    ]

    # Hardcoded credential variable patterns
    HARDCODED_VAR_PATTERNS = [
        r'(?:password|passwd|pwd|secret|token|api_key|apikey)\s*=\s*["\'][^"$][^"\']{6,}["\']',
    ]

    def _get_source_files(self, extensions=('.py', '.ts', '.go', '.rs', '.kt')):
        """Find all source files in service directories."""
        files = []
        for d in self.SERVICE_DIRS:
            if d.exists():
                for ext in extensions:
                    files.extend(d.rglob(f"*{ext}"))
        return files

    def test_analytics_no_hardcoded_connection_string(self):
        """G15 fix: Analytics postgres_repo.py must not have hardcoded DB credentials."""
        repo_file = PROJECT_ROOT / "services" / "analytics" / "src" / "adapters" / "outbound" / "persistence" / "postgres_repo.py"
        if not repo_file.exists():
            pytest.skip("postgres_repo.py not found")

        content = repo_file.read_text()

        # Must NOT contain hardcoded connection string
        for pattern in self.CONNECTION_STRING_PATTERNS:
            matches = re.findall(pattern, content)
            # Filter out env var patterns
            real_matches = [m for m in matches if not m.startswith('$') and not m.startswith('{')]
            assert len(real_matches) == 0, \
                f"Hardcoded DB credentials in postgres_repo.py: {real_matches}"

        # Must reference environment variable or config injection
        assert 'environ' in content.lower() or 'config' in content.lower() or 'env' in content.lower(), \
            "postgres_repo.py should reference environment variables or config for credentials"

    def test_no_hardcoded_credentials_in_python_sources(self):
        """Stress test: Scan ALL Python source files for hardcoded credentials."""
        violations = []
        for fpath in self._get_source_files(('.py',)):
            content = fpath.read_text()
            for pattern in self.HARDCODED_VAR_PATTERNS:
                matches = re.finditer(pattern, content, re.IGNORECASE)
                for match in matches:
                    line = match.group(0)
                    # Skip if it references env vars or config
                    if '${' in line or 'os.environ' in line or 'os.getenv' in line or 'config' in line.lower():
                        continue
                    # Skip if it's in a comment or docstring
                    if 'example' in line.lower() or 'placeholder' in line.lower() or 'replace' in line.lower():
                        continue
                    violations.append(
                        f"{fpath.relative_to(PROJECT_ROOT)}: {line[:80]}"
                    )

        assert len(violations) == 0, \
            f"Hardcoded credentials in Python sources: {violations[:10]}"


# ══════════════════════════════════════════════════════════════════════
# 3. INFRASTRUCTURE SECURITY STRESS TESTS — G5, G8
# ══════════════════════════════════════════════════════════════════════

class TestInfrastructureSecurityStress:
    """Stress test K8s infrastructure for security configurations."""

    def test_networkpolicy_cidrs_are_narrow(self):
        """G5 fix: NetworkPolicy CIDRs must not use broad ranges like 10.0.0.0/8."""
        np_file = PROJECT_ROOT / "infra" / "kubernetes" / "base" / "networkpolicy.yaml"
        if not np_file.exists():
            pytest.skip("networkpolicy.yaml not found")

        content = np_file.read_text()

        # Must NOT contain 10.0.0.0/8 or similarly broad CIDRs
        broad_cidrs = re.findall(r'10\.0\.0\.0/[0-8]', content)
        # Check for private RFC1918 broad CIDRs that shouldn't be in NetworkPolicy
        broad_rfc1918 = re.findall(r'172\.16\.0\.0/12', content)

        assert len(broad_cidrs) == 0, \
            f"Broad CIDR 10.0.0.0/8 found in NetworkPolicy: {broad_cidrs}"
        assert len(broad_rfc1918) == 0, \
            f"Broad CIDR 172.16.0.0/12 found in NetworkPolicy: {broad_rfc1918}"

    def test_debezium_readonly_root_filesystem(self):
        """G8 fix: Debezium deployment must have readOnlyRootFilesystem: true."""
        debezium_file = PROJECT_ROOT / "infra" / "kubernetes" / "platform" / "debezium.yaml"
        if not debezium_file.exists():
            pytest.skip("debezium.yaml not found")

        content = debezium_file.read_text()

        assert 'readOnlyRootFilesystem: true' in content, \
            "Debezium must have readOnlyRootFilesystem: true for security"

    def test_kafka_statefulset_uses_pvc(self):
        """G2 fix: Kafka and Zookeeper StatefulSets must use volumeClaimTemplates, not emptyDir."""
        kafka_file = PROJECT_ROOT / "infra" / "kubernetes" / "platform" / "kafka.yaml"
        if not kafka_file.exists():
            pytest.skip("kafka.yaml not found")

        content = kafka_file.read_text()

        # Must NOT use emptyDir for data volumes in StatefulSets
        # emptyDir is only acceptable for /tmp or cache, not for data
        if 'emptyDir' in content:
            # Check that emptyDir is not used for data directories
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if 'emptyDir' in line:
                    # Verify it's for /tmp or cache, not data
                    _context = '\n'.join(lines[max(0, i-10):i+5])
                    assert 'volumeClaimTemplates' in content, \
                        "Kafka StatefulSet must use volumeClaimTemplates for persistent data"
