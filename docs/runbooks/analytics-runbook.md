# Analytics Service Runbook

## Service Overview

The Analytics service provides real-time data analytics and reporting for the polyglot microservices platform, implemented in **Python**. It consumes events from Kafka (via CDC pipeline), aggregates metrics, generates reports, and serves dashboards. The service writes to both PostgreSQL (relational data) and ClickHouse (time-series/OLAP queries). It supports gRPC for internal queries and REST for dashboard rendering.

**Key characteristics:**
- Language: Python
- Protocol: gRPC (port 50057) + HTTP REST (port 8080)
- SLO: 99.5% availability, p99 latency < 2s (aggregation queries can be slow)
- Replicas: 2-6 (HPA, CPU target 80%)
- Resource budget: CPU 500m/2000m, Memory 1Gi/4Gi

**Dependencies:**
- PostgreSQL (relational analytics data)
- ClickHouse (OLAP time-series queries)
- Kafka (CDC event consumer)
- OTel Collector (telemetry)
- SPIRE Agent (mTLS SVID)

## Architecture

```
Kafka (CDC events from Debezium)
    |
    v
[Analytics :9090]
    |
    +-- gRPC --> GetReport, GetMetrics, StreamAggregations
    +-- REST  --> /api/v1/analytics/reports, /api/v1/metrics
    +-- PostgreSQL --> Aggregations, Reports
    +-- ClickHouse --> Time-series metrics (OLAP)
    +-- OTel  --> Traces/Metrics
    +-- SPIRE --> mTLS SVID rotation
```

- gRPC port: 50057 (internal queries)
- HTTP port: 8080 (REST API + health)
- Data pipeline: Kafka CDC events -> Aggregation service -> PostgreSQL + ClickHouse
- Report generation: Scheduled and on-demand report generation with configurable output formats

## Health Checks

| Endpoint | Method | Expected Response | Notes |
|----------|--------|-------------------|-------|
| `/healthz` | GET | 200 OK | Liveness + readiness |
| `:50057` | gRPC reflection | ListServices response | gRPC health |

**K8s probes:**
- Liveness: HTTP GET `/healthz` on port `http`, initialDelay 15s, period 20s
- Readiness: HTTP GET `/healthz` on port `http`, initialDelay 5s, period 10s

## Common Alerts

### CDCPipelineLag (analytics)
**Meaning:** CDC events are lagging more than 30 seconds. Analytics data is stale.
**Investigation:**
1. Check Debezium connector status
2. Check Kafka consumer lag for analytics consumer group
3. Check ClickHouse insert performance
4. Consider scaling analytics replicas if processing is the bottleneck

### HighLatency (analytics)
**Meaning:** p99 latency exceeds 2s. Report and metric queries are slow.
**Investigation:**
1. Check ClickHouse query performance (may need materialized views)
2. Check PostgreSQL query performance (aggregation queries)
3. Review report generation complexity (large date ranges)
4. Check if data volume has exceeded current capacity

### HighErrorRate (analytics)
**Meaning:** Error rate exceeds 5%.
**Investigation:**
1. Check ClickHouse connectivity
2. Check PostgreSQL connectivity
3. Check Kafka consumer deserialization errors
4. Review schema compatibility (CDC schema evolution)

## Troubleshooting Steps

### Analytics data is stale
1. Check CDC pipeline health: `./scripts/mtls-verify.sh --skip-live` (Debezium section)
2. Check Kafka topic for recent events: `kafka-console-consumer --topic cdc.public.orders --from-beginning --max-messages 1`
3. Check analytics consumer group lag
4. If Debezium is down, restart and verify offset positions
5. If data is corrupted, re-seed from PostgreSQL snapshot

### ClickHouse query timeout
1. Check ClickHouse server status: `curl http://clickhouse:8123/ping`
2. Review slow query log in ClickHouse
3. Check if materialized views need refresh
4. Consider optimizing query with better indexes or partitioning
5. Scale ClickHouse resources if consistently slow

### Report generation failures
1. Check report template rendering errors
2. Verify output format support (PDF, CSV, JSON)
3. Check storage for report artifacts
4. Review report generation logs for stack traces

## Scaling Considerations

- **HPA:** Configured for 2-6 replicas, CPU target 80%
- **CPU-intensive:** Aggregation queries consume significant CPU
- **Memory-intensive:** Large dataset processing requires adequate memory
- **PDB:** maxUnavailable: 1
- **ClickHouse scaling:** Separate from analytics pods — scale ClickHouse cluster independently

## Dependencies

### Upstream
- Gateway (analytics queries)
- Kafka (CDC event consumer)

### Downstream
- PostgreSQL (relational analytics)
- ClickHouse (OLAP time-series on port 8123/9000)

### Platform dependencies
- OTel Collector (telemetry)
- SPIRE Agent (mTLS SVID)
- Schema Registry (CDC event schema)

## Deployment

### How to Deploy
1. Merge PR to `main` — ArgoCD auto-sync applies
2. Python restart is fast
3. Monitor CDC consumer rebalancing
4. Verify report generation post-deployment

### Rollback Procedure
1. `kubectl rollout undo deployment/analytics -n production`
2. Verify CDC consumer resumes from correct offset
3. Check for data gaps during downtime
4. If data gap exists, trigger backfill from PostgreSQL

## On-Call Escalation

| Severity | Response Time | Contact | Channel |
|----------|---------------|---------|---------|
| SEV1 (Analytics fully down) | 15 minutes | Analytics On-Call | PagerDuty #analytics |
| SEV2 (Data staleness >5min) | 30 minutes | Analytics On-Call | PagerDuty #analytics |
| SEV3 (Slow queries >10s) | 2 hours | Analytics Engineer | Slack #analytics-alerts |
| SEV4 (Minor issues) | 8 hours | Analytics Engineer | Slack #analytics |

**Escalation path:** On-Call Engineer → Analytics Lead → VP Engineering

**Note:** Analytics is not on the critical order path. Stale data is acceptable for brief periods. SEV1 response is 15 minutes, not 5.
