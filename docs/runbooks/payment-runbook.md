# Payment Service Runbook

## Service Overview

The Payment service handles payment processing for the polyglot microservices platform, implemented in **Go**. It processes payment transactions, manages payment method validation, and integrates with external payment gateways through an ACL sidecar. The service implements circuit breakers for external gateway calls and uses the outbox pattern for reliable event publishing via Kafka. It is a critical-path service in the order saga workflow.

**Key characteristics:**
- Language: Go
- Protocol: gRPC (port 50054)
- SLO: 99.95% availability, p99 latency < 500ms
- Replicas: 2-6 (HPA, CPU target 70%)
- Resource budget: CPU 200m/1000m, Memory 256Mi/1Gi

**Dependencies:**
- PostgreSQL (transaction data, outbox table)
- Kafka (payment events)
- External payment gateway (via ACL sidecar)
- OTel Collector (telemetry)
- SPIRE Agent (mTLS SVID)

## Architecture

```
Order Service (saga step)
    |
    v
[Payment :9090]
    |
    +-- gRPC       --> ProcessPayment, RefundPayment, GetTransaction
    +-- PostgreSQL  --> Transactions, Outbox table
    +-- Kafka       --> PaymentProcessed, PaymentFailed events
    +-- ACL Sidecar --> External payment gateway (HTTPS :443)
    +-- OTel        --> Traces/Metrics
    +-- SPIRE       --> mTLS SVID rotation
```

- gRPC port: 50054 (internal)
- HTTP health port: 8080
- Circuit breaker: Resilience4j for external gateway calls
- Outbox pattern: Writes to outbox table, Debezium captures and publishes to Kafka

## Health Checks

| Endpoint | Method | Expected Response | Notes |
|----------|--------|-------------------|-------|
| `/healthz` | GET | 200 OK | Liveness + readiness |
| `:50054` | gRPC reflection | ListServices response | gRPC health |

**K8s probes:**
- Liveness: HTTP GET `/healthz` on port `http`, initialDelay 15s, period 20s
- Readiness: HTTP GET `/healthz` on port `http`, initialDelay 5s, period 10s

## Common Alerts

### CircuitBreakerOpen (payment)
**Meaning:** Circuit breaker to external payment gateway is open. All payment processing is failing fast.
**Investigation:**
1. Check external gateway status (may be down or rate-limiting)
2. Review circuit breaker metrics: `resilience4j_circuitbreaker_state{job="payment"}`
3. Check recent error rates: `rate(http_requests_total{job="payment",code=~"5.."}[5m])`
4. Verify ACL sidecar is not blocking legitimate calls

### HighErrorRate (payment)
**Meaning:** Payment error rate exceeds 5%. Transactions are failing.
**Investigation:**
1. Check PostgreSQL connectivity: `kubectl exec -n production <pod> -- pg_isready`
2. Check Kafka producer errors in logs
3. Check external gateway error responses
4. Verify outbox table is not growing unbounded (Debezium may be lagging)

### HighLatency (payment)
**Meaning:** p99 latency exceeds 2s. Payment processing is slow.
**Investigation:**
1. Check external gateway response times
2. Check PostgreSQL query performance (slow queries on transactions table)
3. Check Kafka produce latency
4. Review circuit breaker half-open state (may be in retry storm)

## Troubleshooting Steps

### Payments failing with "gateway timeout"
1. Check external payment gateway health (may require external status page)
2. Check ACL sidecar logs: `kubectl logs -n production <pod> -c acl-sidecar`
3. Check NetworkPolicy allows egress to external gateway on port 443
4. Verify DNS resolution for external gateway hostname
5. If persistent, consider enabling maintenance mode to fail fast

### Outbox table growing (CDC lag)
1. Check Debezium connector status: `kubectl get pods -n production -l app.kubernetes.io/name=cdc-relay`
2. Check Kafka topic for payment events: `kafka-consumer-groups --describe --group payment-consumer`
3. Check Debezium lag metrics: `debezium_source_lag_seconds{connector="payment"}`
4. If Debezium is down, restart the connector after checking offset positions

### Payment double-processing
1. Check idempotency key handling in payment processing logic
2. Review Kafka consumer offsets for duplicate deliveries
3. Check outbox table for duplicate entries
4. Verify saga compensation is correctly handling duplicate payment events

## Scaling Considerations

- **HPA:** Configured for 2-6 replicas, CPU target 70%
- **Conservative scale-down:** 10-minute cooldown to avoid premature scaling during payment bursts
- **PDB:** maxUnavailable: 1 — ensures continuous payment processing during updates
- **Database connection pool:** Monitor for connection exhaustion; scale vertically if needed
- **External gateway rate limits:** Check with payment provider for rate limit increases

## Dependencies

### Upstream
- Order service (saga orchestration)
- Gateway (direct payment queries)

### Downstream
- PostgreSQL (transaction storage)
- Kafka (event publishing)
- External payment gateway (via ACL sidecar on port 443)

### Platform dependencies
- OTel Collector (telemetry)
- SPIRE Agent (mTLS SVID)
- Schema Registry (Avro schema for events)

## Deployment

### How to Deploy
1. Merge PR to `main` — ArgoCD auto-sync applies to production
2. Monitor rollout: `kubectl rollout status deployment/payment -n production`
3. Verify no payment errors: Check Grafana dashboard for error rate
4. Verify outbox processing continues: Check Debezium lag

### Rollback Procedure
1. Identify last working revision: `kubectl rollout history deployment/payment -n production`
2. Rollback: `kubectl rollout undo deployment/payment -n production --to-revision=<N>`
3. If payments are stuck, check outbox table for unprocessed entries
4. Verify Kafka consumer offsets are correct after rollback

### Emergency: Disable Payment Processing
```bash
# Scale to 0 to stop accepting new payments
kubectl scale deployment payment -n production --replicas=0

# Note: This will block the order saga. Consider returning "service unavailable"
# instead of scaling to 0 by enabling maintenance mode in config.
```

## On-Call Escalation

| Severity | Response Time | Contact | Channel |
|----------|---------------|---------|---------|
| SEV1 (All payments failing) | 5 minutes | Payment On-Call | PagerDuty #payment |
| SEV2 (High failure rate >10%) | 10 minutes | Payment On-Call | PagerDuty #payment |
| SEV3 (Slow processing >5s) | 30 minutes | Payment Engineer | Slack #payment-alerts |
| SEV4 (Minor issues) | 4 hours | Payment Engineer | Slack #payment |

**Escalation path:** On-Call Engineer → Payment Lead → VP Engineering → CFO (if financial impact)
