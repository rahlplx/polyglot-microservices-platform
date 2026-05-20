"""
Shared fixtures for mTLS verification test suite.

Provides:
- kubectl exec helpers
- SPIRE API client
- Certificate parsing utilities
- Service pair definitions
- Kubernetes cluster access helpers
"""

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TRUST_DOMAIN = "trust.example.org"
NAMESPACE = "production"
AGENT_SOCKET_PATH = "/run/spire/sockets/agent.sock"
SVID_TTL_SECONDS = 3600  # 1 hour
CA_TTL_SECONDS = 86400  # 24 hours
ROOT_CA_TTL_SECONDS = 259200  # 72 hours
GRACE_PERIOD_SECONDS = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Service Registry
# ---------------------------------------------------------------------------
SERVICE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "gateway": {
        "language": "go",
        "port": 50051,
        "service_account": "gateway",
        "spiffe_id": f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/gateway",
        "dns_names": [
            "gateway",
            "gateway.production",
            "gateway.production.svc",
            "gateway.production.svc.cluster.local",
        ],
    },
    "identity": {
        "language": "rust",
        "port": 50052,
        "service_account": "identity",
        "spiffe_id": f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/identity",
        "dns_names": [
            "identity",
            "identity.production",
            "identity.production.svc",
            "identity.production.svc.cluster.local",
        ],
    },
    "catalog": {
        "language": "typescript",
        "port": 50053,
        "service_account": "catalog",
        "spiffe_id": f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/catalog",
        "dns_names": [
            "catalog",
            "catalog.production",
            "catalog.production.svc",
            "catalog.production.svc.cluster.local",
        ],
    },
    "order": {
        "language": "kotlin",
        "port": 50054,
        "service_account": "order",
        "spiffe_id": f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/order",
        "dns_names": [
            "order",
            "order.production",
            "order.production.svc",
            "order.production.svc.cluster.local",
        ],
    },
    "payment": {
        "language": "go",
        "port": 50055,
        "service_account": "payment",
        "spiffe_id": f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/payment",
        "dns_names": [
            "payment",
            "payment.production",
            "payment.production.svc",
            "payment.production.svc.cluster.local",
        ],
    },
    "notification": {
        "language": "python",
        "port": 50056,
        "service_account": "notification",
        "spiffe_id": f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/notification",
        "dns_names": [
            "notification",
            "notification.production",
            "notification.production.svc",
            "notification.production.svc.cluster.local",
        ],
    },
    "analytics": {
        "language": "python",
        "port": 50057,
        "service_account": "analytics",
        "spiffe_id": f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/analytics",
        "dns_names": [
            "analytics",
            "analytics.production",
            "analytics.production.svc",
            "analytics.production.svc.cluster.local",
        ],
    },
    "cdc-relay": {
        "language": "python",
        "port": 50058,
        "service_account": "cdc-relay",
        "spiffe_id": f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/cdc-relay",
        "dns_names": [
            "cdc-relay",
            "cdc-relay.production",
            "cdc-relay.production.svc",
            "cdc-relay.production.svc.cluster.local",
        ],
    },
    "schema-registry": {
        "language": "go",
        "port": 50051,
        "service_account": "schema-registry",
        "spiffe_id": f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/schema-registry",
        "dns_names": [
            "schema-registry",
            "schema-registry.production",
            "schema-registry.production.svc",
            "schema-registry.production.svc.cluster.local",
        ],
    },
}

# mTLS handshake pairs: (source, target, description)
HANDSHAKE_PAIRS: List[Tuple[str, str, str]] = [
    ("gateway", "payment", "Go to Go"),
    ("gateway", "order", "Go to Kotlin"),
    ("order", "catalog", "Kotlin to TypeScript"),
    ("order", "notification", "Kotlin to Python"),
    ("analytics", "schema-registry", "Python to Go"),
    ("identity", "gateway", "Rust to Go"),
    ("identity", "catalog", "Rust to TypeScript"),
    ("identity", "order", "Rust to Kotlin"),
    ("identity", "payment", "Rust to Go"),
    ("identity", "notification", "Rust to Python"),
    ("identity", "analytics", "Rust to Python"),
    ("identity", "cdc-relay", "Rust to Python"),
    ("identity", "schema-registry", "Rust to Go"),
]

ALL_SERVICES = list(SERVICE_REGISTRY.keys())


# ---------------------------------------------------------------------------
# kubectl helpers
# ---------------------------------------------------------------------------
class KubectlHelper:
    """Helper for executing kubectl commands against the cluster."""

    def __init__(self, namespace: str = NAMESPACE):
        self.namespace = namespace

    def _run(self, cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
        """Run a kubectl command and return the result."""
        full_cmd = ["kubectl", "-n", self.namespace] + cmd
        return subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def get_pod_name(self, service: str) -> Optional[str]:
        """Get the first running pod name for a service by label."""
        result = self._run([
            "get", "pods",
            "-l", f"app.kubernetes.io/name={service}",
            "--field-selector=status.phase=Running",
            "-o", "jsonpath={.items[0].metadata.name}",
        ])
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()

        # Fallback: try alternate label
        result = self._run([
            "get", "pods",
            "-l", f"app={service}",
            "--field-selector=status.phase=Running",
            "-o", "jsonpath={.items[0].metadata.name}",
        ])
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None

    def exec_in_pod(
        self, pod_name: str, command: List[str], container: Optional[str] = None
    ) -> Tuple[int, str, str]:
        """Execute a command in a pod and return (returncode, stdout, stderr)."""
        cmd = ["exec", pod_name]
        if container:
            cmd.extend(["-c", container])
        cmd.append("--")
        cmd.extend(command)
        result = self._run(cmd, timeout=60)
        return result.returncode, result.stdout, result.stderr

    def get_daemonset_status(self, name: str) -> Optional[Dict[str, int]]:
        """Get DaemonSet status: desired, ready, available."""
        result = self._run([
            "get", "daemonset", name,
            "-o", "json",
        ])
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
            status = data.get("status", {})
            return {
                "desired": status.get("desiredNumberScheduled", 0),
                "ready": status.get("numberReady", 0),
                "available": status.get("numberAvailable", 0),
            }
        except json.JSONDecodeError:
            return None

    def get_statefulset_replicas(self, name: str) -> Optional[Dict[str, int]]:
        """Get StatefulSet replica status."""
        result = self._run([
            "get", "statefulset", name,
            "-o", "json",
        ])
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
            spec_replicas = data.get("spec", {}).get("replicas", 0)
            ready_replicas = data.get("status", {}).get("readyReplicas", 0)
            return {
                "desired": spec_replicas,
                "ready": ready_replicas,
            }
        except json.JSONDecodeError:
            return None

    def configmap_exists(self, name: str) -> bool:
        """Check if a ConfigMap exists."""
        result = self._run(["get", "configmap", name, "-o", "name"])
        return result.returncode == 0 and result.stdout.strip() != ""

    def get_configmap_data(self, name: str) -> Optional[Dict[str, str]]:
        """Get ConfigMap data."""
        result = self._run(["get", "configmap", name, "-o", "json"])
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
            return data.get("data", {})
        except json.JSONDecodeError:
            return None


# ---------------------------------------------------------------------------
# SPIRE API Client
# ---------------------------------------------------------------------------
class SpireApiClient:
    """Client for interacting with SPIRE Server and Agent APIs."""

    def __init__(
        self,
        kubectl: KubectlHelper,
        server_pod: str = "spire-server-0",
        agent_socket: str = AGENT_SOCKET_PATH,
    ):
        self.kubectl = kubectl
        self.server_pod = server_pod
        self.agent_socket = agent_socket

    def server_healthcheck(self) -> Tuple[bool, str]:
        """Check SPIRE server health."""
        rc, stdout, stderr = self.kubectl.exec_in_pod(
            self.server_pod,
            ["/opt/spire/bin/spire-server", "healthcheck"],
            container="spire-server",
        )
        return rc == 0, stdout.strip() or stderr.strip()

    def agent_healthcheck(self, agent_pod: str) -> Tuple[bool, str]:
        """Check SPIRE agent health."""
        rc, stdout, stderr = self.kubectl.exec_in_pod(
            agent_pod,
            ["/opt/spire/bin/spire-agent", "healthcheck"],
            container="spire-agent",
        )
        return rc == 0, stdout.strip() or stderr.strip()

    def fetch_workload_svid(self, pod_name: str) -> Optional[str]:
        """Fetch X.509 SVID from the Workload API for a pod."""
        rc, stdout, stderr = self.kubectl.exec_in_pod(
            pod_name,
            ["/opt/spire/bin/spire-agent", "api", "fetch",
             "-socketPath", self.agent_socket],
        )
        if rc == 0 and stdout.strip():
            return stdout.strip()
        return None

    def list_entries(self) -> Optional[str]:
        """List all registration entries from SPIRE server."""
        rc, stdout, stderr = self.kubectl.exec_in_pod(
            self.server_pod,
            ["/opt/spire/bin/spire-server", "entry", "list"],
            container="spire-server",
        )
        if rc == 0:
            return stdout.strip()
        return None

    def show_entry(self, spiffe_id: str) -> Optional[str]:
        """Show a specific registration entry by SPIFFE ID."""
        rc, stdout, stderr = self.kubectl.exec_in_pod(
            self.server_pod,
            ["/opt/spire/bin/spire-server", "entry", "show",
             "-spiffeID", spiffe_id],
            container="spire-server",
        )
        if rc == 0:
            return stdout.strip()
        return None

    def federation_list(self) -> Optional[str]:
        """List federated trust domains."""
        rc, stdout, stderr = self.kubectl.exec_in_pod(
            self.server_pod,
            ["/opt/spire/bin/spire-server", "federation", "list"],
            container="spire-server",
        )
        if rc == 0:
            return stdout.strip()
        return None


# ---------------------------------------------------------------------------
# Certificate Parsing Utilities
# ---------------------------------------------------------------------------
class CertificateParser:
    """Parse X.509 SVID certificates for mTLS verification."""

    @staticmethod
    def parse_openssl_output(cert_text: str) -> Dict[str, Any]:
        """Parse the output of `openssl x509 -noout -text` into a dict."""
        result: Dict[str, Any] = {
            "spiffe_id": None,
            "serial_number": None,
            "not_before": None,
            "not_after": None,
            "ttl_seconds": None,
            "dns_sans": [],
            "key_usage": [],
            "extended_key_usage": [],
            "is_expired": True,
            "is_about_to_expire": True,
        }

        if not cert_text:
            return result

        # Extract SPIFFE ID from URI SANs
        uri_match = re.search(
            r"URI:\s*(spiffe://[^\s,]+)", cert_text
        )
        if uri_match:
            result["spiffe_id"] = uri_match.group(1)

        # Extract serial number
        serial_match = re.search(
            r"Serial Number:\s*([a-fA-F0-9:]+)", cert_text
        )
        if serial_match:
            result["serial_number"] = serial_match.group(1).replace(":", "")

        # Extract validity dates
        not_before_match = re.search(
            r"Not Before\s*:\s*(.+)", cert_text
        )
        not_after_match = re.search(
            r"Not After\s*:\s*(.+)", cert_text
        )
        if not_before_match and not_after_match:
            result["not_before"] = not_before_match.group(1).strip()
            result["not_after"] = not_after_match.group(1).strip()

            try:
                before = datetime.strptime(
                    result["not_before"], "%b %d %H:%M:%S %Y %Z"
                ).replace(tzinfo=timezone.utc)
                after = datetime.strptime(
                    result["not_after"], "%b %d %H:%M:%S %Y %Z"
                ).replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)

                ttl = (after - now).total_seconds()
                result["ttl_seconds"] = max(0, ttl)
                result["is_expired"] = now > after
                result["is_about_to_expire"] = ttl < GRACE_PERIOD_SECONDS

                total_cert_ttl = (after - before).total_seconds()
                result["cert_ttl_seconds"] = total_cert_ttl
            except (ValueError, TypeError):
                pass

        # Extract DNS SANs
        dns_matches = re.findall(r"DNS:([^\s,]+)", cert_text)
        result["dns_sans"] = dns_matches

        # Extract Key Usage
        key_usage_match = re.search(
            r"Key Usage[\s\S]*?((?:\s+\w[\w\s-]*,?)+)", cert_text
        )
        if key_usage_match:
            usage_text = key_usage_match.group(1)
            result["key_usage"] = [
                u.strip().rstrip(",")
                for u in usage_text.split("\n")
                if u.strip() and not u.strip().startswith("Key")
            ]

        # Extract Extended Key Usage
        ext_key_usage_match = re.search(
            r"Extended Key Usage[\s\S]*?((?:\s+\w[\w\s-]*,?)+)", cert_text
        )
        if ext_key_usage_match:
            usage_text = ext_key_usage_match.group(1)
            result["extended_key_usage"] = [
                u.strip().rstrip(",")
                for u in usage_text.split("\n")
                if u.strip() and not u.strip().startswith("Extended")
            ]

        return result

    @staticmethod
    def validate_spiffe_id(spiffe_id: str, service_name: str) -> Dict[str, Any]:
        """Validate a SPIFFE ID matches the expected format for a service."""
        expected = SERVICE_REGISTRY.get(service_name, {}).get("spiffe_id", "")
        result = {
            "spiffe_id": spiffe_id,
            "expected": expected,
            "matches": spiffe_id == expected,
            "format_valid": False,
            "trust_domain_correct": False,
            "namespace_correct": False,
            "service_account_correct": False,
        }

        # Validate SPIFFE ID format: spiffe://<trust-domain>/ns/<namespace>/sa/<sa>
        pattern = r"^spiffe://([^/]+)/ns/([^/]+)/sa/([^/]+)$"
        match = re.match(pattern, spiffe_id)
        if match:
            result["format_valid"] = True
            result["trust_domain_correct"] = match.group(1) == TRUST_DOMAIN
            result["namespace_correct"] = match.group(2) == NAMESPACE
            expected_sa = SERVICE_REGISTRY.get(service_name, {}).get(
                "service_account", ""
            )
            result["service_account_correct"] = match.group(3) == expected_sa

        return result

    @staticmethod
    def validate_dns_sans(
        dns_sans: List[str], service_name: str
    ) -> Dict[str, Any]:
        """Validate DNS SANs match the expected service FQDN."""
        expected = SERVICE_REGISTRY.get(service_name, {}).get("dns_names", [])
        fqdn = f"{service_name}.{NAMESPACE}.svc.cluster.local"

        return {
            "dns_sans": dns_sans,
            "expected": expected,
            "has_fqdn": fqdn in dns_sans,
            "all_expected_present": all(d in dns_sans for d in expected),
        }


# ---------------------------------------------------------------------------
# Pytest Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def kubectl() -> KubectlHelper:
    """Provide a kubectl helper for the test session."""
    return KubectlHelper(namespace=NAMESPACE)


@pytest.fixture(scope="session")
def spire_client(kubectl: KubectlHelper) -> SpireApiClient:
    """Provide a SPIRE API client for the test session."""
    return SpireApiClient(kubectl=kubectl)


@pytest.fixture(scope="session")
def cert_parser() -> CertificateParser:
    """Provide a certificate parser for the test session."""
    return CertificateParser()


@pytest.fixture(scope="session")
def service_registry() -> Dict[str, Dict[str, Any]]:
    """Provide the service registry for the test session."""
    return SERVICE_REGISTRY


@pytest.fixture(scope="session")
def handshake_pairs() -> List[Tuple[str, str, str]]:
    """Provide the mTLS handshake pair definitions."""
    return HANDSHAKE_PAIRS


@pytest.fixture(scope="session")
def all_services() -> List[str]:
    """Provide the list of all service names."""
    return ALL_SERVICES


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Provide the project root path."""
    return Path(__file__).parent.parent.parent


@pytest.fixture(scope="session")
def infra_k8s_base(project_root: Path) -> Path:
    """Provide the path to infra/kubernetes/base."""
    return project_root / "infra" / "kubernetes" / "base"


@pytest.fixture(scope="session")
def infra_k8s_platform(project_root: Path) -> Path:
    """Provide the path to infra/kubernetes/platform."""
    return project_root / "infra" / "kubernetes" / "platform"


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "mtls: marks tests as mTLS verification tests"
    )
    config.addinivalue_line(
        "markers", "spire: marks tests as SPIRE infrastructure tests"
    )
    config.addinivalue_line(
        "markers", "spiffe: marks tests as SPIFFE identity verification tests"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (require cluster)"
    )
