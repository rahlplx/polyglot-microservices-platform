# Phase 4 Initialization Plan

```markdown
# Phase 4: Testing, Validation & Observability Activation

## Overview

Phase 4 transitions the platform from implementation-complete to production-ready through three parallel workstreams: (1) OpenTelemetry Collector and Grafana dashboard activation for RED/USE metrics, (2) comprehensive testing validation across all 9 polyglot services, and (3) the first Chaos Engineering exercise executing the automated programmatic cloud shift defined in the master specification.

**Prerequisite:** Phase 3 COMPLETE — PR #1 merged, v0.3.0 tagged, 13 tracked remediations acknowledged.

---

## Step 1: Phase 3 Remediation Closure (Prerequisite Gate)

Before any Phase 4 work begins, the following PR #1 review findings must be resolved by worker agents:

### Critical Path Remediations (Must fix before testing)

| ID | File(s) | Fix | Agent Assignment |
|----|---------|-----|-----------------|
| V-1 | `services/analytics/src/domain/services/analytics_service.py` | Replace `datetime.utcnow()` with `datetime.now(timezone.utc)` at lines 127-128, 226-227 | Python Remediation Agent |
| V-2 | `services/analytics/src/domain/services/dashboard_service.py` | Replace `datetime.utcnow()` with `datetime.now(timezone.utc)` at lines 117-118, 142, 374, 387 | Python Remediation Agent |
| V-3 | `services/analytics/src/domain/services/report_service.py` | Replace `datetime.utcnow()` with `datetime.now(timezone.utc)` at lines 131-132, 171, 378, 391 | Python Remediation Agent |
| V-4 | `services/payment/domain/models/payment.go` | Replace `time.Now()` with `time.Now().UTC()` at lines 151, 153 | Go Remediation Agent |
| V-5 | `services/payment/domain/models/refund.go` | Replace `time.Now()` with `time.Now().UTC()` at line 97 | Go Remediation Agent |
| V-6 | `services/payment/domain/services/circuit_breaker.go` | Replace `time.Now()` with `time.Now().UTC()` at lines 39, 115, 154 | Go Remediation Agent |
| V-7 | `services/payment/domain/services/refund_service.go` | Replace `time.Now()` with `time.Now().UTC()` at lines 126-127 | Go Remediation Agent |

### Medium Priority Remediations (Can parallelize with Phase 4)

| ID | Description | Agent Assignment |
|----|-------------|-----------------|
| V-8 | Add `spiffe.io/inject: "true"` pod annotations to all K8s deployment overlays | Infrastructure Agent |
| V-9 | Generate OpenAPI 3.1 specs for identity, catalog, order, notification, analytics, rl-engine | Schema Agent |
| V-10 | Remove service-local proto copies, reference centralized `schemas/proto/` only | Schema Agent |
| V-11 | Create `infra/terraform/` modules for VPC, cluster, node groups, managed DBs | Infrastructure Agent |
| V-12 | Create `.github/workflows/` CI/CD pipeline (lint → test → build → deploy) | Infrastructure Agent |

### Low Priority (Architectural Debt)

| ID | Description | Agent Assignment |
|----|-------------|-----------------|
| V-13 | Refactor `SearchDocument` in catalog domain port to use `price: Money` instead of flat fields | Catalog Agent |

**Gate:** V-1 through V-7 must be merged to develop before Phase 4 testing begins. V-8 through V-13 can proceed in parallel.

---

## Step 2: OpenTelemetry Collector Configuration

### 2.1 OTel Gateway Deployment (HA)

Deploy the OTel Gateway as a highly-available Deployment (2+ replicas) that receives telemetry from the OTel Collector DaemonSets and exports to backend systems.

**File:** `infra/kubernetes/platform/otel-gateway.yaml` (already exists — needs validation)

**Validation Checklist:**
- [ ] Gateway Deployment has 2+ replicas with anti-affinity rules
- [ ] Receivers match Collector export configuration (OTLP/gRPC on 4317)
- [ ] Processors include: `memory_limiter`, `batch`, `filter`, `transform`
- [ ] Exporters configured for: Prometheus (metrics), Tempo (traces), Loki (logs)
- [ ] TLS configuration references SPIRE bundle for mTLS between Collector → Gateway
- [ ] Resource detection processor adds cloud provider metadata
- [ ] Health check endpoint enabled on port 13133

**Configuration for OTel Gateway (`config.yaml`):**

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
        max_recv_msg_size_mib: 32
      http:
        endpoint: 0.0.0.0:4318

processors:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 80
    spike_limit_percentage: 25

  batch:
    send_batch_size: 16384
    send_batch_max_size: 32768
    timeout: 10s

  resource:
    attributes:
      - key: collector.source
        value: "gateway"
        action: upsert

  resource_detection:
    detectors: [env, system]
    timeout: 5s

  transform:
    error_mode: ignore
    trace_statements:
      - context: span
        statements:
          - set(attributes["deployment.environment"], "production") where attributes["deployment.environment"] == nil

exporters:
  prometheus:
    endpoint: 0.0.0.0:8889
    namespace: polyglot_platform
    send_timestamps: true
    metric_expiration: 5m

  otlphttp/tempo:
    endpoint: http://tempo.production.svc.cluster.local:4318
    tls:
      ca_file: /etc/spire/certs/bundle.crt

  loki:
    endpoint: http://loki.production.svc.cluster.local:3100/loki/api/v1/push
    default_labels_enabled:
      exporter: false
      job: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, resource, resource_detection, transform, batch]
      exporters: [otlphttp/tempo]
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, resource, resource_detection, transform, batch]
      exporters: [prometheus]
    logs:
      receivers: [otlp]
      processors: [memory_limiter, resource, transform, batch]
      exporters: [loki]
  telemetry:
    logs:
      level: info
    metrics:
      address: 0.0.0.0:8888
```

### 2.2 Backend Stack Deployment

Deploy the observability backend stack (Prometheus, Tempo, Loki, Grafana) into the `production` namespace.

**Files to create:**
- `infra/kubernetes/platform/prometheus.yaml` — Prometheus StatefulSet with remote-write from OTel Gateway
- `infra/kubernetes/platform/tempo.yaml` — Tempo StatefulSet for trace storage
- `infra/kubernetes/platform/loki.yaml` — Loki StatefulSet for log aggregation
- `infra/kubernetes/platform/grafana.yaml` — Grafana Deployment with datasource provisioning

**Key Configuration:**
- Prometheus: 50Gi PVC, 15-day retention, remote-write from OTel Gateway prometheus exporter
- Tempo: 100Gi PVC, 30-day trace retention, search enabled
- Loki: 100Gi PVC, 30-day log retention, structured metadata enabled
- Grafana: Datasources auto-provisioned via ConfigMaps (Prometheus, Tempo, Loki)

---

## Step 3: Grafana Dashboard Configuration for RED/USE Metrics

### 3.1 RED Metrics Dashboard (Request-Rate-Error-Duration)

**Dashboard:** `RED Metrics — Service Overview`
**UID:** `red-metrics-overview`
**File:** `infra/kubernetes/platform/grafana-dashboards/red-metrics.json`

**Panels (8 panels):**

1. **Request Rate (Requests/sec)** — Time series graph, one line per service
   - Metric: `rate(http_server_duration_count[5m])`
   - Group by: `service.name`
   - Y-axis: Requests/sec

2. **Error Rate (%)** — Time series graph, one line per service
   - Metric: `rate(http_server_duration_count{http.status_code >= 500}[5m]) / rate(http_server_duration_count[5m]) * 100`
   - Group by: `service.name`
   - Alert threshold: >1% (warning), >5% (critical)

3. **Duration p50/p95/p99 (ms)** — Time series graph with 3 lines per service
   - Metric: `histogram_quantile(0.50, rate(http_server_duration_bucket[5m]))`
   - Metric: `histogram_quantile(0.95, rate(http_server_duration_bucket[5m]))`
   - Metric: `histogram_quantile(0.99, rate(http_server_duration_bucket[5m]))`
   - Group by: `service.name`
   - Alert threshold: p99 > 500ms (warning), p99 > 2000ms (critical)

4. **gRPC Request Rate** — Time series graph for inter-service gRPC traffic
   - Metric: `rate(rpc_server_duration_count[5m])`
   - Group by: `rpc.service`, `rpc.method`

5. **gRPC Error Rate** — Time series graph
   - Metric: `rate(rpc_server_duration_count{rpc.grpc.status_code != 0}[5m]) / rate(rpc_server_duration_count[5m]) * 100`
   - Group by: `rpc.service`

6. **Active SVIDs** — Stat panel showing SPIFFE/SPIRE workload attestation count
   - Metric: `spire_agent_svid_count`
   - Threshold: <9 = critical (not all services attested)

7. **Circuit Breaker States** — Heatmap or bar chart
   - Metric: `circuit_breaker_state`
   - Group by: `gateway_id`, `state` (closed/open/half_open)

8. **Kafka Consumer Lag** — Time series graph
   - Metric: `kafka_consumer_group_lag`
   - Group by: `topic`, `consumer_group`
   - Alert threshold: lag > 1000 (warning), lag > 10000 (critical)

### 3.2 USE Metrics Dashboard (Utilization-Saturation-Errors)

**Dashboard:** `USE Metrics — Infrastructure`
**UID:** `use-metrics-infrastructure`
**File:** `infra/kubernetes/platform/grafana-dashboards/use-metrics.json`

**Panels (8 panels):**

1. **CPU Utilization (%)** — Time series graph per service pod
   - Metric: `rate(container_cpu_usage_seconds_total{namespace="production"}[5m]) / container_spec_cpu_quota * 100`
   - Group by: `pod`
   - Alert threshold: >80% (warning), >95% (critical)

2. **Memory Utilization (%)** — Time series graph per service pod
   - Metric: `container_memory_working_set_bytes{namespace="production"} / container_spec_memory_limit_bytes * 100`
   - Group by: `pod`
   - Alert threshold: >80% (warning), >95% (critical)

3. **Disk I/O Saturation** — Time series graph
   - Metric: `rate(container_fs_reads_total{namespace="production"}[5m])` and `rate(container_fs_writes_total{namespace="production"}[5m])`
   - Group by: `pod`

4. **Network Saturation (bytes/sec)** — Time series graph
   - Metric: `rate(container_network_transmit_bytes_total{namespace="production"}[5m])` and `rate(container_network_receive_bytes_total{namespace="production"}[5m])`
   - Group by: `pod`

5. **Pod Restarts** — Stat panel with alert
   - Metric: `kube_pod_container_status_restarts_total{namespace="production"}`
   - Alert threshold: >0 in last 1h

6. **OOMKills** — Stat panel with alert
   - Metric: `kube_pod_container_status_terminated_reason{reason="OOMKilled", namespace="production"}`
   - Alert threshold: >0

7. **Kafka Broker Disk Usage** — Gauge per broker
   - Metric: `kafka_log_size`
   - Group by: `broker`
   - Alert threshold: >80% of PVC capacity

8. **Debezium Connector Status** — Stat panel
   - Metric: `kafka_connect_connector_status`
   - Group by: `connector`, `state` (running/paused/failed)
   - Alert: FAILED state triggers PagerDuty

### 3.3 Grafana Datasource Provisioning

**File:** `infra/kubernetes/platform/grafana-datasources.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-datasources
  namespace: production
data:
  datasources.yaml: |
    apiVersion: 1
    datasources:
      - name: Prometheus
        type: prometheus
        access: proxy
        url: http://prometheus.production.svc.cluster.local:9090
        isDefault: true
        editable: false
      - name: Tempo
        type: tempo
        access: proxy
        url: http://tempo.production.svc.cluster.local:3200
        editable: false
        jsonData:
          tracesToMetrics:
            datasourceUid: prometheus
            tags: ['service.name', 'rpc.method']
      - name: Loki
        type: loki
        access: proxy
        url: http://loki.production.svc.cluster.local:3100
        editable: false
        jsonData:
          derivedFields:
            - datasourceUid: tempo
              matcherRegex: 'trace_id=(\w+)'
              url: '$${__value.raw}'
              name: TraceID
```

---

## Step 4: Testing & Validation Suite

### 4.1 Contract Testing (Pact)

Execute consumer-driven contract tests across all 9 services:

```bash
# Run all contract tests (each service has a contracts/ directory)
for service in gateway identity catalog order payment notification analytics rl-engine schema-registry; do
  cd services/$service
  # Run service-specific contract test command
  # Go: go test ./tests/contract/...
  # Rust: cargo test --test contract
  # Python: pytest tests/contract/
  # Kotlin: ./gradlew contractTest
  # TypeScript: npm run test:contract
  cd ../..
done
```

### 4.2 Integration Testing

Deploy the full platform to the staging overlay and execute end-to-end integration tests:

1. **Gateway → Identity mTLS handshake** — Verify SVID exchange and workload attestation
2. **Order → Payment → Catalog saga** — Execute a complete order lifecycle with payment processing and inventory reservation
3. **Order Outbox → Debezium → Kafka → Notification** — Verify CDC pipeline delivers order events to notification consumers
4. **Analytics → ClickHouse query** — Verify metric ingestion and query latency < 500ms p99
5. **RL Engine → Policy evaluation** — Verify reinforcement learning inference returns decisions within SLO

### 4.3 Security Validation

1. **Proprietary SDK scan** — Re-run `rg "boto3|aws-sdk|@google-cloud|@azure" services/` to confirm zero regressions
2. **NetworkPolicy validation** — Deploy a test pod that attempts unauthorized egress and confirm it's blocked
3. **SPIFFE/SPIRE attestation** — Verify all 9 services receive valid SVIDs within 30 seconds of pod startup
4. **ACL bypass attempt** — Attempt to call a cloud provider API directly from a service and confirm it fails

---

## Step 5: Chaos Engineering — Automated Programmatic Cloud Shift

### 5.1 Objective

Execute the automated programmatic cloud shift (migrating stateful data from AWS to a generic VPS) in under 4 hours, exactly as defined in the master specification. This validates the Technology-Neutral doctrine by proving that no proprietary cloud SDKs or services create migration barriers.

### 5.2 Pre-Chaos Prerequisites

| # | Prerequisite | Verification |
|---|-------------|-------------|
| 1 | All 9 services deploy successfully on generic VPS (no AWS/GCP/Azure dependencies) | `kubectl get pods -n production` shows all Running |
| 2 | PostgreSQL data export script ready | `pg_dump` produces complete backup |
| 3 | Kafka topic data export script ready | `kafka-console-consumer` with `--from-beginning` captures all events |
| 4 | ClickHouse data export script ready | `clickhouse-client --query "SELECT * FROM ... FORMAT Native"` |
| 5 | Terraform modules for generic VPS target | `infra/terraform/` modules exist and plan cleanly |
| 6 | ArgoCD application manifests parameterized for target cluster | `targetRevision` and `repoURL` are configurable |

### 5.3 Cloud Shift Execution Plan (4-Hour Timeline)

**T+0:00 — T+0:15: Pre-Migration Validation**
- Run full RED/USE metrics snapshot on source (AWS) deployment
- Verify all services are healthy and no error spikes exist
- Confirm data export scripts work against source databases
- Record baseline: p99 latencies, error rates, Kafka consumer lag

**T+0:15 — T+0:45: Infrastructure Provisioning on Target VPS**
```bash
# Provision target infrastructure via Terraform
cd infra/terraform/
terraform workspace select target-vps
terraform plan -out=tfplan
terraform apply tfplan

# Expected: VPC, Kubernetes cluster, node groups, managed PostgreSQL,
# object storage, DNS records provisioned in under 30 minutes
```

**T+0:45 — T+1:30: Data Migration (Stateful Components)**
```bash
# Step 1: PostgreSQL migration (Order, Payment, Catalog, Notification, Schema Registry)
pg_dump -h $SOURCE_PG_HOST -U postgres -Fc production > /tmp/production.pgdump
pg_restore -h $TARGET_PG_HOST -U postgres -d production /tmp/production.pgdump

# Step 2: Kafka topic replication
kafka-mirror-maker --consumer.config source.properties --producer.config target.properties \
  --whitelist "order-events,payment-events,notification-events,cdc-outbox-events"

# Step 3: ClickHouse migration (Analytics)
clickhouse-client --host $SOURCE_CH_HOST --query "BACKUP DATABASE analytics TO '/tmp/analytics.backup'"
# Transfer and restore on target

# Step 4: Schema Registry state
# Kafka-based (topics: schemas, schema-changes) — already replicated by mirror-maker
```

**T+1:30 — T+2:00: Application Deployment on Target**
```bash
# Update ArgoCD to deploy to target cluster
argocd login $TARGET_ARGOCD
argocd app sync polyglot-microservices --dest-server $TARGET_K8S_API

# Verify SPIRE attestation on target
kubectl get pods -n production -o wide  # All 9 services Running
kubectl logs -n production deploy/gateway | grep "SVID fetched"
```

**T+2:00 — T+2:30: Smoke Testing on Target**
```bash
# Run integration test suite against target
./scripts/integration-test.sh --target $TARGET_K8S_API

# Verify:
# - Gateway health check returns SERVING
# - Identity attestation works with target SPIRE
# - Order creation completes within SLO
# - Payment processing succeeds (Stripe sandbox)
# - Notification delivery works
# - Analytics queries return data
# - RL Engine inference returns decisions
```

**T+2:30 — T+3:00: Traffic Cutover (DNS-based)**
```bash
# Update DNS to point to target load balancer
# TTL should be set to 60s prior to migration

# Blue-green cutover:
# 1. Update A record: app.example.com → target LB IP
# 2. Wait for DNS propagation (60s TTL)
# 3. Monitor RED metrics on target for 15 minutes
# 4. If all green → migration complete
# 5. If errors spike → rollback DNS to source
```

**T+3:00 — T+3:30: Validation & Monitoring**
```bash
# Compare RED/USE metrics: source (pre-migration) vs target (post-migration)
# Acceptable variance: p99 latency within 20%, error rate < 0.5%

# Verify all Kafka consumers have caught up on target
kafka-consumer-groups --bootstrap-server $TARGET_KAFKA --describe --all-groups

# Verify SPIRE trust bundle is consistent across all workloads
kubectl get configmap spire-bundle -n production -o yaml
```

**T+3:30 — T+4:00: Rollback Preparation & Documentation**
- Keep source infrastructure running for 24h as rollback safety net
- Document migration duration, data consistency verification results, and any issues encountered
- Update runbook with lessons learned
- If all metrics green → schedule source infrastructure decommission at T+24h

### 5.4 Chaos Engineering Exercises (Post-Migration)

After successful cloud shift, execute targeted chaos experiments on the target deployment:

| Experiment | Target | Expected Behavior | Verification |
|-----------|--------|-------------------|-------------|
| **Kill SPIRE Server** | `spire-server-0` pod | SVID rotation continues via remaining replicas; no service disruption within 1h TTL | All services remain SERVING for 1h |
| **Kill Kafka Broker** | `kafka-1` pod | Debezium reconnects; consumers rebalance; no event loss (replication factor 3, min.insync=2) | Consumer lag returns to 0 within 60s |
| **Network Partition Payment → Stripe** | NetworkPolicy deny to 0.0.0.0/0:443 for payment pod | Circuit breaker opens after failure threshold; requests fail fast; saga compensation triggers | Order status transitions to COMPENSATING |
| **OOM Kill Analytics** | `kubectl exec analytics-0 -- kill -9 1` | Pod restarts; ClickHouse queries resume; no data loss | Pod restarts within 30s, queries resume |
| **DNS Outage** | Block port 53 egress from all pods | Service discovery fails; Gateway cannot route; graceful degradation | Gateway returns 503 for new requests; existing connections survive |

### 5.5 Success Criteria for Chaos Engineering

| Metric | Target | Measurement |
|--------|--------|-------------|
| Cloud shift total duration | < 4 hours | Wall clock from T+0:00 to T+4:00 |
| Data consistency verification | 100% row count match | Source vs target row counts for all tables |
| Zero proprietary SDK calls during migration | 0 detections | `rg` scan + OTel trace analysis |
| Post-migration p99 latency variance | < 20% from baseline | Grafana dashboard comparison |
| Post-migration error rate | < 0.5% | Prometheus query over 1h window |
| SPIRE attestation on target | All 9 services within 30s | OTel trace analysis |
| Kafka consumer lag post-cutover | < 100 events within 5 min | Kafka consumer group lag metric |
| Chaos experiment recovery | All services self-heal | No manual intervention required |

---

## Step 6: Phase 4 Gate Verification

| ID | Requirement | Verification Method | Target |
|----|-------------|-------------------|--------|
| 4.1 | Unit tests cover critical paths | Coverage > 80% for new code | `go test -cover`, `cargo tarpaulin`, `pytest --cov`, `./gradlew jacocoTestReport`, `nyc report` |
| 4.2 | Integration tests cover user flows | E2E scenarios pass on staging | `./scripts/integration-test.sh` exits 0 |
| 4.3 | /qa full pass with zero open P0/P1 bugs | QA report shows no critical issues | gstack /qa skill |
| 4.4 | /benchmark performance regression check | No regression from baseline | p99 within 20% of Phase 3 baseline |
| 4.5 | /cso security audit clean | No high/critical findings | gstack /cso skill |
| 4.6 | RED metrics dashboard operational | All 8 panels show live data | Grafana visual inspection |
| 4.7 | USE metrics dashboard operational | All 8 panels show live data | Grafana visual inspection |
| 4.8 | OTel Collector → Gateway → Backend pipeline active | Traces, metrics, logs flow end-to-end | Tempo query returns traces, Prometheus returns metrics, Loki returns logs |
| 4.9 | Cloud shift completed in < 4 hours | Migration timeline documented | Wall clock measurement |
| 4.10 | Chaos experiments: all services self-heal | No manual intervention | Experiment log shows automatic recovery |

---

## Step 7: Auto-Trigger Mapping for Phase 4

```
pre_execution → check_freeze → verify_phase_3_complete → verify_remediations_merged →
  → inject_context(execution) →
  → deploy_otel_backends → configure_grafana_dashboards → validate_telemetry_pipeline →
  → run_contract_tests → run_integration_tests → run_security_audit →
  → execute_cloud_shift → execute_chaos_experiments →
  → skill_invoke(/qa) → /benchmark → /cso →
  → post_execution → validate_output → update_worklog → update_reliability → cleanup
```

## Certified gstack Skills for Phase 4

- `/qa` — Full QA pass (find bugs, fix, re-verify)
- `/qa-only` — Report-only QA (no code changes)
- `/benchmark` — Performance regression detection
- `/benchmark-models` — Cross-model benchmark
- `/cso` — OWASP Top 10 + STRIDE security audit
- `/investigate` — Deep-dive debugging
- `/health` — Code quality dashboard

## Phase 4 → Phase 5 Transition

All 10 spec items (4.1-4.10) must PASS before Phase 5 (Ship & Deploy) begins. The cloud shift exercise and chaos engineering results serve as the ultimate validation of the Technology-Neutral doctrine — if the platform can migrate between cloud providers in under 4 hours without code changes, the core architectural principle is proven.
```
