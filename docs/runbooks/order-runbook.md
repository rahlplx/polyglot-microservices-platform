# Order Service Runbook

## Service Overview

The Order service manages the full order lifecycle for the polyglot microservices platform, implemented in **Kotlin** (JVM). It orchestrates complex multi-step sagas spanning catalog inventory reservation, payment processing, and notification delivery. The service uses the outbox pattern for reliable event publishing and Resilience4j for circuit breakers, retries, and timeouts. It is the most critical business service as it coordinates the entire order flow.

**Key characteristics:**
- Language: Kotlin (JVM)
- Protocol: gRPC (port 50053)
- SLO: 99.95% availability, p99 latency < 1s
- Replicas: 2-8 (HPA, CPU target 70%)
- Resource budget: CPU 500m/2000m, Memory 512Mi/2Gi

**Dependencies:**
- PostgreSQL (order data, outbox table)
- Kafka (order events, saga events)
- Catalog service (inventory reservation)
- Payment service (payment processing)
- Notification service (order confirmation)
- OTel Collector (telemetry)
- SPIRE Agent (mTLS SVID)

## Architecture

```
Gateway
    |
    v
[Order :9090]
    |
    +-- Saga Orchestrator --> CreateOrder saga
    |   +-- Step 1: ReserveInventory (Catalog)
    |   +-- Step 2: ProcessPayment (Payment)
    |   +-- Step 3: SendNotification (Notification)
    |   +-- Compensating actions on failure
    +-- PostgreSQL --> Orders, OrderLines, Outbox
    +-- Kafka --> OrderCreated, OrderCompleted, OrderCancelled
    +-- Resilience4j --> Circuit breakers + Retries
    +-- OTel --> Traces/Metrics
    +-- SPIRE --> mTLS SVID rotation
```

- gRPC port: 50053 (internal)
- HTTP health port: 8080
- Saga pattern: Orchestration-based saga with compensating transactions
- Resilience: Circuit breakers on all downstream calls, retry with exponential backoff

## Health Checks

| Endpoint | Method | Expected Response | Notes |
|----------|--------|-------------------|-------|
| `/healthz` | GET | 200 OK | Liveness + readiness |
| `:50053` | gRPC reflection | ListServices response | gRPC health |

**K8s probes:**
- Liveness: HTTP GET `/healthz` on port `http`, initialDelay 15s, period 20s
- Readiness: HTTP GET `/healthz` on port `http`, initialDelay 5s, period 10s

## Common Alerts

### HighLatency (order)
**Meaning:** p99 latency exceeds 2s. Orders are taking too long to process.
**Investigation:**
1. Check if saga steps are slow (Catalog, Payment, or Notification)
2. Examine distributed traces in Tempo for bottleneck span
3. Check PostgreSQL query performance (saga state queries)
4. Check JVM GC pauses: `jvm_gc_pause_seconds{job="order"}`

### CircuitBreakerOpen (order -> payment/catalog)
**Meaning:** Circuit breaker to a downstream service is open. Orders cannot complete.
**Investigation:**
1. Identify which downstream service is failing
2. Check that service's health and error rate
3. Review saga compensation — partial orders may need manual reconciliation
4. Check if orders are being created but stuck in PENDING state

### KafkaConsumerLag (order)
**Meaning:** Order consumer lag exceeds 1000. Events are piling up.
**Investigation:**
1. Check consumer pod health
2. Check Kafka broker health
3. Look for slow processing or deserialization errors
4. Consider scaling consumer replicas

## Troubleshooting Steps

### Orders stuck in PENDING state
1. Check saga state in PostgreSQL: `SELECT * FROM saga_instances WHERE status = 'PENDING'`
2. Check downstream service availability (Catalog, Payment)
3. Review order service logs for saga step failures
4. Check circuit breaker metrics for open circuits
5. If downstream recovered, sagas should auto-retry on the next attempt cycle

### Saga compensation failures
1. Check compensation action logs: `kubectl logs -n production -l app.kubernetes.io/name=order | grep -i compensation`
2. Verify inventory was released (check Catalog service)
3. Verify payment was refunded (check Payment service)
4. If compensation partially failed, may need manual reconciliation via admin API

### JVM OutOfMemoryError
1. Check heap usage: `kubectl exec -n production <pod> -- jcmd 1 GC.heap_info`
2. Increase memory limits in deployment manifest
3. Review JVM heap settings (-Xms/-Xmx) in container args
4. Check for memory leaks in saga orchestrator (long-running sagas)

## Scaling Considerations

- **HPA:** Configured for 2-8 replicas, CPU target 70%
- **JVM warmup:** New pods may have higher latency for the first 30-60 seconds (JIT compilation)
- **PDB:** maxUnavailable: 1 — ensures continuous order processing
- **Database connections:** Monitor HikariCP pool utilization
- **Saga state lock:** Ensure saga instances are not contending on the same orders

## Dependencies

### Upstream
- Gateway (direct order queries and creation)

### Downstream (saga participants)
- Catalog service (inventory reservation/release)
- Payment service (payment processing/refund)
- Notification service (order confirmation)
- PostgreSQL (order and saga state)
- Kafka (event publishing)

### Platform dependencies
- OTel Collector (telemetry)
- SPIRE Agent (mTLS SVID)
- Schema Registry (event schemas)

## Deployment

### How to Deploy
1. Merge PR to `main` — ArgoCD auto-sync applies
2. JVM services need careful rollout — monitor for warmup latency
3. Check saga state consistency during rollout
4. Monitor error rate for 15 minutes post-deployment

### Rollback Procedure
1. Rollback: `kubectl rollout undo deployment/order -n production`
2. Check for in-flight sagas — they may need reconciliation
3. Verify saga state table for partially completed sagas
4. Run reconciliation job if needed: `kubectl create job --from=cronjob/saga-reconciler manual-reconcile -n production`

### Emergency: Drain Order Queue
```bash
# Scale up to handle backlog
kubectl scale deployment order -n production --replicas=8

# Monitor queue depth
kubectl exec -n production <kafka-pod> -- kafka-consumer-groups --bootstrap-server localhost:9092 --describe --group order-consumer
```

## On-Call Escalation

| Severity | Response Time | Contact | Channel |
|----------|---------------|---------|---------|
| SEV1 (Orders not processing) | 5 minutes | Order On-Call | PagerDuty #order |
| SEV2 (High failure rate >10%) | 10 minutes | Order On-Call | PagerDuty #order |
| SEV3 (Slow processing >5s) | 30 minutes | Order Engineer | Slack #order-alerts |
| SEV4 (Minor issues) | 4 hours | Order Engineer | Slack #order |

**Escalation path:** On-Call Engineer → Order Lead → VP Engineering → CTO (if revenue impact)
