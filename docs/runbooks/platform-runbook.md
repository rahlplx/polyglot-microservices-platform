# Platform Infrastructure Runbook

## Service Overview

This runbook covers the platform infrastructure components that support all 9 microservices: Kafka, Zookeeper, SPIRE Server, SPIRE Agent, Debezium CDC, OTel Collector, Prometheus, Grafana, Tempo, and Loki. These are the shared services that provide messaging, identity, observability, and data pipeline capabilities. Platform failures can affect all application services simultaneously.

**Key components:**
- **Kafka + Zookeeper:** Event streaming platform (3 brokers, replication factor 3)
- **SPIRE Server + Agent:** Identity and mTLS (3 server replicas, DaemonSet agents)
- **Debezium CDC:** Change Data Capture from PostgreSQL to Kafka
- **OTel Collector:** Observability pipeline (DaemonSet + Gateway)
- **Prometheus:** Metrics collection and alerting
- **Grafana:** Dashboards and visualization
- **Tempo:** Distributed tracing backend
- **Loki:** Log aggregation

## Architecture

```
[Application Services]
    |
    +-- Kafka (9092)     --> Event streaming
    +-- SPIRE (8081)     --> mTLS identity
    +-- OTel (4317/4318) --> Telemetry export
    +-- Schema Registry  --> Schema resolution
    |
[Platform Services]
    +-- Zookeeper (2181) --> Kafka coordination
    +-- Debezium         --> CDC from PostgreSQL
    +-- Prometheus       --> Metrics + alerts
    +-- Grafana          --> Dashboards
    +-- Tempo            --> Traces
    +-- Loki             --> Logs
```

## Health Checks

| Component | Endpoint | Expected | Notes |
|-----------|----------|----------|-------|
| Kafka | TCP :9092 | Connection OK | `kafka-broker-api-versions --bootstrap-server localhost:9092` |
| Zookeeper | HTTP :8080/commands/ruok | 200 OK | liveness + readiness |
| SPIRE Server | HTTP :8080/live | 200 OK | liveness |
| SPIRE Server | HTTP :8080/ready | 200 OK | readiness |
| Debezium | HTTP :8083/health | 200 OK | Connector health |
| OTel Collector | HTTP :13133/ | 200 OK | Health check extension |
| Prometheus | HTTP :9090/-/healthy | 200 OK | Self-health |
| Grafana | HTTP :3000/api/health | 200 OK | Self-health |

## Common Alerts

### KafkaUnderReplicatedPartitions
**Meaning:** Kafka has under-replicated partitions. Data loss risk if a broker fails.
**Investigation:**
1. Check broker health: `kubectl get pods -n production -l app.kubernetes.io/name=kafka`
2. Check under-replicated partitions: `kafka-topics --describe --under-replicated-partitions --bootstrap-server localhost:9092`
3. Check disk usage on each broker pod
4. Verify network connectivity between brokers
5. Restart failed broker if necessary

### KafkaConsumerLag
**Meaning:** Consumer groups cannot keep up with production rate.
**Investigation:**
1. Identify the affected consumer group
2. Check consumer pod health and resource utilization
3. Scale consumer replicas if CPU is high
4. Check for processing errors in consumer logs
5. Consider increasing partition count for the topic

### SPIREServerUnhealthy
**Meaning:** SPIRE Server healthz is failing. SVID issuance is blocked.
**Investigation:**
1. Check SPIRE Server pods: `kubectl get pods -n production -l app.kubernetes.io/name=spire-server`
2. Check server logs: `kubectl logs -n production -l app.kubernetes.io/name=spire-server`
3. Verify SQLite data volume is not full
4. Check ConfigMap for misconfiguration
5. If server is crash-looping, check recent ConfigMap changes

### CertificateExpiry
**Meaning:** SVID expiring within 24 hours. Rotation should handle this automatically.
**Investigation:**
1. Identify affected workload
2. Check SPIRE Agent on the node
3. Restart affected pod if rotation is stuck
4. Run mTLS verification: `./scripts/mtls-verify.sh`

### CDCPipelineLag
**Meaning:** CDC pipeline lag exceeds 30 seconds. Analytics data is stale.
**Investigation:**
1. Check Debezium connector status: `curl http://debezium:8083/connectors`
2. Check connector health: `curl http://debezium:8083/connectors/<name>/status`
3. Check PostgreSQL replication slot: `SELECT * FROM pg_replication_slots`
4. Check Kafka producer throughput
5. Restart Debezium connector if stuck: `curl -X DELETE http://debezium:8083/connectors/<name> && curl -X POST http://debezium:8083/connectors -d @<config>`

### DiskUsageHigh
**Meaning:** PVC usage exceeds 80%. Risk of volume filling up.
**Investigation:**
1. Identify which PVC: `kubectl get pvc -n production`
2. Check usage: `kubectl exec -n production <pod> -- df -h /var/lib/<component>/data`
3. Expand PVC if needed: Edit the PVC storage request
4. Implement data retention or rotation if appropriate

## Troubleshooting Steps

### Kafka broker down
1. Check pod events: `kubectl describe pod kafka-0 -n production`
2. Check disk usage on the PVC: `kubectl exec kafka-0 -n production -- df -h /var/lib/kafka/data`
3. If OOMKilled, increase memory limits
4. If disk full, increase PVC size or clean up old log segments
5. Wait for partition reassignment to complete after broker recovery

### Zookeeper quorum lost
1. Check all 3 ZK pods: `kubectl get pods -n production -l app.kubernetes.io/name=zookeeper`
2. If 2+ pods are down, Kafka may be impacted
3. Restart ZK pods one at a time, waiting for each to become ready
4. Verify leader election: `kubectl exec zookeeper-0 -n production -- echo ruok | nc localhost 8080`
5. After ZK quorum restores, verify Kafka ISR counts

### SPIRE cluster failure
1. Check SPIRE Server StatefulSet: `kubectl get statefulset spire-server -n production`
2. If all servers are down, scale to 1 and wait for bootstrap
3. Verify the bundle ConfigMap: `kubectl get configmap spire-bundle -n production`
4. Re-register workload entries if needed
5. Scale back to 3 replicas

### OTel Collector not receiving telemetry
1. Check collector pods: `kubectl get pods -n production -l app.kubernetes.io/name=otel-collector`
2. Check collector config: `kubectl get configmap otel-collector -n production -o yaml`
3. Verify application exporters are pointing to the correct endpoint
4. Check for sampling configuration issues
5. Verify Tempo is receiving traces and Loki is receiving logs

### Prometheus not scraping targets
1. Check Prometheus targets: `curl http://prometheus:9090/api/v1/targets`
2. Verify ServiceMonitor/PodMonitor resources are deployed
3. Check NetworkPolicy allows Prometheus to reach scrape targets
4. Check for RBAC issues preventing discovery

## Scaling Considerations

### Kafka
- **StatefulSet:** 3 brokers with PVCs — cannot auto-scale
- **Horizontal:** Add more brokers (requires partition reassignment)
- **Vertical:** Increase CPU/memory limits on broker pods
- **Disk:** Monitor PVC usage and expand proactively

### SPIRE Server
- **StatefulSet:** 3 replicas — cannot auto-scale
- **PDB:** minAvailable: 2 ensures quorum during maintenance
- **Vertical:** Increase CPU/memory if attestation load grows

### OTel Collector
- **DaemonSet:** One per node — scales with cluster size
- **Gateway:** 2 replicas — can be scaled manually or with HPA
- **PDB:** minAvailable: 1 ensures at least one collector running

## Dependencies

### Upstream
- All application services (produce/consume Kafka, export OTel, request SVIDs)

### Downstream
- PostgreSQL (Debezium source)
- External NTP (certificate time validation)

### Infrastructure
- Kubernetes API (pod discovery, service discovery)
- Node storage (PVCs for Kafka, ZK, SPIRE data)
- Network (inter-broker, inter-ZK, SPIRE gRPC)

## Deployment

### How to Deploy Platform Components
1. Platform components are deployed via ArgoCD App-of-Apps
2. Each component has its own Application manifest in `infra/kubernetes/apps/`
3. Changes to platform manifests are auto-synced by ArgoCD
4. StatefulSets (Kafka, ZK, SPIRE) use Parallel pod management for faster rollout

### Rollback Procedure
1. For StatefulSets, rollback is more complex due to persistent state
2. Kafka: Verify ISR counts before and after rollback
3. SPIRE: Ensure bundle ConfigMap is consistent
4. OTel: Rolling restart is safe (stateless)
5. Use `argocd app rollback <app-name> <revision>` for ArgoCD-managed rollback

### Emergency: Kafka Cluster Recovery
```bash
# If Kafka cluster is completely down
# 1. Check ZK quorum first
kubectl get pods -n production -l app.kubernetes.io/name=zookeeper

# 2. If ZK is healthy, restart Kafka brokers one at a time
kubectl delete pod kafka-0 -n production
# Wait for kafka-0 to be ready
kubectl delete pod kafka-1 -n production
# Wait for kafka-1 to be ready
kubectl delete pod kafka-2 -n production

# 3. Verify ISR counts
kubectl exec kafka-0 -n production -- kafka-topics --describe --bootstrap-server localhost:9092
```

## On-Call Escalation

| Severity | Response Time | Contact | Channel |
|----------|---------------|---------|---------|
| SEV1 (Kafka/SPIRE down) | 5 minutes | Platform On-Call | PagerDuty #platform |
| SEV2 (CDC/OTel pipeline broken) | 15 minutes | Platform On-Call | PagerDuty #platform |
| SEV3 (Observability gaps) | 1 hour | Platform Engineer | Slack #platform-alerts |
| SEV4 (Minor issues) | 8 hours | Platform Engineer | Slack #platform |

**Escalation path:** On-Call Engineer → Platform Lead → VP Engineering → CTO (if platform-wide outage)

**Note:** Platform services are shared infrastructure. A Kafka or SPIRE outage affects ALL application services. These are the highest-priority alerts in the system.
