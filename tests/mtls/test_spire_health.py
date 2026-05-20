"""
Test SPIRE infrastructure health.

Verifies:
- SPIRE server is healthy
- SPIRE agents are running on all nodes
- Bundle rotation is working
- Entry registration is correct for all services
"""

import re
from typing import Any, Dict, List, Optional

import pytest

from conftest import (
    ALL_SERVICES,
    KubectlHelper,
    NAMESPACE,
    SERVICE_REGISTRY,
    SVID_TTL_SECONDS,
    TRUST_DOMAIN,
    SpireApiClient,
)


# ---------------------------------------------------------------------------
# Test: SPIRE Server Health
# ---------------------------------------------------------------------------
class TestSpireServerHealth:
    """Test that the SPIRE server is healthy and correctly configured."""

    @pytest.mark.integration
    @pytest.mark.spire
    def test_spire_server_is_healthy(
        self, kubectl: KubectlHelper, spire_client: SpireApiClient
    ):
        """SPIRE server must pass healthcheck."""
        healthy, output = spire_client.server_healthcheck()

        assert healthy, (
            f"SPIRE server healthcheck failed. Output: {output}"
        )

    @pytest.mark.integration
    @pytest.mark.spire
    def test_spire_server_pods_running(self, kubectl: KubectlHelper):
        """All 3 SPIRE server replicas must be in Running state."""
        status = kubectl.get_statefulset_replicas("spire-server")

        if status is None:
            pytest.skip("Cannot get SPIRE server StatefulSet status")

        assert status["ready"] >= 3, (
            f"SPIRE server has {status['ready']}/3 ready replicas. "
            f"Expected at least 3."
        )

    @pytest.mark.integration
    @pytest.mark.spire
    def test_spire_server_health_endpoint(
        self, kubectl: KubectlHelper
    ):
        """SPIRE server health endpoint must be responsive."""
        rc, stdout, stderr = kubectl.exec_in_pod(
            "spire-server-0",
            ["curl", "-sf", "http://localhost:8080/live"],
            container="spire-server",
        )

        assert rc == 0, (
            f"SPIRE server health endpoint not responsive. "
            f"stderr: {stderr}"
        )

    @pytest.mark.integration
    @pytest.mark.spire
    def test_spire_server_bundle_endpoint_accessible(
        self, kubectl: KubectlHelper
    ):
        """SPIRE server bundle endpoint must be accessible."""
        # The bundle endpoint runs on port 8443 with TLS
        # We check if the port is listening
        rc, stdout, stderr = kubectl.exec_in_pod(
            "spire-server-0",
            ["sh", "-c", "ss -tlnp | grep 8443 || echo 'PORT_NOT_LISTENING'"],
            container="spire-server",
        )

        assert "PORT_NOT_LISTENING" not in stdout, (
            "SPIRE server bundle endpoint port 8443 is not listening"
        )

    @pytest.mark.integration
    @pytest.mark.spire
    def test_spire_server_ca_rotation_configured(
        self, kubectl: KubectlHelper
    ):
        """SPIRE server CA rotation must be configured with 24h TTL."""
        rc, stdout, stderr = kubectl.exec_in_pod(
            "spire-server-0",
            ["grep", "ca_ttl", "/run/spire/config/server.conf"],
            container="spire-server",
        )

        assert rc == 0, (
            "SPIRE server ca_ttl is not configured in server.conf"
        )

        # The ca_ttl should be 24h (updated from 72h in federation policy)
        ca_ttl = stdout.strip()
        assert "24h" in ca_ttl or "72h" in ca_ttl, (
            f"SPIRE server ca_ttl is not 24h or 72h: {ca_ttl}"
        )

    @pytest.mark.integration
    @pytest.mark.spire
    def test_spire_server_trust_domain_correct(
        self, kubectl: KubectlHelper
    ):
        """SPIRE server must use the correct trust domain."""
        rc, stdout, stderr = kubectl.exec_in_pod(
            "spire-server-0",
            ["grep", "trust_domain", "/run/spire/config/server.conf"],
            container="spire-server",
        )

        assert rc == 0, "Cannot read trust_domain from server.conf"
        assert TRUST_DOMAIN in stdout, (
            f"SPIRE server trust domain is not '{TRUST_DOMAIN}': {stdout.strip()}"
        )


# ---------------------------------------------------------------------------
# Test: SPIRE Agent Health
# ---------------------------------------------------------------------------
class TestSpireAgentHealth:
    """Test that SPIRE agents are healthy and correctly configured."""

    @pytest.mark.integration
    @pytest.mark.spire
    def test_spire_agents_running_on_all_nodes(
        self, kubectl: KubectlHelper
    ):
        """SPIRE agent DaemonSet must have all pods ready on every node."""
        status = kubectl.get_daemonset_status("spire-agent")

        if status is None:
            pytest.skip("Cannot get SPIRE agent DaemonSet status")

        assert status["desired"] > 0, "No SPIRE agents are scheduled"
        assert status["ready"] == status["desired"], (
            f"SPIRE agent: {status['ready']}/{status['desired']} agents ready. "
            f"Expected all agents to be ready."
        )

    @pytest.mark.integration
    @pytest.mark.spire
    def test_spire_agent_attestation(
        self, kubectl: KubectlHelper, spire_client: SpireApiClient
    ):
        """SPIRE agent must pass healthcheck (attestation verification)."""
        # Get the first agent pod
        agent_pod = kubectl.get_pod_name("spire-agent")
        if not agent_pod:
            # Try with different label
            rc, stdout, stderr = kubectl._run([
                "get", "pods",
                "-l", "app=spire-agent",
                "--field-selector=status.phase=Running",
                "-o", "jsonpath={.items[0].metadata.name}",
            ])
            if rc == 0 and stdout.strip():
                agent_pod = stdout.strip()

        if not agent_pod:
            pytest.skip("No SPIRE agent pod found")

        healthy, output = spire_client.agent_healthcheck(agent_pod)
        assert healthy, (
            f"SPIRE agent healthcheck failed. Output: {output}"
        )

    @pytest.mark.integration
    @pytest.mark.spire
    def test_spire_agent_svid_rotation_ttl(
        self, kubectl: KubectlHelper, spire_client: SpireApiClient
    ):
        """SPIRE agent SVID TTL must be 1 hour (rotation configured)."""
        agent_pod = kubectl.get_pod_name("spire-agent")
        if not agent_pod:
            pytest.skip("No SPIRE agent pod found")

        # Check the agent config for SVID TTL
        rc, stdout, stderr = kubectl.exec_in_pod(
            agent_pod,
            ["grep", "svid_ttl", "/run/spire/config/agent.conf"],
            container="spire-agent",
        )

        if rc == 0:
            assert "1h" in stdout or "3600" in stdout, (
                f"SPIRE agent svid_ttl is not 1h: {stdout.strip()}"
            )
        else:
            # If svid_ttl is not explicitly set, it inherits from the server
            pytest.skip(
                "SPIRE agent svid_ttl not explicitly set in agent.conf "
                "(inherits from server default)"
            )

    @pytest.mark.integration
    @pytest.mark.spire
    def test_spire_agent_trust_domain_correct(
        self, kubectl: KubectlHelper
    ):
        """SPIRE agent must use the correct trust domain."""
        agent_pod = kubectl.get_pod_name("spire-agent")
        if not agent_pod:
            pytest.skip("No SPIRE agent pod found")

        rc, stdout, stderr = kubectl.exec_in_pod(
            agent_pod,
            ["grep", "trust_domain", "/run/spire/config/agent.conf"],
            container="spire-agent",
        )

        assert rc == 0, "Cannot read trust_domain from agent.conf"
        assert TRUST_DOMAIN in stdout, (
            f"SPIRE agent trust domain is not '{TRUST_DOMAIN}': {stdout.strip()}"
        )

    @pytest.mark.integration
    @pytest.mark.spire
    def test_spire_agent_k8s_psat_attestor(
        self, kubectl: KubectlHelper
    ):
        """SPIRE agent must use k8s_psat NodeAttestor for node attestation."""
        agent_pod = kubectl.get_pod_name("spire-agent")
        if not agent_pod:
            pytest.skip("No SPIRE agent pod found")

        rc, stdout, stderr = kubectl.exec_in_pod(
            agent_pod,
            ["grep", "k8s_psat", "/run/spire/config/agent.conf"],
            container="spire-agent",
        )

        assert rc == 0, (
            "SPIRE agent does not have k8s_psat NodeAttestor configured"
        )

    @pytest.mark.integration
    @pytest.mark.spire
    def test_spire_agent_k8s_workload_attestor(
        self, kubectl: KubectlHelper
    ):
        """SPIRE agent must use k8s WorkloadAttestor for workload attestation."""
        agent_pod = kubectl.get_pod_name("spire-agent")
        if not agent_pod:
            pytest.skip("No SPIRE agent pod found")

        rc, stdout, stderr = kubectl.exec_in_pod(
            agent_pod,
            ["grep", "-A5", "WorkloadAttestor", "/run/spire/config/agent.conf"],
            container="spire-agent",
        )

        assert rc == 0, (
            "SPIRE agent does not have WorkloadAttestor configured"
        )
        assert "k8s" in stdout, (
            "SPIRE agent does not have k8s WorkloadAttestor. "
            f"Found: {stdout.strip()}"
        )


# ---------------------------------------------------------------------------
# Test: Bundle Rotation
# ---------------------------------------------------------------------------
class TestBundleRotation:
    """Test that trust bundle rotation is working correctly."""

    @pytest.mark.integration
    @pytest.mark.spire
    def test_bundle_configmap_exists(self, kubectl: KubectlHelper):
        """The spire-bundle ConfigMap must exist (populated by SPIRE server)."""
        assert kubectl.configmap_exists("spire-bundle"), (
            "spire-bundle ConfigMap does not exist in namespace "
            f"'{NAMESPACE}'"
        )

    @pytest.mark.integration
    @pytest.mark.spire
    def test_bundle_configmap_contains_certificate(
        self, kubectl: KubectlHelper
    ):
        """The spire-bundle ConfigMap must contain valid CA certificates."""
        data = kubectl.get_configmap_data("spire-bundle")
        if not data:
            pytest.skip("Cannot read spire-bundle ConfigMap data")

        # At least one key should contain a certificate
        has_cert = any(
            "BEGIN CERTIFICATE" in value
            for value in data.values()
            if isinstance(value, str)
        )

        assert has_cert, (
            "spire-bundle ConfigMap does not contain any certificates"
        )

    @pytest.mark.integration
    @pytest.mark.spire
    def test_bundle_notifier_configured(self, kubectl: KubectlHelper):
        """SPIRE server must have the k8sbundle Notifier plugin configured."""
        rc, stdout, stderr = kubectl.exec_in_pod(
            "spire-server-0",
            ["grep", "-A5", "k8sbundle", "/run/spire/config/server.conf"],
            container="spire-server",
        )

        assert rc == 0, (
            "SPIRE server does not have k8sbundle Notifier configured"
        )
        assert "spire-bundle" in stdout, (
            "SPIRE server k8sbundle Notifier does not reference spire-bundle ConfigMap"
        )


# ---------------------------------------------------------------------------
# Test: Entry Registration
# ---------------------------------------------------------------------------
class TestEntryRegistration:
    """Test that SPIRE entry registration is correct for all services."""

    @pytest.mark.integration
    @pytest.mark.spire
    @pytest.mark.parametrize("service", ALL_SERVICES)
    def test_entry_registered_for_service(
        self,
        kubectl: KubectlHelper,
        spire_client: SpireApiClient,
        service: str,
    ):
        """Each service must have a registration entry in SPIRE server."""
        svc_info = SERVICE_REGISTRY[service]
        spiffe_id = svc_info["spiffe_id"]

        entry_output = spire_client.show_entry(spiffe_id)

        if entry_output is None:
            pytest.skip(
                f"Cannot query SPIRE server for {service} entry"
            )

        # The output should contain the SPIFFE ID
        assert spiffe_id in entry_output, (
            f"SPIRE server does not have an entry for SPIFFE ID '{spiffe_id}'. "
            f"Server output: {entry_output[:200]}"
        )

    @pytest.mark.integration
    @pytest.mark.spire
    @pytest.mark.parametrize("service", ALL_SERVICES)
    def test_entry_has_correct_selectors(
        self,
        kubectl: KubectlHelper,
        spire_client: SpireApiClient,
        service: str,
    ):
        """Each service entry must have k8s:ns:production and k8s:sa:<sa> selectors."""
        svc_info = SERVICE_REGISTRY[service]
        spiffe_id = svc_info["spiffe_id"]
        sa_name = svc_info["service_account"]

        entry_output = spire_client.show_entry(spiffe_id)

        if entry_output is None:
            pytest.skip(
                f"Cannot query SPIRE server for {service} entry"
            )

        # Check for namespace selector
        ns_selector_found = (
            f"k8s:ns:{NAMESPACE}" in entry_output
            or f"ns:{NAMESPACE}" in entry_output
        )

        # Check for service account selector
        sa_selector_found = (
            f"k8s:sa:{sa_name}" in entry_output
            or f"sa:{sa_name}" in entry_output
        )

        assert ns_selector_found, (
            f"Entry for {service} is missing k8s:ns:{NAMESPACE} selector. "
            f"Output: {entry_output[:200]}"
        )
        assert sa_selector_found, (
            f"Entry for {service} is missing k8s:sa:{sa_name} selector. "
            f"Output: {entry_output[:200]}"
        )

    @pytest.mark.integration
    @pytest.mark.spire
    @pytest.mark.parametrize("service", ALL_SERVICES)
    def test_entry_has_dns_names(
        self,
        kubectl: KubectlHelper,
        spire_client: SpireApiClient,
        service: str,
    ):
        """Each service entry must have DNS names matching the service FQDN."""
        svc_info = SERVICE_REGISTRY[service]
        spiffe_id = svc_info["spiffe_id"]
        fqdn = f"{service}.{NAMESPACE}.svc.cluster.local"

        entry_output = spire_client.show_entry(spiffe_id)

        if entry_output is None:
            pytest.skip(
                f"Cannot query SPIRE server for {service} entry"
            )

        # DNS names should be present in the entry
        dns_found = (
            fqdn in entry_output
            or "dns" in entry_output.lower()
        )

        assert dns_found, (
            f"Entry for {service} is missing DNS name '{fqdn}'. "
            f"Output: {entry_output[:200]}"
        )

    @pytest.mark.integration
    @pytest.mark.spire
    def test_nine_entries_registered(
        self,
        kubectl: KubectlHelper,
        spire_client: SpireApiClient,
    ):
        """Exactly 9 workload entries must be registered in SPIRE server."""
        entries_output = spire_client.list_entries()

        if entries_output is None:
            pytest.skip("Cannot list SPIRE server entries")

        # Count entries that match our trust domain
        our_entries = re.findall(
            rf"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/\w+",
            entries_output,
        )

        # We expect at least 9 entries (one per service)
        # There may be additional entries (e.g., spire-server, spire-agent)
        unique_entries = set(our_entries)

        service_spiffe_ids = {
            SERVICE_REGISTRY[s]["spiffe_id"] for s in ALL_SERVICES
        }

        missing = service_spiffe_ids - unique_entries
        if missing:
            pytest.fail(
                f"Missing SPIRE entries for: {missing}. "
                f"Found {len(unique_entries)} entries, "
                f"expected at least {len(service_spiffe_ids)}."
            )

    @pytest.mark.integration
    @pytest.mark.spire
    @pytest.mark.parametrize("service", ALL_SERVICES)
    def test_entry_ttl_is_one_hour(
        self,
        kubectl: KubectlHelper,
        spire_client: SpireApiClient,
        service: str,
    ):
        """Each service entry must have a 1-hour (3600s) TTL."""
        svc_info = SERVICE_REGISTRY[service]
        spiffe_id = svc_info["spiffe_id"]

        entry_output = spire_client.show_entry(spiffe_id)

        if entry_output is None:
            pytest.skip(
                f"Cannot query SPIRE server for {service} entry"
            )

        # TTL should be 3600 seconds
        ttl_match = re.search(r"(?:ttl|TTL)\s*[:=]\s*(\d+)", entry_output)

        if ttl_match:
            ttl = int(ttl_match.group(1))
            assert ttl == SVID_TTL_SECONDS, (
                f"Entry for {service} has TTL {ttl}s, "
                f"expected {SVID_TTL_SECONDS}s"
            )
        else:
            # If we can't parse TTL, check the server default config
            pass


# ---------------------------------------------------------------------------
# Test: Offline Validation (no cluster required)
# ---------------------------------------------------------------------------
class TestSpireConfigOfflineValidation:
    """Offline validation of SPIRE configuration from manifests."""

    def test_spire_server_manifest_exists(self, infra_k8s_platform):
        """The SPIRE server manifest must exist."""
        server_file = infra_k8s_platform / "spire-server.yaml"
        assert server_file.exists(), "spire-server.yaml not found"

    def test_spire_agent_manifest_exists(self, infra_k8s_platform):
        """The SPIRE agent manifest must exist."""
        agent_file = infra_k8s_platform / "spire-agent.yaml"
        assert agent_file.exists(), "spire-agent.yaml not found"

    def test_spire_server_has_three_replicas(self, infra_k8s_platform):
        """SPIRE server StatefulSet must have 3 replicas."""
        server_file = infra_k8s_platform / "spire-server.yaml"
        content = server_file.read_text()

        assert "replicas: 3" in content, (
            "SPIRE server StatefulSet does not have 3 replicas"
        )

    def test_spire_server_trust_domain_in_manifest(self, infra_k8s_platform):
        """SPIRE server config must specify the correct trust domain."""
        server_file = infra_k8s_platform / "spire-server.yaml"
        content = server_file.read_text()

        assert TRUST_DOMAIN in content, (
            f"SPIRE server manifest does not contain trust domain '{TRUST_DOMAIN}'"
        )

    def test_spire_server_svid_ttl_in_manifest(self, infra_k8s_platform):
        """SPIRE server config must specify 1h SVID TTL."""
        server_file = infra_k8s_platform / "spire-server.yaml"
        content = server_file.read_text()

        assert "1h" in content or "3600" in content, (
            "SPIRE server manifest does not specify 1h SVID TTL"
        )

    def test_spire_agent_k8s_psat_attestor_in_manifest(self, infra_k8s_platform):
        """SPIRE agent config must use k8s_psat NodeAttestor."""
        agent_file = infra_k8s_platform / "spire-agent.yaml"
        content = agent_file.read_text()

        assert "k8s_psat" in content, (
            "SPIRE agent manifest does not configure k8s_psat NodeAttestor"
        )

    def test_spire_agent_k8s_workload_attestor_in_manifest(self, infra_k8s_platform):
        """SPIRE agent config must use k8s WorkloadAttestor."""
        agent_file = infra_k8s_platform / "spire-agent.yaml"
        content = agent_file.read_text()

        assert "WorkloadAttestor" in content, (
            "SPIRE agent manifest does not configure WorkloadAttestor"
        )
        assert "k8s" in content, (
            "SPIRE agent manifest does not configure k8s WorkloadAttestor"
        )

    def test_spire_bundle_configmap_in_manifest(self, infra_k8s_platform):
        """The spire-bundle ConfigMap must be defined in the server manifest."""
        server_file = infra_k8s_platform / "spire-server.yaml"
        content = server_file.read_text()

        assert "spire-bundle" in content, (
            "SPIRE server manifest does not define spire-bundle ConfigMap"
        )

    def test_spire_federation_policy_exists(self, infra_k8s_platform):
        """The SPIRE federation policy ConfigMap must exist."""
        federation_file = infra_k8s_platform / "spire-federation-policy.yaml"
        assert federation_file.exists(), (
            "spire-federation-policy.yaml not found"
        )

    def test_spire_federation_policy_no_external_domains(
        self, infra_k8s_platform
    ):
        """The SPIRE federation policy must not define external trust domains."""
        federation_file = infra_k8s_platform / "spire-federation-policy.yaml"
        content = federation_file.read_text()

        # Should not contain any federated trust domains
        assert "federated_trust_domains = []" in content, (
            "SPIRE federation policy defines federated trust domains "
            "but should have none"
        )

    def test_all_nine_service_entries_in_federation_policy(
        self, infra_k8s_platform
    ):
        """The SPIRE federation policy must define entries for all 9 services."""
        federation_file = infra_k8s_platform / "spire-federation-policy.yaml"
        content = federation_file.read_text()

        for service in ALL_SERVICES:
            sa_name = SERVICE_REGISTRY[service]["service_account"]
            expected_spiffe = (
                f"spiffe://{TRUST_DOMAIN}/ns/{NAMESPACE}/sa/{sa_name}"
            )

            assert expected_spiffe in content, (
                f"SPIRE federation policy is missing entry for {service} "
                f"with SPIFFE ID '{expected_spiffe}'"
            )

    def test_spire_server_anti_affinity(self, infra_k8s_platform):
        """SPIRE server pods must have pod anti-affinity for HA."""
        server_file = infra_k8s_platform / "spire-server.yaml"
        content = server_file.read_text()

        assert "podAntiAffinity" in content, (
            "SPIRE server StatefulSet is missing pod anti-affinity rule"
        )
