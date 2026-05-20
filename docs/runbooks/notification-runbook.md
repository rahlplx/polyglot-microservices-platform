# Notification Service Runbook

## Service Overview

The Notification service handles multi-channel notification delivery for the polyglot microservices platform, implemented in **Python**. It consumes CloudEvents from Kafka (order confirmations, payment receipts, shipping updates) and delivers them through email, SMS, push, and webhook channels. The service manages delivery preferences, templates, and tracking. It is an asynchronous service that does not block the critical order path — notification failures should not prevent order completion.

**Key characteristics:**
- Language: Python
- Protocol: gRPC (port 50056) + Kafka consumer
- SLO: 99.5% availability, p99 latency < 500ms (internal), best-effort delivery
- Replicas: 2-4 (HPA, CPU target 75%)
- Resource budget: CPU 100m/500m, Memory 256Mi/512Mi

**Dependencies:**
- PostgreSQL (notification log, preferences, templates)
- Kafka (CloudEvents consumer)
- External channel providers (email SMTP, SMS API, push service, webhook endpoints)
- OTel Collector (telemetry)
- SPIRE Agent (mTLS SVID)

## Architecture

```
Kafka (order.events, payment.events)
    |
    v
[Notification :9090]
    |
    +-- Kafka Consumer --> CloudEvents processor
    +-- gRPC --> SendNotification, GetNotificationPreferences
    +-- Channel Senders:
    |   +-- Email (SMTP :587)
    |   +-- SMS (HTTPS API)
    |   +-- Push (HTTPS API)
    |   +-- Webhook (HTTPS :443)
    +-- PostgreSQL --> Notifications, Preferences, Templates
    +-- OTel  --> Traces/Metrics
    +-- SPIRE --> mTLS SVID rotation
```

- gRPC port: 50056 (internal — direct notification requests)
- Kafka consumer: Subscribes to order and payment event topics
- Channel delivery: Async with retry and delivery tracking
- Template engine: Jinja2-based template rendering with i18n support

## Health Checks

| Endpoint | Method | Expected Response | Notes |
|----------|--------|-------------------|-------|
| `/healthz` | GET | 200 OK | Liveness + readiness |
| `:50056` | gRPC reflection | ListServices response | gRPC health |

**K8s probes:**
- Liveness: HTTP GET `/healthz` on port `http`, initialDelay 15s, period 20s
- Readiness: HTTP GET `/healthz` on port `http`, initialDelay 5s, period 10s

## Common Alerts

### KafkaConsumerLag (notification)
**Meaning:** Notification consumer lag exceeds 1000. Notifications are delayed.
**Investigation:**
1. Check consumer pod health and resource utilization
2. Check Kafka broker health
3. Look for processing errors (external channel failures)
4. Consider scaling consumer replicas

### HighErrorRate (notification)
**Meaning:** Notification delivery failure rate exceeds 5%.
**Investigation:**
1. Identify which channel is failing (email, SMS, push, webhook)
2. Check external provider status
3. Review NetworkPolicy for egress to external providers
4. Check for rate limiting by external providers

### CircuitBreakerOpen (notification -> email/sms)
**Meaning:** Circuit breaker to an external channel provider is open.
**Investigation:**
1. Check external provider status page
2. Review API rate limits and quotas
3. Check for authentication token expiration
4. Notifications will queue and retry when circuit closes

## Troubleshooting Steps

### Notifications not being delivered
1. Check Kafka consumer is running: `kubectl get pods -n production -l app.kubernetes.io/name=notification`
2. Check consumer lag: `kafka-consumer-groups --describe --group notification-consumer`
3. Check notification log in PostgreSQL: `SELECT * FROM notifications WHERE status = 'FAILED' ORDER BY created_at DESC LIMIT 20`
4. Check channel sender logs for error details

### Email delivery failures
1. Check SMTP connectivity from pod: `kubectl exec -n production <pod> -- python3 -c "import smtplib; smtplib.SMTP('smtp.example.com', 587)"`
2. Verify SMTP credentials are valid (check SecretKeyRef)
3. Check if external SMTP provider is rate-limiting
4. Review email template rendering errors

### Template rendering errors
1. Check template syntax in PostgreSQL templates table
2. Verify template variables are provided correctly in CloudEvents
3. Check for missing i18n keys
4. Test template rendering manually: `kubectl exec -n production <pod> -- python3 -c "from notification.template_service import render; render('order_confirmation', context)"`

## Scaling Considerations

- **HPA:** Configured for 2-4 replicas, CPU target 75%
- **Asynchronous service:** Can tolerate brief scaling delays
- **Channel-specific scaling:** Email/webhook channels may need different scaling than SMS/push
- **PDB:** maxUnavailable: 1
- **Kafka partitions:** Ensure partition count supports maximum consumer replicas

## Dependencies

### Upstream
- Kafka (event topics: order.events, payment.events)
- Order service (direct notification requests)
- Gateway (notification preference queries)

### Downstream
- PostgreSQL (notification storage)
- Email provider (SMTP :587)
- SMS provider (HTTPS API)
- Push provider (HTTPS API)
- Webhook endpoints (HTTPS :443)

### Platform dependencies
- OTel Collector (telemetry)
- SPIRE Agent (mTLS SVID)
- Schema Registry (CloudEvents schema)

## Deployment

### How to Deploy
1. Merge PR to `main` — ArgoCD auto-sync applies
2. Python services restart quickly
3. Kafka consumer will rebalance during deployment (brief lag spike expected)
4. Monitor delivery success rate post-deployment

### Rollback Procedure
1. `kubectl rollout undo deployment/notification -n production`
2. Check Kafka consumer offsets after rollback (may need offset reset)
3. Verify notification delivery resumes
4. Check for duplicate notifications if at-least-once delivery caused reprocessing

## On-Call Escalation

| Severity | Response Time | Contact | Channel |
|----------|---------------|---------|---------|
| SEV1 (All notifications failing) | 15 minutes | Notification On-Call | PagerDuty #notification |
| SEV2 (Major channel down) | 30 minutes | Notification On-Call | PagerDuty #notification |
| SEV3 (Delivery delays >5min) | 1 hour | Notification Engineer | Slack #notification-alerts |
| SEV4 (Minor issues) | 8 hours | Notification Engineer | Slack #notification |

**Escalation path:** On-Call Engineer → Notification Lead → VP Engineering

**Note:** Notification is a best-effort service. SEV1/SEV2 response times are relaxed compared to critical-path services (Order, Payment). Notification failures should not block order completion.
