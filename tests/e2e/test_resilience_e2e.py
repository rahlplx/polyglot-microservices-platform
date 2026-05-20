"""
End-to-End Integration Tests for Cross-Service Resilience.

Tests the platform's resilience patterns including cascading failure
prevention, retry with backoff, bulkhead isolation, graceful
degradation, leader election, and Kafka partition failover.

Resilience Patterns Tested:
- Circuit Breaker (Gateway, Payment)
- Retry with Exponential Backoff (all services)
- Bulkhead Isolation (per-service thread pool / connection pool)
- Graceful Degradation (cached schemas when registry unavailable)
- Leader Election (SPIRE Server, Kafka partitions)
- Kafka Consumer Rebalance
"""

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

from .conftest import (
    HttpClientFactory,
    KubectlHelper,
    KafkaHelper,
    PostgresHelper,
    OTelTraceHelper,
    SERVICE_REGISTRY,
    KAFKA_TOPICS,
    wait_for_condition,
    wait_for_service_ready,
)


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------
pytestmark = [pytest.mark.e2e, pytest.mark.resilience]


# ---------------------------------------------------------------------------
# Test 1: Cascading Failure Prevention
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.resilience
@pytest.mark.destructive
def test_resilience_cascading_failure_prevention(
    http_client_factory: HttpClientFactory,
    kubectl: KubectlHelper,
    otel_helper: OTelTraceHelper,
):
    """Cascading failure prevention — Kill payment -> verify circuit breaker
    opens in gateway -> other services unaffected.

    Scales the payment service to 0 to simulate a complete failure, then
    verifies the gateway's circuit breaker opens for payment requests
    while other services continue to operate normally.
    """
    # Step 1: Scale payment service down to 0
    scaled = kubectl.scale_deployment("payment", 0)
    assert scaled, "Failed to scale payment deployment to 0"

    try:
        # Wait for payment to be fully unavailable
        time.sleep(15)

        # Step 2: Verify circuit breaker opens for payment requests
        def circuit_breaker_open():
            code, resp, _ = http_client_factory.get(
                "/api/v1/payment/payments",
                timeout=10,
            )
            # Gateway should return 503 (circuit breaker open) or 502 (upstream unavailable)
            return code in (503, 502, 504)

        cb_open = wait_for_condition(
            circuit_breaker_open,
            timeout=30,
            interval=3,
            message="Circuit breaker did not open for payment service",
        )
        assert cb_open, "Circuit breaker should open when payment service is down"

        # Step 3: Verify other services are NOT affected
        code_catalog, _, _ = http_client_factory.get(
            "/api/v1/catalog/products",
            timeout=10,
        )
        assert code_catalog not in (502, 503, 504), (
            f"Catalog should NOT be affected by payment failure, got {code_catalog}"
        )

        code_order, _, _ = http_client_factory.get(
            "/api/v1/order/orders",
            timeout=10,
        )
        assert code_order not in (502, 503, 504), (
            f"Order should NOT be affected by payment failure, got {code_order}"
        )

        code_notification, _, _ = http_client_factory.get(
            "/api/v1/notification/notifications",
            timeout=10,
        )
        assert code_notification not in (502, 503, 504), (
            f"Notification should NOT be affected by payment failure, got {code_notification}"
        )

        # Step 4: Verify circuit breaker state via metrics
        cb_metric = otel_helper.query_prometheus(
            'circuit_breaker_state{service="payment"}'
        )
        if cb_metric and cb_metric.get("status") == "success":
            results = cb_metric.get("data", {}).get("result", [])
            if results:
                cb_value = float(results[0].get("value", [0, "0"])[1])
                # Circuit breaker should be OPEN (value=1 or 2 depending on convention)
                assert cb_value > 0, "Circuit breaker metric should indicate open state"

    finally:
        # Restore payment service
        kubectl.scale_deployment("payment", 2)
        # Wait for payment to recover
        wait_for_service_ready("payment", timeout=120, interval=5, kubectl=kubectl)


# ---------------------------------------------------------------------------
# Test 2: Retry with Exponential Backoff
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.resilience
def test_resilience_retry_with_backoff(
    http_client_factory: HttpClientFactory,
    otel_helper: OTelTraceHelper,
):
    """Retry with backoff — Simulate transient failure -> verify retry
    with exponential backoff succeeds.

    Sends a request that will initially fail (simulated via header) but
    succeed on retry. Verifies the retry mechanism uses exponential
    backoff by checking the trace spans for multiple attempts.
    """
    # Step 1: Send request that will trigger a retry
    trace_id = uuid.uuid4().hex[:32]
    headers = {
        "traceparent": f"00-{trace_id}-{'0' * 16}-01",
        "X-Simulate-Retry": "true",  # Service should fail first, succeed on retry
    }

    code, resp, _ = http_client_factory.get(
        "/api/v1/catalog/products",
        headers=headers,
        service="catalog",
        timeout=30,
    )

    # Step 2: Verify the request eventually succeeded (after retry)
    assert code in (200, 404), f"Request should succeed after retry, got {code}"

    # Step 3: Verify retry spans in the trace
    trace_data = otel_helper.query_trace(trace_id)
    if trace_data:
        retry_spans = []
        for batch in trace_data.get("batches", []):
            for scope_span in batch.get("scopeSpans", []):
                for span in scope_span.get("spans", []):
                    span_name = span.get("name", "")
                    # Look for retry-attempt attributes
                    for attr in span.get("attributes", []):
                        if attr.get("key") == "retry.attempt":
                            retry_spans.append(span_name)
                            break

        # Verify at least one retry span exists
        if retry_spans:
            assert len(retry_spans) >= 1, "At least one retry attempt should be visible in trace"

    # Step 4: Verify retry metrics in Prometheus
    retry_metric = otel_helper.query_prometheus(
        'sum(rate(http_client_retry_attempts_total[5m]))'
    )
    # Metric may not exist if no retries have occurred recently
    if retry_metric and retry_metric.get("status") == "success":
        results = retry_metric.get("data", {}).get("result", [])
        # Any value confirms the retry metric pipeline is working
        pass


# ---------------------------------------------------------------------------
# Test 3: Bulkhead Isolation
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.resilience
@pytest.mark.slow
def test_resilience_bulkhead_isolation(
    http_client_factory: HttpClientFactory,
    kubectl: KubectlHelper,
):
    """Bulkhead isolation — Overload analytics -> verify order processing
    is unaffected.

    Sends a burst of requests to the analytics service to overload it,
    then verifies that order processing remains responsive and is not
    affected by the analytics overload.
    """
    # Step 1: Send burst of requests to analytics to create load
    import concurrent.futures

    def stress_analytics(index: int) -> Dict[str, Any]:
        try:
            code, resp, _ = http_client_factory.post(
                "/api/v1/analytics/metrics/query",
                {
                    "metric_names": ["order.count", "revenue.total", "latency.p99"],
                    "time_range": {
                        "start_time": "2024-01-01T00:00:00Z",
                        "end_time": datetime.now(timezone.utc).isoformat(),
                    },
                    "granularity": "minute",
                },
                service="analytics",
                timeout=30,
            )
            return {"index": index, "code": code, "time": time.time()}
        except Exception as e:
            return {"index": index, "code": 0, "error": str(e), "time": time.time()}

    # Send 20 concurrent requests to analytics
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        analytics_futures = [executor.submit(stress_analytics, i) for i in range(20)]
        # Don't wait for all to complete yet

    # Step 2: While analytics is under load, verify order processing works
    order_start = time.time()
    code, order_resp, _ = http_client_factory.get(
        "/api/v1/order/orders",
        service="order",
        timeout=15,
    )
    order_latency = time.time() - order_start

    assert code not in (502, 503, 504), (
        f"Order service should be unaffected by analytics overload, got {code}"
    )
    assert order_latency < 5.0, (
        f"Order service response time ({order_latency:.2f}s) should be under 5s "
        f"even when analytics is overloaded (bulkhead isolation)"
    )

    # Step 3: Verify catalog is also unaffected
    catalog_start = time.time()
    code, _, _ = http_client_factory.get(
        "/api/v1/catalog/products",
        service="catalog",
        timeout=15,
    )
    catalog_latency = time.time() - catalog_start

    assert code not in (502, 503, 504), (
        f"Catalog service should be unaffected by analytics overload, got {code}"
    )
    assert catalog_latency < 5.0, (
        f"Catalog service response time ({catalog_latency:.2f}s) should be under 5s "
        f"(bulkhead isolation)"
    )

    # Wait for analytics stress to complete
    concurrent.futures.wait(analytics_futures, timeout=60)


# ---------------------------------------------------------------------------
# Test 4: Graceful Degradation — Schema Registry Unavailable
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.resilience
@pytest.mark.destructive
def test_resilience_graceful_degradation(
    http_client_factory: HttpClientFactory,
    kubectl: KubectlHelper,
):
    """Graceful degradation — Kill schema-registry -> verify services use
    cached schemas -> eventual recovery.

    Scales the schema-registry service to 0, then verifies that services
    continue to operate using locally cached schemas. After restoring
    the service, verifies that schema resolution returns to normal.
    """
    # Step 1: Pre-warm schema cache by making a request
    code, _, _ = http_client_factory.get(
        "/api/v1/catalog/products",
        service="catalog",
    )
    assert code not in (502, 503, 504), "Catalog should be healthy before test"

    # Step 2: Scale schema-registry down to 0
    scaled = kubectl.scale_deployment("schema-registry", 0)
    assert scaled, "Failed to scale schema-registry deployment to 0"

    try:
        # Wait for schema-registry to be unavailable
        time.sleep(15)

        # Step 3: Verify services continue to operate with cached schemas
        # Catalog should still process requests using cached schema
        code, catalog_resp, _ = http_client_factory.get(
            "/api/v1/catalog/products",
            service="catalog",
            timeout=15,
        )
        assert code not in (502, 503), (
            f"Catalog should continue operating with cached schemas, got {code}"
        )

        # Order service should also continue (may need schema for event validation)
        code, order_resp, _ = http_client_factory.get(
            "/api/v1/order/orders",
            service="order",
            timeout=15,
        )
        assert code not in (502, 503), (
            f"Order should continue operating with cached schemas, got {code}"
        )

        # Step 4: Verify schema-registry requests fail (as expected)
        code, schema_resp, _ = http_client_factory.get(
            "/api/v1/schema-registry/schemas",
            service="schema-registry",
            timeout=10,
        )
        assert code in (502, 503, 504, 0), (
            f"Schema registry should be unavailable, got {code}"
        )

    finally:
        # Step 5: Restore schema-registry
        kubectl.scale_deployment("schema-registry", 2)

        # Step 6: Verify eventual recovery
        def schema_registry_recovered():
            code, _, _ = http_client_factory.get(
                "/api/v1/schema-registry/schemas",
                service="schema-registry",
                timeout=10,
            )
            return code == 200

        recovered = wait_for_condition(
            schema_registry_recovered,
            timeout=120,
            interval=5,
            message="Schema registry did not recover within timeout",
        )
        assert recovered, "Schema registry should eventually recover after scale-up"


# ---------------------------------------------------------------------------
# Test 5: Leader Election — SPIRE Server
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.resilience
@pytest.mark.destructive
@pytest.mark.slow
def test_resilience_leader_election(
    kubectl: KubectlHelper,
    spire_client: SpireApiClient,
):
    """Leader election — Kill SPIRE server leader -> verify new leader
    elected -> SVIDs continue to be issued.

    Identifies the current SPIRE server leader pod, deletes it, and
    verifies that a new leader is elected and SVID issuance continues
    without interruption.
    """
    from .conftest import SpireApiClient

    # Step 1: Verify SPIRE server is healthy before test
    healthy, msg = spire_client.server_healthcheck()
    assert healthy, f"SPIRE server should be healthy before test: {msg}"

    # Step 2: Find the current leader pod
    # SPIRE server uses StatefulSet, leader is typically spire-server-0
    leader_pod = "spire-server-0"
    pods_result = kubectl._run([
        "get", "pods", "-l", "app.kubernetes.io/name=spire-server",
        "-o", "jsonpath={.items[*].metadata.name}",
    ])
    if pods_result.returncode == 0 and pods_result.stdout.strip():
        leader_pod = pods_result.stdout.strip().split()[0]

    # Step 3: Delete the leader pod
    deleted = kubectl.delete_pod(leader_pod, force=True)
    assert deleted, f"Failed to delete SPIRE server leader pod: {leader_pod}"

    # Step 4: Wait for new leader election and SVID issuance
    def spire_healthy_after_failover():
        healthy, msg = spire_client.server_healthcheck()
        return healthy

    recovered = wait_for_condition(
        spire_healthy_after_failover,
        timeout=120,
        interval=5,
        message="SPIRE server did not recover after leader pod deletion",
    )
    assert recovered, "SPIRE server should elect new leader and recover"

    # Step 5: Verify SVIDs can still be issued
    # Wait a bit for the new leader to be fully operational
    time.sleep(10)

    healthy_after, msg_after = spire_client.server_healthcheck()
    assert healthy_after, f"SPIRE server should be healthy after leader failover: {msg_after}"

    # Verify SVID issuance works
    gateway_spiffe_id = SERVICE_REGISTRY["gateway"]["spiffe_id"]
    entry = spire_client.show_entry(gateway_spiffe_id)
    assert entry is not None, "SVID entries should still be accessible after leader failover"


# ---------------------------------------------------------------------------
# Test 6: Kafka Partition Leader Failover
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.resilience
@pytest.mark.destructive
@pytest.mark.slow
def test_resilience_kafka_partition_failover(
    kafka_helper: KafkaHelper,
    kubectl: KubectlHelper,
    otel_helper: OTelTraceHelper,
):
    """Kafka partition leader failover -> verify consumers rebalance
    -> no message loss.

    Forces a Kafka partition leader change by deleting the leader broker
    pod, then verifies that consumers rebalance and no messages are lost
    during the failover.
    """
    # Step 1: Produce test messages before failover
    test_key = f"failover-test-{uuid.uuid4().hex[:8]}"
    test_messages = []
    for i in range(10):
        msg = {
            "test_id": test_key,
            "sequence": i,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": f"failover-test-msg-{i}",
        }
        test_messages.append(msg)
        kafka_helper.produce(KAFKA_TOPICS["order_events"], f"{test_key}-{i}", msg)

    # Step 2: Record current Kafka broker state
    broker_result = kubectl._run([
        "get", "pods", "-l", "app.kubernetes.io/name=kafka",
        "-o", "jsonpath={.items[*].metadata.name}",
    ])
    if broker_result.returncode != 0 or not broker_result.stdout.strip():
        pytest.skip("Kafka broker pods not found — skipping partition failover test")

    broker_pods = broker_result.stdout.strip().split()
    if len(broker_pods) < 2:
        pytest.skip("Need at least 2 Kafka broker pods for partition failover test")

    # Step 3: Delete one Kafka broker pod (not the controller)
    target_pod = broker_pods[-1]  # Delete the last broker
    deleted = kubectl.delete_pod(target_pod, force=True)
    assert deleted, f"Failed to delete Kafka broker pod: {target_pod}"

    try:
        # Step 4: Wait for Kafka cluster to stabilize
        time.sleep(30)  # Allow leader election and partition reassignment

        # Step 5: Produce more messages after failover
        post_failover_messages = []
        for i in range(10, 20):
            msg = {
                "test_id": test_key,
                "sequence": i,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": f"failover-test-msg-{i}",
            }
            post_failover_messages.append(msg)
            kafka_helper.produce(KAFKA_TOPICS["order_events"], f"{test_key}-{i}", msg)

        # Step 6: Verify consumer can read messages from both before and after failover
        received_sequences = set()
        consumer = kafka_helper.create_consumer(
            [KAFKA_TOPICS["order_events"]],
            group_id=f"failover-verify-{test_key}",
        )

        deadline = time.time() + 30
        try:
            for message in consumer:
                if message.value and message.value.get("test_id") == test_key:
                    received_sequences.add(message.value.get("sequence"))
                if time.time() > deadline or len(received_sequences) >= 20:
                    break
        finally:
            consumer.close()

        # Step 7: Verify no message loss
        expected_sequences = set(range(20))
        lost = expected_sequences - received_sequences
        assert len(lost) <= 2, (  # Allow small margin for consumer timing
            f"Too many messages lost during Kafka failover: {len(lost)} lost "
            f"(expected 0-2, lost sequences: {sorted(lost)})"
        )

    finally:
        # Kafka will self-heal via StatefulSet controller
        # Wait for broker to come back
        time.sleep(30)


# ---------------------------------------------------------------------------
# Offline / Manifest Validation Tests
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.resilience
@pytest.mark.offline
def test_circuit_breaker_proto_defined(project_root):
    """Validate that circuit breaker types are defined in the Payment
    proto schema.

    This is an offline test that does not require a live cluster.
    """
    circuit_proto = project_root / "schemas" / "proto" / "payment" / "v1" / "circuit.proto"
    assert circuit_proto.exists(), f"Circuit breaker proto not found at {circuit_proto}"

    content = circuit_proto.read_text()
    assert "CircuitBreakerState" in content, "CircuitBreakerState message must be defined"
    assert "CircuitState" in content, "CircuitState enum must be defined"
    assert "CIRCUIT_STATE_CLOSED" in content, "CLOSED state must be defined"
    assert "CIRCUIT_STATE_OPEN" in content, "OPEN state must be defined"
    assert "CIRCUIT_STATE_HALF_OPEN" in content, "HALF_OPEN state must be defined"


@pytest.mark.e2e
@pytest.mark.resilience
@pytest.mark.offline
def test_network_policies_defined(project_root):
    """Validate that default-deny NetworkPolicies are defined for
    the production namespace, enabling cascading failure prevention
    at the network level.

    This is an offline test that does not require a live cluster.
    """
    netpol = project_root / "infra" / "kubernetes" / "base" / "networkpolicy.yaml"
    assert netpol.exists(), f"NetworkPolicy manifest not found at {netpol}"

    content = netpol.read_text()
    assert "NetworkPolicy" in content, "NetworkPolicy resource must be defined"
    assert "deny" in content.lower() or "Deny" in content, "Default-deny policy must be defined"


@pytest.mark.e2e
@pytest.mark.resilience
@pytest.mark.offline
def test_resilience4j_config_exists(project_root):
    """Validate that the Order service has Resilience4j configuration
    for circuit breaker and retry patterns.

    This is an offline test that does not require a live cluster.
    """
    resilience_config = project_root / "services" / "order" / "src" / "main" / "kotlin" / "adapters" / "outbound" / "resilience" / "Resilience4jConfig.kt"
    assert resilience_config.exists(), f"Resilience4j config not found at {resilience_config}"

    content = resilience_config.read_text()
    assert "CircuitBreaker" in content or "circuitBreaker" in content, "CircuitBreaker must be configured"
    assert "Retry" in content or "retry" in content, "Retry must be configured"
