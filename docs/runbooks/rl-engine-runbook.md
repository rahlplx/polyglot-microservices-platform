# RL Engine Runbook

## Service Overview

The RL (Reinforcement Learning) Engine provides adaptive policy management for the polyglot microservices platform, implemented in **Python**. It uses reinforcement learning to dynamically adjust circuit breaker thresholds, rate limiting parameters, and routing weights based on real-time system behavior. The engine maintains a knowledge base of system state and historical outcomes, training policies that are deployed to the gateway and services. It is an offline/async service — policy updates are not on the critical request path.

**Key characteristics:**
- Language: Python
- Protocol: gRPC (port 50060) + HTTP REST (port 8080)
- SLO: 99.5% availability, p99 latency < 500ms (policy queries)
- Replicas: 2-4 (HPA, CPU target 80%)
- Resource budget: CPU 200m/1000m, Memory 256Mi/1Gi

**Dependencies:**
- PostgreSQL (knowledge base, policy storage)
- Kafka (CDC events for knowledge base updates)
- OTel Collector (telemetry metrics for policy training)
- SPIRE Agent (mTLS SVID)

## Architecture

```
Gateway (rate limit queries)
    |
    v
[RL Engine :9090]
    |
    +-- gRPC --> CheckRateLimit, GetActivePolicies, UpdatePolicy
    +-- REST  --> /api/v1/policies, /api/v1/rate-limits
    +-- PostgreSQL --> Knowledge base, Policies, Training data
    +-- Kafka --> CDC events (system state observations)
    +-- OTel  --> Metrics collection for training
    +-- SPIRE --> mTLS SVID rotation
```

- gRPC port: 50060 (internal policy queries)
- HTTP port: 8080 (REST API + health)
- Knowledge base: PostgreSQL-backed, updated via CDC pipeline
- Policy training: Batch training on accumulated observations
- Policy deployment: Policies pushed to gateway and services on update

## Health Checks

| Endpoint | Method | Expected Response | Notes |
|----------|--------|-------------------|-------|
| `/healthz` | GET | 200 OK | Liveness + readiness |
| `:50060` | gRPC reflection | ListServices response | gRPC health |

**K8s probes:**
- Liveness: HTTP GET `/healthz` on port `http`, initialDelay 15s, period 20s
- Readiness: HTTP GET `/healthz` on port `http`, initialDelay 5s, period 10s

## Common Alerts

### RLKnowledgeBaseStale
**Meaning:** Knowledge base has not been updated in 30 days. RL policies may be based on outdated system behavior.
**Investigation:**
1. Check CDC pipeline health (is data flowing from Debezium?)
2. Check Kafka consumer group for rl-engine
3. Verify PostgreSQL knowledge base tables have recent entries
4. Check rl-engine logs for ingestion errors

### HighLatency (rl-engine)
**Meaning:** Policy queries are slow. Rate limiting decisions at the gateway are delayed.
**Investigation:**
1. Check PostgreSQL query performance for policy lookups
2. Review knowledge base size (may need pruning)
3. Check if training job is consuming too many resources
4. Consider caching active policies in memory

### HighErrorRate (rl-engine)
**Meaning:** Policy query error rate exceeds 5%.
**Investigation:**
1. Check PostgreSQL connectivity
2. Review policy serialization errors
3. Check for schema mismatch between stored policies and query format
4. Verify knowledge base integrity

## Troubleshooting Steps

### Knowledge base not receiving updates
1. Check Kafka consumer lag for rl-engine consumer group
2. Check Debezium connector status for CDC pipeline
3. Verify the CDC relay is publishing to the correct Kafka topics
4. Check if schema evolution has broken deserialization

### RL policies producing poor results
1. Review recent policy changes in PostgreSQL policies table
2. Check if training data distribution has shifted (concept drift)
3. Consider resetting to default policy: `curl -X POST http://rl-engine:8080/api/v1/policies/reset`
4. Review circuit breaker and rate limiting metrics for anomalies

### Rate limit check timeouts at gateway
1. Check rl-engine pod health and resource utilization
2. Check gRPC response times: `histogram_quantile(0.99, rate(grpc_server_handling_seconds_bucket{job="rl-engine"}[5m]))`
3. Consider increasing rl-engine replicas
4. Gateway should fall back to static rate limits if rl-engine is unavailable

## Scaling Considerations

- **HPA:** Configured for 2-4 replicas, CPU target 80%
- **Compute-intensive:** Training jobs consume significant CPU
- **Training isolation:** Consider running training as a separate Job rather than inline
- **PDB:** maxUnavailable: 1
- **Knowledge base:** May need periodic pruning to maintain query performance

## Dependencies

### Upstream
- Gateway (rate limit checks)
- Analytics (policy evaluation queries)

### Downstream
- PostgreSQL (knowledge base, policies)
- Kafka (CDC event consumer)

### Platform dependencies
- OTel Collector (telemetry + training data)
- SPIRE Agent (mTLS SVID)
- Schema Registry (CDC event schema)

## Deployment

### How to Deploy
1. Merge PR to `main` — ArgoCD auto-sync applies
2. Python restart is fast
3. Active policies are loaded from PostgreSQL on startup (brief cold-start latency)
4. Monitor policy query latency post-deployment

### Rollback Procedure
1. `kubectl rollout undo deployment/rl-engine -n production`
2. Verify active policies are reloaded correctly
3. Check gateway rate limiting is functioning
4. If policy state is corrupted, reset to default policies

### Emergency: Fallback to Static Rate Limits
```bash
# If rl-engine is causing gateway issues, the gateway should automatically
# fall back to static rate limits. Verify this behavior:
kubectl logs -n production -l app.kubernetes.io/name=gateway | grep -i "rate.limit.fallback"

# If not falling back, restart gateway to clear cached rl-engine connections
kubectl rollout restart deployment/gateway -n production
```

## On-Call Escalation

| Severity | Response Time | Contact | Channel |
|----------|---------------|---------|---------|
| SEV1 (RL Engine down, gateway impacted) | 15 minutes | ML/Platform On-Call | PagerDuty #platform |
| SEV2 (Knowledge base stale >7 days) | 4 hours | ML Engineer | Slack #ml-alerts |
| SEV3 (Policy quality degraded) | 24 hours | ML Engineer | Slack #ml-alerts |
| SEV4 (Minor issues) | 48 hours | ML Engineer | Slack #ml |

**Escalation path:** On-Call Engineer → ML Lead → Platform Lead → VP Engineering

**Note:** RL Engine is a best-effort optimization service. If it fails, the gateway falls back to static rate limits. This is acceptable but suboptimal.
