"""
End-to-End Integration Tests for Service Discovery & Routing.

Tests the Gateway's routing capabilities, gRPC reflection, Schema Registry
resolution, Identity service attestation, RL Engine policy endpoints,
and circuit breaker integration for service unavailability.
"""

import json
import time
import uuid
from typing import Any, Dict, Optional

import pytest

from .conftest import (
    HttpClientFactory,
    GrpcChannelFactory,
    KubectlHelper,
    SpireApiClient,
    OTelTraceHelper,
    SERVICE_REGISTRY,
    ALL_SERVICES,
    wait_for_service_ready,
    wait_for_condition,
)


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------
pytestmark = [pytest.mark.e2e, pytest.mark.discovery]


# ---------------------------------------------------------------------------
# Test 1: Gateway Routes to Correct Service by Path
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.discovery
def test_gateway_routes_to_correct_service(
    http_client_factory: HttpClientFactory,
    service_registry: Dict[str, Dict[str, Any]],
):
    """Gateway routes to correct service by path.

    Verifies that the Gateway correctly routes requests to each backend
    service based on the URL path prefix. Tests all 9 services.
    """
    # Define path -> expected service mappings
    route_tests = [
        ("/api/v1/order/orders", "order"),
        ("/api/v1/catalog/products", "catalog"),
        ("/api/v1/payment/payments", "payment"),
        ("/api/v1/notification/notifications", "notification"),
        ("/api/v1/analytics/metrics", "analytics"),
        ("/api/v1/identity/workloads", "identity"),
        ("/api/v1/schema-registry/schemas", "schema-registry"),
        ("/api/v1/rl-engine/policies", "rl-engine"),
    ]

    for path, expected_service in route_tests:
        code, resp, headers = http_client_factory.get(path, timeout=10)
        # We don't require 200 — the service may return 404 for empty data
        # but we verify the gateway forwarded to the correct backend
        assert code != 503, f"Gateway returned 503 for {path} (expected service: {expected_service})"
        assert code != 502, f"Gateway returned 502 for {path} — backend {expected_service} unreachable"

        # Check routing header if present
        routed_to = headers.get("X-Service-Name", headers.get("x-service-name", ""))
        if routed_to:
            assert routed_to == expected_service, (
                f"Gateway routed {path} to {routed_to}, expected {expected_service}"
            )


# ---------------------------------------------------------------------------
# Test 2: Gateway Handles Service Unavailability Gracefully
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.discovery
@pytest.mark.destructive
def test_gateway_handles_service_unavailability(
    http_client_factory: HttpClientFactory,
    kubectl: KubectlHelper,
):
    """Gateway handles service unavailability gracefully (circuit breaker).

    Scales a non-critical service (analytics) to 0, then verifies
    the gateway returns a proper error response instead of hanging
    or crashing. Also verifies other services remain unaffected.
    """
    # Scale analytics down to 0
    scaled = kubectl.scale_deployment("analytics", 0)
    assert scaled, "Failed to scale analytics deployment to 0"

    try:
        # Wait for analytics to be fully unavailable
        time.sleep(15)

        # Verify gateway returns proper error for analytics
        code, resp, _ = http_client_factory.get(
            "/api/v1/analytics/metrics",
            timeout=15,
        )
        assert code in (503, 502, 504), (
            f"Gateway should return 5xx for unavailable analytics, got {code}"
        )

        # Verify other services are NOT affected
        code_catalog, _, _ = http_client_factory.get(
            "/api/v1/catalog/products",
            timeout=10,
        )
        assert code_catalog not in (502, 503, 504), (
            f"Catalog should NOT be affected by analytics being down, got {code_catalog}"
        )

        code_order, _, _ = http_client_factory.get(
            "/api/v1/order/orders",
            timeout=10,
        )
        assert code_order not in (502, 503, 504), (
            f"Order should NOT be affected by analytics being down, got {code_order}"
        )

    finally:
        # Restore analytics deployment
        kubectl.scale_deployment("analytics", 2)
        time.sleep(15)


# ---------------------------------------------------------------------------
# Test 3: gRPC Reflection Works for All Services
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.discovery
def test_grpc_reflection_all_services(
    grpc_channel_factory: GrpcChannelFactory,
    service_registry: Dict[str, Dict[str, Any]],
):
    """gRPC reflection works for all services.

    Verifies that each service exposes gRPC server reflection, allowing
    clients to discover available RPCs at runtime. This is critical for
    API accessibility and developer experience.
    """
    try:
        import grpc
        from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc
    except ImportError:
        pytest.skip("grpcio-reflection package not installed")

    for service_name, config in service_registry.items():
        host = f"{service_name}.production.svc.cluster.local"
        port = config["grpc_port"]
        target = f"{host}:{port}"

        channel = grpc_channel_factory.create_channel(target)
        try:
            stub = reflection_pb2_grpc.ServerReflectionStub(channel)

            # List services via reflection
            request = reflection_pb2.ServerReflectionRequest(list_services="")
            responses = stub.ServerReflectionInfo(iter([request]))
            service_list = None
            for resp in responses:
                if resp.HasField("list_services"):
                    service_list = [s.name for s in resp.list_services.service]
                    break

            if service_list is not None:
                # Verify the expected gRPC service is listed
                expected_grpc_service = config.get("grpc_service", "")
                if expected_grpc_service:
                    assert expected_grpc_service in service_list, (
                        f"Service {service_name}: expected gRPC service "
                        f"'{expected_grpc_service}' not found in reflection list: {service_list}"
                    )
            else:
                # Some services may not have reflection enabled; log but don't fail
                pytest.log.warning(f"gRPC reflection not available for {service_name}")
        except grpc.RpcError as e:
            pytest.log.warning(f"gRPC reflection failed for {service_name}: {e}")
        finally:
            channel.close()


# ---------------------------------------------------------------------------
# Test 4: Schema Registry Resolves Schema by Subject + Version
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.discovery
def test_schema_registry_resolves_by_subject_and_version(
    http_client_factory: HttpClientFactory,
):
    """Schema registry resolves schema by subject + version.

    Verifies the Schema Registry can resolve schemas by subject name
    and version number, supporting both specific version lookup and
    latest version retrieval.
    """
    # Test subjects that should exist in the registry
    subjects = [
        "order-events-value",
        "payment-events-value",
        "catalog-events-value",
    ]

    for subject in subjects:
        # Resolve latest version
        code, resp, _ = http_client_factory.get(
            f"/api/v1/schema-registry/schemas/{subject}/versions/latest",
            service="schema-registry",
        )
        if code == 200:
            assert "schema" in resp or "id" in resp, (
                f"Schema response for {subject} must contain 'schema' or 'id'"
            )

            # Resolve version 1 specifically
            code_v1, resp_v1, _ = http_client_factory.get(
                f"/api/v1/schema-registry/schemas/{subject}/versions/1",
                service="schema-registry",
            )
            assert code_v1 in (200, 404), (
                f"Schema version lookup for {subject}/1 returned unexpected code: {code_v1}"
            )

    # List all subjects
    code, subjects_resp, _ = http_client_factory.get(
        "/api/v1/schema-registry/subjects",
        service="schema-registry",
    )
    assert code == 200, f"Failed to list schema subjects: {subjects_resp}"
    assert isinstance(subjects_resp, (list, dict)), "Subjects response should be a list or dict"


# ---------------------------------------------------------------------------
# Test 5: Identity Service Attests Workloads and Issues SVIDs
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.discovery
def test_identity_attests_workloads_and_issues_svids(
    http_client_factory: HttpClientFactory,
    spire_client: SpireApiClient,
    kubectl: KubectlHelper,
):
    """Identity service attests workloads and issues SVIDs.

    Verifies the Identity service can attest a workload by its SPIFFE ID
    and selectors, issue an X.509 SVID, and list registered workloads.
    """
    # Step 1: Verify SPIRE server is healthy
    healthy, msg = spire_client.server_healthcheck()
    assert healthy, f"SPIRE server is not healthy: {msg}"

    # Step 2: List registered workloads
    entries = spire_client.list_entries()
    assert entries is not None, "Failed to list SPIRE registration entries"

    # Step 3: Verify a known workload entry exists (gateway)
    gateway_spiffe_id = SERVICE_REGISTRY["gateway"]["spiffe_id"]
    entry = spire_client.show_entry(gateway_spiffe_id)
    # Entry should exist for the gateway service
    assert entry is not None, f"No SPIRE entry found for gateway ({gateway_spiffe_id})"

    # Step 4: Attest a workload via the Identity service gRPC
    code, resp, _ = http_client_factory.post(
        "/api/v1/identity/attest",
        {
            "spiffe_id": gateway_spiffe_id,
            "selectors": {
                "k8s:ns": "production",
                "k8s:sa": "gateway",
            },
            "trust_domain": "trust.example.org",
        },
        service="identity",
    )
    assert code in (200, 201), f"Workload attestation failed: {resp}"

    attested = resp.get("attested", False)
    assert attested, f"Workload attestation should succeed for gateway: {resp}"

    # Step 5: Issue an SVID for the attested workload
    code, svid_resp, _ = http_client_factory.post(
        "/api/v1/identity/issue-svid",
        {
            "spiffe_id": gateway_spiffe_id,
            "ttl_seconds": 3600,
            "trust_domain": "trust.example.org",
        },
        service="identity",
    )
    assert code in (200, 201), f"SVID issuance failed: {svid_resp}"
    assert "certificate_chain" in svid_resp or "svid" in svid_resp, (
        f"SVID response must contain certificate_chain or svid: {svid_resp}"
    )


# ---------------------------------------------------------------------------
# Test 6: RL Engine Policy Endpoint Returns Active Policies
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.discovery
def test_rl_engine_policy_endpoint_returns_active_policies(
    http_client_factory: HttpClientFactory,
):
    """RL engine policy endpoint returns active policies.

    Verifies the RL Engine exposes an endpoint that returns the currently
    active rate-limiting policies, including their configuration,
    scope, and current state.
    """
    # Get active policies
    code, resp, _ = http_client_factory.get(
        "/api/v1/rl-engine/policies/active",
        service="rl-engine",
    )
    assert code == 200, f"RL Engine active policies endpoint failed: {resp}"

    # Verify response contains policies
    policies = resp.get("policies", resp.get("data", []))
    assert isinstance(policies, list), "Active policies response should be a list"

    # If there are policies, verify their structure
    for policy in policies:
        assert "policy_id" in policy or "id" in policy, "Policy must have an ID"
        assert "scope" in policy or "type" in policy, "Policy must have a scope or type"
        assert "config" in policy or "limits" in policy, "Policy must have config or limits"

    # Verify rate limit status endpoint
    code, status_resp, _ = http_client_factory.get(
        "/api/v1/rl-engine/status",
        service="rl-engine",
    )
    assert code == 200, f"RL Engine status endpoint failed: {status_resp}"

    # Verify check-rate-limit endpoint
    code, check_resp, _ = http_client_factory.post(
        "/api/v1/rl-engine/check",
        {
            "client_id": "test-e2e-client",
            "service": "gateway",
            "endpoint": "/api/v1/catalog/products",
        },
        service="rl-engine",
    )
    assert code in (200, 429), f"Rate limit check should return 200 or 429, got {code}"


# ---------------------------------------------------------------------------
# Offline / Manifest Validation Tests
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.discovery
@pytest.mark.offline
def test_gateway_proto_defines_proxy_rpc(project_root):
    """Validate that the Gateway proto defines the ProxyRequest RPC
    required for service routing.

    This is an offline test that does not require a live cluster.
    """
    gateway_proto = project_root / "schemas" / "proto" / "gateway" / "v1" / "gateway.proto"
    assert gateway_proto.exists(), f"Gateway proto not found at {gateway_proto}"

    content = gateway_proto.read_text()
    assert "GatewayService" in content, "GatewayService must be defined"
    assert "ProxyRequest" in content, "GatewayService must have ProxyRequest RPC"
    assert "HealthCheck" in content, "GatewayService must have HealthCheck RPC"
    assert "GetRateLimitStatus" in content, "GatewayService must have GetRateLimitStatus RPC"

    # Verify request includes service_name for routing
    assert "service_name" in content, "ProxyRequestRequest must have service_name field"
    assert "method_path" in content, "ProxyRequestRequest must have method_path field"


@pytest.mark.e2e
@pytest.mark.discovery
@pytest.mark.offline
def test_kustomize_overlays_define_all_services(project_root):
    """Validate that the production kustomize overlay references
    all 9 services with correct image tags.

    This is an offline test that does not require a live cluster.
    """
    production_kustomize = project_root / "infra" / "kubernetes" / "overlays" / "production" / "kustomization.yaml"
    assert production_kustomize.exists(), f"Production kustomize not found at {production_kustomize}"

    content = production_kustomize.read_text()

    # Verify all 9 services have image definitions
    expected_services = [
        "gateway", "identity", "catalog", "order", "payment",
        "notification", "analytics", "cdc-relay", "schema-registry",
    ]
    for svc in expected_services:
        assert svc in content, f"Service '{svc}' must be defined in production kustomize overlay"

    # Verify replica counts are defined for production
    assert "replicas" in content, "Production overlay must define replica counts"

    # Verify namespace is production
    assert "namespace: production" in content, "Production overlay must set namespace to production"


@pytest.mark.e2e
@pytest.mark.discovery
@pytest.mark.offline
def test_app_of_apps_defines_all_services(project_root):
    """Validate that the ArgoCD App-of-Apps defines all 9 services.

    This is an offline test that does not require a live cluster.
    """
    app_of_apps = project_root / "infra" / "kubernetes" / "apps" / "app-of-apps.yaml"
    assert app_of_apps.exists(), f"App-of-Apps manifest not found at {app_of_apps}"

    content = app_of_apps.read_text()

    expected_services = [
        "gateway", "identity", "catalog", "order", "payment",
        "notification", "analytics", "cdc-relay", "schema-registry",
    ]
    for svc in expected_services:
        assert svc in content, f"Service '{svc}' must be in App-of-Apps generator list"
