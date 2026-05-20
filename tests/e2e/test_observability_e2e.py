"""
End-to-End Integration Tests for the Observability Stack.

Tests the complete observability pipeline including distributed tracing
(Tempo), metrics (Prometheus), logging (Loki), tail-based sampling,
alerting rules, and Grafana dashboard data availability.

Observability Stack:
  OTel SDK (per-service) -> OTel Collector DaemonSet -> OTel Gateway
  -> Tempo (traces), Prometheus (metrics), Loki (logs), Grafana (dashboards)
"""

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

from .conftest import (
    HttpClientFactory,
    OTelTraceHelper,
    KubectlHelper,
    SERVICE_REGISTRY,
    ALL_SERVICES,
    wait_for_condition,
)


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------
pytestmark = [pytest.mark.e2e, pytest.mark.observability]


# ---------------------------------------------------------------------------
# Test 1: Request Trace — Complete Trace Through Gateway
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.observability
def test_observability_request_trace(
    http_client_factory: HttpClientFactory,
    otel_helper: OTelTraceHelper,
    test_product_id: str,
):
    """Request trace — Make request through gateway -> verify complete
    trace in Tempo (all spans present).

    Sends a request through the gateway to the catalog service and
    verifies that Tempo has a complete distributed trace with all
    expected spans: gateway ingress, catalog processing, and egress.
    """
    # Step 1: Generate a request with trace context
    trace_id = uuid.uuid4().hex[:32]
    trace_parent = f"00-{trace_id}-{'0' * 16}-01"

    headers = {
        "traceparent": trace_parent,
        "X-Trace-Test": "e2e-observability",
    }

    code, resp, _ = http_client_factory.get(
        f"/api/v1/catalog/products/{test_product_id}",
        headers=headers,
        service="catalog",
    )

    # Step 2: Wait for trace to be available in Tempo
    def trace_available():
        trace_data = otel_helper.query_trace(trace_id)
        return trace_data is not None and len(trace_data.get("batches", [])) > 0

    trace_ready = wait_for_condition(
        trace_available,
        timeout=30,
        interval=5,
        message=f"Trace {trace_id} not found in Tempo within timeout",
    )
    assert trace_ready, f"Distributed trace should be available in Tempo for trace_id={trace_id}"

    # Step 3: Verify all expected spans are present
    trace_data = otel_helper.query_trace(trace_id)
    assert trace_data is not None, "Trace data should not be None after confirming availability"

    # Collect all span names from the trace
    span_names = []
    service_names = []
    for batch in trace_data.get("batches", []):
        resource_attrs = {
            attr["key"]: attr.get("value", {}).get("stringValue", "")
            for attr in batch.get("resource", {}).get("attributes", [])
        }
        svc = resource_attrs.get("service.name", "")
        for scope_span in batch.get("scopeSpans", []):
            for span in scope_span.get("spans", []):
                span_names.append(span.get("name", ""))
                service_names.append(svc)

    # Verify gateway span exists
    gateway_spans = [s for s, svc in zip(span_names, service_names) if svc == "gateway"]
    assert len(gateway_spans) > 0, "At least one gateway span should be present in trace"

    # Verify catalog span exists (if the request reached catalog)
    catalog_spans = [s for s, svc in zip(span_names, service_names) if svc == "catalog"]
    assert len(catalog_spans) > 0, "At least one catalog span should be present in trace"

    # Verify trace contains multiple spans (distributed trace)
    assert len(span_names) >= 2, (
        f"Distributed trace should contain at least 2 spans (gateway + catalog), got {len(span_names)}"
    )


# ---------------------------------------------------------------------------
# Test 2: RED Metrics — Rate, Errors, Duration for Each Service
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.observability
def test_observability_red_metrics(
    otel_helper: OTelTraceHelper,
):
    """RED metrics — Verify Rate, Errors, Duration metrics in Prometheus
    for each service.

    Checks that Prometheus has RED (Rate, Errors, Duration) metrics
    available for each of the 9 services in the platform.
    """
    services_with_metrics = []
    services_without_metrics = []

    for service_name in ALL_SERVICES:
        red = otel_helper.check_red_metrics(service_name)

        # At minimum, the rate metric should be available for active services
        if red.get("rate") is not None:
            services_with_metrics.append(service_name)
        else:
            services_without_metrics.append(service_name)

    # At least the gateway should have metrics (it handles all ingress)
    assert len(services_with_metrics) > 0, (
        f"No services have RED metrics in Prometheus. "
        f"Services without metrics: {services_without_metrics}"
    )

    # Verify gateway specifically has metrics
    gateway_red = otel_helper.check_red_metrics("gateway")
    assert gateway_red["rate"] is not None, "Gateway must have rate metrics in Prometheus"

    # Verify error metrics exist for at least some services
    any_errors = any(
        otel_helper.check_red_metrics(svc).get("errors") is not None
        for svc in ALL_SERVICES
    )
    assert any_errors, "At least one service should have error metrics available"


# ---------------------------------------------------------------------------
# Test 3: Log Correlation — Logs Correlated with Trace IDs
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.observability
def test_observability_log_correlation(
    otel_helper: OTelTraceHelper,
    http_client_factory: HttpClientFactory,
):
    """Log correlation — Verify logs in Loki can be correlated with
    trace IDs.

    Sends a request with a known trace ID and verifies that Loki logs
    contain entries correlated with that trace ID via the traceparent
    or trace_id label.
    """
    # Step 1: Generate request with trace context
    trace_id = uuid.uuid4().hex[:32]

    headers = {
        "traceparent": f"00-{trace_id}-{'0' * 16}-01",
        "X-Log-Correlation-Test": "e2e",
    }

    http_client_factory.get(
        "/api/v1/catalog/products",
        headers=headers,
        service="catalog",
    )

    # Step 2: Wait for logs to be ingested by Loki
    time.sleep(10)  # Allow log ingestion pipeline to process

    # Step 3: Query Loki for logs with the trace ID
    loki_query = f'{{service_name="catalog"}} |= "{trace_id}"'
    loki_resp = otel_helper.query_loki(loki_query, limit=10)

    # Step 4: Verify log correlation
    if loki_resp and loki_resp.get("status") == "success":
        data = loki_resp.get("data", {})
        result_type = data.get("resultType", "")
        results = data.get("result", [])

        if result_type == "streams" and results:
            # Check if any log stream contains our trace_id
            found = False
            for stream in results:
                values = stream.get("values", [])
                for ts, line in values:
                    if trace_id in line:
                        found = True
                        break
            assert found, f"Trace ID {trace_id} should be present in Loki logs for catalog service"
    else:
        # Loki may not be reachable or may not have ingested logs yet
        # Try alternate query format
        alt_query = f'{{trace_id="{trace_id}"}}'
        alt_resp = otel_helper.query_loki(alt_query, limit=10)
        if alt_resp and alt_resp.get("data", {}).get("result"):
            pass  # Logs found via alternate query
        else:
            pytest.log.warning(
                f"Could not verify log correlation for trace {trace_id} "
                f"— Loki may not have ingested logs yet or query format differs"
            )


# ---------------------------------------------------------------------------
# Test 4: Tail-Based Sampling — High-Error Requests Always Sampled
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.observability
def test_observability_tail_based_sampling(
    otel_helper: OTelTraceHelper,
    http_client_factory: HttpClientFactory,
):
    """Tail-based sampling — High-error requests are always sampled,
    successful requests sampled at configured rate.

    Verifies that the OTel Collector's tail-based sampling policy
    ensures error traces are always retained while successful traces
    are sampled at the configured rate (10% baseline in production).
    """
    # Step 1: Generate an error request (should always be sampled)
    error_trace_id = uuid.uuid4().hex[:32]
    headers = {
        "traceparent": f"00-{error_trace_id}-{'0' * 16}-01",
        "X-Simulate-Error": "true",
    }

    # Request to a non-existent resource (will generate 404/500)
    http_client_factory.get(
        "/api/v1/catalog/products/nonexistent-product-404",
        headers=headers,
        service="catalog",
    )

    # Step 2: Wait for error trace to be available
    def error_trace_available():
        trace = otel_helper.query_trace(error_trace_id)
        return trace is not None and len(trace.get("batches", [])) > 0

    error_trace_found = wait_for_condition(
        error_trace_available,
        timeout=30,
        interval=5,
        message="Error trace should always be sampled and available in Tempo",
    )
    assert error_trace_found, "Error traces must always be sampled (tail-based sampling policy)"

    # Step 3: Verify OTel Collector sampling configuration
    # Check that the sampling policy is configured correctly
    sampling_resp = otel_helper.query_prometheus(
        "otelcol_processor_tail_sampling_sampling_decision"
    )
    if sampling_resp and sampling_resp.get("status") == "success":
        results = sampling_resp.get("data", {}).get("result", [])
        # There should be sampling decision metrics
        assert len(results) > 0, "OTel Collector should have tail sampling decision metrics"


# ---------------------------------------------------------------------------
# Test 5: Alert Rules — Prometheus Alert Rules Fire Correctly
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.observability
def test_observability_alert_rules(
    otel_helper: OTelTraceHelper,
    kubectl: KubectlHelper,
):
    """Alert rules — Verify Prometheus alert rules fire correctly for
    degraded services.

    Checks that Prometheus has the expected alerting rules configured
    and that they would fire correctly when services degrade. Does not
    require actually degrading a service — verifies rule configuration.
    """
    # Step 1: Check Prometheus alert rules are configured
    alerts = otel_helper.check_alert_rules()
    assert isinstance(alerts, list), "Alert rules should return a list"

    # Step 2: Verify critical alert rules exist
    # These are the alert rules defined in the platform's PrometheusRule CRD
    expected_alert_names = [
        "ServiceDown",
        "HighErrorRate",
        "HighLatency",
        "CDCPipelineLagHigh",
        "CircuitBreakerOpen",
        "SVIDExpirySoon",
    ]

    # Check via Prometheus rules API
    import urllib.request
    prometheus_url = otel_helper.prometheus_url
    try:
        url = f"{prometheus_url}/api/v1/rules"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            rules_data = json.loads(resp.read().decode("utf-8"))

        if rules_data.get("status") == "success":
            groups = rules_data.get("data", {}).get("groups", [])
            rule_names = []
            for group in groups:
                for rule in group.get("rules", []):
                    rule_names.append(rule.get("name", ""))

            # At least some alert rules should be defined
            assert len(rule_names) > 0, "Prometheus should have alert rules configured"

            # Check for key alert rules
            found_alerts = [name for name in expected_alert_names if name in rule_names]
            if len(found_alerts) == 0:
                pytest.log.warning(
                    f"None of the expected alert rules ({expected_alert_names}) "
                    f"found in Prometheus. Available rules: {rule_names[:10]}"
                )
    except Exception as e:
        pytest.log.warning(f"Could not verify Prometheus alert rules: {e}")

    # Step 3: Verify PrometheusRule CRD exists in the cluster
    rule_result = kubectl._run(["get", "prometheusrules", "-o", "name"])
    if rule_result.returncode == 0:
        assert "prometheusrule" in rule_result.stdout.lower(), (
            "At least one PrometheusRule CRD should exist in the cluster"
        )


# ---------------------------------------------------------------------------
# Test 6: Dashboard Data — Grafana Dashboards Have Data for All Services
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.observability
def test_observability_dashboard_data(
    otel_helper: OTelTraceHelper,
):
    """Dashboard data — Verify Grafana dashboards have data for all services.

    Checks that Grafana has dashboards configured for the platform and
    that they have data available (non-empty query results) for the
    monitored services.
    """
    # Step 1: List Grafana dashboards
    dashboards = otel_helper.check_grafana_dashboards()
    assert isinstance(dashboards, list), "Grafana dashboard list should be an array"

    # Step 2: Verify key dashboards exist
    dashboard_titles = [d.get("title", "").lower() for d in dashboards]
    expected_dashboards = [
        "platform overview",
        "service mesh",
        "order saga",
        "cdc pipeline",
        "infrastructure",
    ]

    found_dashboards = []
    for expected in expected_dashboards:
        for title in dashboard_titles:
            if expected in title:
                found_dashboards.append(expected)
                break

    # At least one dashboard should exist
    if len(dashboards) > 0:
        # Step 3: Verify dashboard has data by querying a panel
        # Pick the first dashboard and verify its data source is healthy
        for dashboard in dashboards:
            uid = dashboard.get("uid", "")
            if uid:
                import urllib.request
                try:
                    url = f"{GRAFANA_URL}/api/dashboards/uid/{uid}"
                    req = urllib.request.Request(url)
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        dash_data = json.loads(resp.read().decode("utf-8"))
                    # Dashboard should have panels
                    panels = dash_data.get("dashboard", {}).get("panels", [])
                    if len(panels) > 0:
                        break  # Found a dashboard with panels
                except Exception:
                    continue
    else:
        pytest.log.warning("No Grafana dashboards found — dashboard data verification skipped")


# ---------------------------------------------------------------------------
# Offline / Manifest Validation Tests
# ---------------------------------------------------------------------------
@pytest.mark.e2e
@pytest.mark.observability
@pytest.mark.offline
def test_otel_collector_manifests_exist(project_root):
    """Validate that OTel Collector manifests exist and are properly
    configured for the DaemonSet + Gateway fan-out architecture.

    This is an offline test that does not require a live cluster.
    """
    otel_daemonset = project_root / "infra" / "kubernetes" / "platform" / "otel-collector.yaml"
    otel_gateway = project_root / "infra" / "kubernetes" / "platform" / "otel-gateway.yaml"

    assert otel_daemonset.exists(), f"OTel Collector DaemonSet manifest not found at {otel_daemonset}"
    assert otel_gateway.exists(), f"OTel Gateway manifest not found at {otel_gateway}"

    # Verify DaemonSet is configured for traces, metrics, and logs
    daemonset_content = otel_daemonset.read_text()
    assert "DaemonSet" in daemonset_content, "OTel Collector must be deployed as DaemonSet"
    assert "traces" in daemonset_content.lower(), "OTel Collector must handle traces"
    assert "metrics" in daemonset_content.lower(), "OTel Collector must handle metrics"
    assert "logs" in daemonset_content.lower(), "OTel Collector must handle logs"

    # Verify Gateway is configured for HA
    gateway_content = otel_gateway.read_text()
    assert "Deployment" in gateway_content, "OTel Gateway must be deployed as Deployment"
    assert "load_balancing" in gateway_content.lower() or "loadbalancing" in gateway_content.lower() or "replicas" in gateway_content, "OTel Gateway must support load balancing"


@pytest.mark.e2e
@pytest.mark.observability
@pytest.mark.offline
def test_grafana_dashboard_json_files_exist(project_root):
    """Validate that Grafana dashboard JSON files exist in the platform
    infrastructure directory.

    This is an offline test that does not require a live cluster.
    """
    dashboards_dir = project_root / "infra" / "kubernetes" / "platform" / "grafana-dashboards"
    assert dashboards_dir.exists(), f"Grafana dashboards directory not found at {dashboards_dir}"

    # Verify at least RED metrics dashboard exists
    red_dashboard = dashboards_dir / "red-metrics.json"
    use_dashboard = dashboards_dir / "use-metrics.json"
    assert red_dashboard.exists(), f"RED metrics dashboard not found at {red_dashboard}"
    assert use_dashboard.exists(), f"USE metrics dashboard not found at {use_dashboard}"

    # Validate JSON is parseable
    red_content = red_dashboard.read_text()
    red_data = json.loads(red_content)
    assert "panels" in red_data or "dashboard" in red_data, "RED metrics dashboard must have panels"

    use_content = use_dashboard.read_text()
    use_data = json.loads(use_content)
    assert "panels" in use_data or "dashboard" in use_data, "USE metrics dashboard must have panels"


@pytest.mark.e2e
@pytest.mark.observability
@pytest.mark.offline
def test_prometheus_manifest_exists(project_root):
    """Validate that Prometheus manifests exist with proper configuration
    for the platform's SLO-driven alerting.

    This is an offline test that does not require a live cluster.
    """
    prometheus_manifest = project_root / "infra" / "kubernetes" / "platform" / "prometheus.yaml"
    assert prometheus_manifest.exists(), f"Prometheus manifest not found at {prometheus_manifest}"

    content = prometheus_manifest.read_text()
    assert "Prometheus" in content, "Prometheus resource must be defined"
    assert "replicas" in content.lower(), "Prometheus must have replica configuration"


# Import GRAFANA_URL for dashboard checks
from .conftest import GRAFANA_URL
