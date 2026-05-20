# Catalog Service Runbook

## Service Overview

The Catalog service manages the product catalog for the polyglot microservices platform, implemented in **TypeScript** (Node.js). It provides product search, browse, and detail retrieval capabilities. The service integrates with Meilisearch for full-text search and PostgreSQL for product data persistence. It supports both gRPC and REST protocols, making products accessible to internal services and the gateway.

**Key characteristics:**
- Language: TypeScript (Node.js)
- Protocol: gRPC (port 50052) + HTTP REST (port 8080)
- SLO: 99.9% availability, p99 latency < 300ms
- Replicas: 2-6 (HPA, CPU target 70%)
- Resource budget: CPU 200m/1000m, Memory 256Mi/1Gi

**Dependencies:**
- PostgreSQL (product data)
- Meilisearch (full-text search index)
- OTel Collector (telemetry)
- SPIRE Agent (mTLS SVID)

## Architecture

```
Gateway / Order Service
    |
    v
[Catalog :9090]
    |
    +-- gRPC --> GetProduct, SearchCatalog, CreateProduct, DeleteProduct
    +-- REST  --> /api/v1/products, /api/v1/products/search
    +-- PostgreSQL --> Products table
    +-- Meilisearch --> Search index (sync on write)
    +-- OTel  --> Traces/Metrics
    +-- SPIRE --> mTLS SVID rotation
```

- gRPC port: 50052 (internal service-to-service)
- HTTP port: 8080 (REST API + health checks)
- Search: Meilisearch index synced on product write operations
- Hexagonal architecture: Domain logic isolated from infrastructure adapters

## Health Checks

| Endpoint | Method | Expected Response | Notes |
|----------|--------|-------------------|-------|
| `/healthz` | GET | 200 OK | Liveness + readiness |
| `:50052` | gRPC reflection | ListServices response | gRPC health |

**K8s probes:**
- Liveness: HTTP GET `/healthz` on port `http`, initialDelay 15s, period 20s
- Readiness: HTTP GET `/healthz` on port `http`, initialDelay 5s, period 10s

## Common Alerts

### ServiceDown (catalog)
**Meaning:** No ready catalog pods for 2 minutes. Product browsing and ordering are blocked.
**Investigation:**
1. Check pod status and events
2. Check database connectivity
3. Check Meilisearch connectivity
4. Review recent deployments for regressions

### HighLatency (catalog)
**Meaning:** p99 latency exceeds 2s. Search queries are slow.
**Investigation:**
1. Check Meilisearch response times (may need index optimization)
2. Check PostgreSQL query performance
3. Check if search index is stale or corrupted
4. Review search query patterns for overly broad queries

### HighErrorRate (catalog)
**Meaning:** Error rate exceeds 5%.
**Investigation:**
1. Check PostgreSQL connection pool exhaustion
2. Check Meilisearch availability
3. Review recent schema changes that may have broken queries

## Troubleshooting Steps

### Search returning stale results
1. Check Meilisearch index last sync time
2. Verify write operations are triggering index updates
3. Check if Meilisearch pods are healthy
4. Manually trigger re-index if needed: `curl -X POST http://meilisearch:9200/indexes/products/sync`

### Database connection pool exhausted
1. Check active connections: `kubectl exec -n production <pod> -- node -e "console.log(process._getActiveHandles().length)"`
2. Review connection pool settings in config
3. Scale up catalog replicas if under high load
4. Check for slow queries holding connections

### Product data inconsistency
1. Compare PostgreSQL data with Meilisearch index
2. Check CDC pipeline for missed updates
3. Verify outbox pattern is publishing events correctly
4. Re-sync search index from PostgreSQL source of truth

## Scaling Considerations

- **HPA:** Configured for 2-6 replicas, CPU target 70%
- **Read-heavy service:** Scales well horizontally
- **Meilisearch scaling:** May need separate scaling if search traffic grows
- **PDB:** maxUnavailable: 1
- **Database:** Read replicas can reduce load on primary PostgreSQL

## Dependencies

### Upstream
- Gateway (product browsing)
- Order service (inventory queries)

### Downstream
- PostgreSQL (product data)
- Meilisearch (search index)

### Platform dependencies
- OTel Collector (telemetry)
- SPIRE Agent (mTLS SVID)

## Deployment

### How to Deploy
1. Merge PR to `main` — ArgoCD auto-sync applies
2. Node.js cold start is fast (unlike JVM)
3. Monitor search index sync after deployment
4. Verify product search functionality in Grafana

### Rollback Procedure
1. `kubectl rollout undo deployment/catalog -n production --to-revision=<N>`
2. Verify search index is consistent after rollback
3. If search index corrupted, trigger full re-index

## On-Call Escalation

| Severity | Response Time | Contact | Channel |
|----------|---------------|---------|---------|
| SEV1 (Catalog fully down) | 5 minutes | Catalog On-Call | PagerDuty #catalog |
| SEV2 (Search not working) | 15 minutes | Catalog On-Call | PagerDuty #catalog |
| SEV3 (Slow search >5s) | 30 minutes | Catalog Engineer | Slack #catalog-alerts |
| SEV4 (Minor issues) | 4 hours | Catalog Engineer | Slack #catalog |

**Escalation path:** On-Call Engineer → Catalog Lead → VP Engineering
