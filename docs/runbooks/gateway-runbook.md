# Gateway Service Runbook

## Service Overview

The Gateway service is the API gateway for the polyglot microservices platform, implemented in **Go**. It serves as the single entry point for all external client traffic, routing requests to backend services via gRPC proxy and REST pass-through. The gateway handles rate limiting, authentication forwarding, and request routing based on path and header patterns. It integrates with the RL Engine for rate limiting and the Identity service for SPIFFE/SPIRE workload attestation.

**Key characteristics:**
- Language: Go
- Protocol: gRPC (port 50051) + HTTP (port 8080)
- SLO: 99.9% availability, p99 latency < 200ms
- Replicas: 2-10 (HPA, CPU target 70%)
- Resource budget: CPU 100m/500m, Memory 128Mi/512Mi

**Dependencies:**
- Identity service (authentication/attestation)
- Catalog service (product queries)
- Order service (order management)
- Payment service (payment processing)
- Analytics service (analytics queries)
- Schema Registry (schema resolution)
- RL Engine (rate limiting)
- OTel Collector (telemetry export)
- SPIRE Agent (mTLS SVID)

## Architecture

```
External Clients
    |
    v
[Gateway :8443/:8080]
    |
    +-- gRPC proxy --> Identity :9090
    +-- gRPC proxy --> Catalog :9090
    +-- gRPC proxy --> Order :9090
    +-- gRPC proxy --> Payment :9090
    +-- REST proxy --> Analytics :9090
    +-- gRPC proxy --> Schema Registry :9090
    +-- RL Engine   --> Rate limit checks
    +-- OTel        --> Traces/Metrics
    +-- SPIRE       --> mTLS SVID rotation
```

- gRPC port: 50051 (internal service-to-service)
- HTTP port: 8080 (health checks, REST proxy)
- Service discovery: Kubernetes DNS + endpoint watch
- mTLS: SPIFFE/SPIRE workload API via Unix socket

## Health Checks

| Endpoint | Method | Expected Response | Notes |
|----------|--------|-------------------|-------|
| `/healthz` | GET | 200 OK | Combined liveness + readiness |
| `:50051` | gRPC reflection | ListServices response | gRPC health |

**K8s probes:**
- Liveness: HTTP GET `/healthz` on port `http`, initialDelay 15s, period 20s
- Readiness: HTTP GET `/healthz` on port `http`, initialDelay 5s, period 10s

## Common Alerts

### ServiceDown (gateway)
**Meaning:** No ready gateway pods for 2 minutes. External traffic cannot reach any backend service.
**Investigation:**
1. Check pod status: `kubectl get pods -n production -l app.kubernetes.io/name=gateway`
2. Check pod events: `kubectl describe pod <pod-name> -n production`
3. Check recent deployments: `kubectl rollout history deployment/gateway -n production`
4. Check resource pressure: `kubectl top pods -n production -l app.kubernetes.io/name=gateway`

### HighLatency (gateway)
**Meaning:** p99 latency exceeds 2s for 5 minutes. Users experience slow responses.
**Investigation:**
1. Check downstream service health (all routed services)
2. Examine trace data in Tempo for slow spans
3. Check RL Engine response times (rate limiting may be adding latency)
4. Check CPU/memory utilization on gateway pods
5. Review recent traffic patterns for anomalies

### HighErrorRate (gateway)
**Meaning:** Error rate exceeds 5% for 5 minutes. Users are receiving 5xx responses.
**Investigation:**
1. Check which downstream services are returning errors
2. Examine error types in Loki logs (connection refused, timeout, circuit breaker open)
3. Check if mTLS SVIDs are valid and not expired
4. Review NetworkPolicy enforcement (may be blocking legitimate traffic)

## Troubleshooting Steps

### Gateway returning 503 Service Unavailable
1. Check if backend service pods are running: `kubectl get pods -n production -l app.kubernetes.io/name=<service>`
2. Check gateway logs for connection errors: `kubectl logs -n production -l app.kubernetes.io/name=gateway --tail=100`
3. Verify DNS resolution: `kubectl exec -n production <gateway-pod> -- nslookup <service>.production.svc.cluster.local`
4. Check circuit breaker status in metrics: `resilience4j_circuitbreaker_state{job="gateway"}`

### Gateway OOMKilled
1. Check memory limits: `kubectl describe pod <pod-name> -n production | grep -A5 Limits`
2. Review traffic volume — may need to scale up via HPA
3. Increase memory limits in deployment manifest if within quota
4. Check for memory leaks in Go runtime: `debug/pprof/heap`

### mTLS certificate errors
1. Check SPIRE Agent health: `kubectl get pods -n production -l app.kubernetes.io/name=spire-agent`
2. Verify SVID rotation: `kubectl exec -n production <gateway-pod> -- ls -la /run/spire/sockets/`
3. Check SPIFFE ID annotation: `kubectl get sa gateway -n production -o yaml`
4. Run mTLS verification script: `./scripts/mtls-verify.sh`

## Scaling Considerations

- **HPA:** Configured for 2-10 replicas, CPU target 70%
- **Scale up trigger:** CPU > 70% for 30 seconds, adds up to 100% or 3 pods per minute
- **Scale down:** Cooldown period of 5 minutes, removes 25% of pods per 2 minutes
- **Manual scaling:** `kubectl scale deployment gateway -n production --replicas=<N>`
- **PDB:** maxUnavailable: 1 — ensures at least N-1 pods during disruptions
- **Vertical scaling:** Increase CPU/memory limits if HPA cannot keep up with burst traffic

## Dependencies

### Upstream (traffic sources)
- External clients (internet)
- Load balancer / Ingress controller

### Downstream (traffic destinations)
- Identity service (gRPC :9090)
- Catalog service (gRPC :9090)
- Order service (gRPC :9090)
- Payment service (gRPC :9090)
- Analytics service (REST :9090)
- Schema Registry (gRPC :9090)

### Platform dependencies
- RL Engine (rate limiting gRPC)
- OTel Collector (telemetry :4317)
- SPIRE Agent (mTLS Unix socket)
- Kubernetes API (service discovery)

## Deployment

### How to Deploy
1. Merge PR to `main` branch
2. ArgoCD auto-sync detects change and applies to production
3. Monitor rollout: `kubectl rollout status deployment/gateway -n production`
4. Verify health: `curl http://gateway.production.svc.cluster.local:8080/healthz`

### Rollback Procedure
1. Identify last working revision: `kubectl rollout history deployment/gateway -n production`
2. Rollback: `kubectl rollout undo deployment/gateway -n production --to-revision=<N>`
3. If ArgoCD auto-sync re-applies, pause sync: `argocd app pause gateway`
4. After fix, resume sync: `argocd app resume gateway`
5. Verify health after rollback

### Emergency Redeploy
```bash
# Force ArgoCD sync to last known good state
argocd app sync gateway --revision <commit-sha>

# Or manually set image tag
kubectl set image deployment/gateway gateway=ghcr.io/example/gateway:<previous-tag> -n production
```

## On-Call Escalation

| Severity | Response Time | Contact | Channel |
|----------|---------------|---------|---------|
| SEV1 (Gateway fully down) | 5 minutes | Platform On-Call | PagerDuty #platform |
| SEV2 (High error rate >10%) | 15 minutes | Platform On-Call | PagerDuty #platform |
| SEV3 (High latency >5s) | 30 minutes | Platform Engineer | Slack #platform-alerts |
| SEV4 (Minor issues) | 4 hours | Platform Engineer | Slack #platform |

**Escalation path:** On-Call Engineer → Platform Lead → VP Engineering
