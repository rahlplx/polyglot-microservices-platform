# Schema Registry Runbook

## Service Overview

The Schema Registry service manages schema storage, validation, and compatibility checking for the polyglot microservices platform, implemented in **Go**. It stores Protobuf and Avro schemas used by Kafka producers/consumers and gRPC services. The registry enforces schema evolution rules (additive-only, no breaking changes) and integrates with Buf for breaking change detection in CI. It supports both gRPC and REST protocols for schema operations.

**Key characteristics:**
- Language: Go
- Protocol: gRPC (port 50059) + HTTP REST (port 8081)
- SLO: 99.9% availability, p99 latency < 100ms
- Replicas: 2-4 (HPA, CPU target 60%)
- Resource budget: CPU 100m/300m, Memory 128Mi/256Mi

**Dependencies:**
- PostgreSQL (schema storage)
- Kafka (schema topic for distribution)
- Buf CLI (breaking change detection)
- OTel Collector (telemetry)
- SPIRE Agent (mTLS SVID)

## Architecture

```
All Services (schema resolution)
    |
    v
[Schema Registry :9090]
    |
    +-- gRPC --> RegisterSchema, GetSchema, ListSchemas, CheckCompatibility
    +-- REST  --> /subjects/{subject}/versions, /schemas/{id}
    +-- PostgreSQL --> Schemas, Subjects, Versions
    +-- Kafka --> Schema topic (distribution)
    +-- Buf   --> Breaking change detection
    +-- OTel  --> Traces/Metrics
    +-- SPIRE --> mTLS SVID rotation
```

- gRPC port: 50059 (internal schema resolution)
- HTTP port: 8081 (REST API for Kafka SerDe)
- Schema storage: PostgreSQL with subject/version indexing
- Compatibility: BACKWARD, FORWARD, FULL, NONE (configurable per subject)
- Buf integration: Breaking change checks run in CI pipeline

## Health Checks

| Endpoint | Method | Expected Response | Notes |
|----------|--------|-------------------|-------|
| `/healthz` | GET | 200 OK | Liveness + readiness |
| `:8081` | GET /subjects | 200 OK + JSON array | REST health |

**K8s probes:**
- Liveness: HTTP GET `/healthz` on port `http`, initialDelay 15s, period 20s
- Readiness: HTTP GET `/healthz` on port `http`, initialDelay 5s, period 10s

## Common Alerts

### ServiceDown (schema-registry)
**Meaning:** Schema Registry is down. Kafka producers/consumers cannot serialize/deserialize messages.
**Investigation:**
1. Check pod status and events
2. Check PostgreSQL connectivity
3. Kafka producers will fall back to local schema cache if configured
4. Restart pods if crash-looping

### HighLatency (schema-registry)
**Meaning:** Schema resolution is slow. Kafka produce/consume latency increases.
**Investigation:**
1. Check PostgreSQL query performance
2. Review schema lookup cache hit rate
3. Check if schema count has grown significantly
4. Consider adding caching layer if PostgreSQL is the bottleneck

### KafkaConsumerLag (schema-registry)
**Meaning:** Schema distribution topic consumer is lagging.
**Investigation:**
1. Check schema-registry consumer group
2. Verify Kafka broker health
3. Check for deserialization errors in consumer

## Troubleshooting Steps

### Schema compatibility check failing in CI
1. Check the specific breaking change: `buf breaking schemas/ --against '.git#branch=main,subdir=schemas'`
2. Review schema changes for: field removal, field rename, type change, required field addition
3. Apply additive-only changes: add optional fields, deprecate instead of remove
4. If the change is intentional and backward-compatible, update compatibility level

### Kafka deserialization errors
1. Check if the schema version in the message matches a registered schema
2. Verify schema subject naming convention matches the topic name
3. Check schema compatibility level for the subject
4. If a new schema version was registered incorrectly, deprecate it

### Schema not found for a subject
1. List schemas for subject: `curl http://schema-registry:8081/subjects/{subject}/versions`
2. Check if the schema was registered in the correct subject
3. Verify the service registering the schema has network access
4. Check if the schema registration failed silently (review logs)

## Scaling Considerations

- **HPA:** Configured for 2-4 replicas, CPU target 60%
- **Lightweight service:** Schema lookups are fast, low resource usage
- **Caching:** Most lookups served from in-memory cache after warm-up
- **PDB:** maxUnavailable: 1
- **Database:** Single PostgreSQL instance is typically sufficient

## Dependencies

### Upstream
- All services (schema registration and resolution)
- CDC Relay (schema for Debezium events)

### Downstream
- PostgreSQL (schema storage)
- Kafka (schema distribution topic)

### Platform dependencies
- OTel Collector (telemetry)
- SPIRE Agent (mTLS SVID)

## Deployment

### How to Deploy
1. Merge PR to `main` — ArgoCD auto-sync applies
2. Go binary restart is fast
3. Schema cache will be cold after restart — expect brief latency spike
4. Monitor schema lookup latency post-deployment

### Rollback Procedure
1. `kubectl rollout undo deployment/schema-registry -n production`
2. Verify schema resolution resumes
3. If a schema version was incorrectly registered, use the REST API to deprecate it:
   `curl -X PUT http://schema-registry:8081/subjects/{subject}/versions/{version}/deprecate`

## On-Call Escalation

| Severity | Response Time | Contact | Channel |
|----------|---------------|---------|---------|
| SEV1 (Schema Registry down) | 10 minutes | Platform On-Call | PagerDuty #platform |
| SEV2 (Schema compatibility broken) | 30 minutes | Platform Engineer | PagerDuty #platform |
| SEV3 (Slow lookups >1s) | 2 hours | Platform Engineer | Slack #platform-alerts |
| SEV4 (Minor issues) | 8 hours | Platform Engineer | Slack #platform |

**Escalation path:** On-Call Engineer → Platform Lead → VP Engineering

**Note:** Schema Registry has local caching in consumers. Brief outages (<5 min) are typically tolerable as services use cached schemas.
