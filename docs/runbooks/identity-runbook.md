# Identity Service Runbook

## Service Overview

The Identity service provides SPIFFE/SPIRE workload attestation and SVID management for the polyglot microservices platform, implemented in **Rust**. It serves as the bridge between the SPIRE Server and application workloads, handling workload attestation, SVID issuance, SVID rotation, and revocation. The service validates workload identity based on Kubernetes service account tokens and pod selectors, then issues X.509 SVIDs used for mTLS throughout the platform.

**Key characteristics:**
- Language: Rust
- Protocol: gRPC (port 50058)
- SLO: 99.99% availability, p99 latency < 100ms
- Replicas: 2 (static, no HPA — low and predictable load)
- Resource budget: CPU 100m/300m, Memory 256Mi/512Mi

**Dependencies:**
- SPIRE Server (CA and SVID signing)
- PostgreSQL (workload registration, attestation records)
- OTel Collector (telemetry)
- SPIRE Agent (workload API)

## Architecture

```
All Services (SVID requests)
    |
    v
[Identity :9090]
    |
    +-- gRPC --> AttestWorkload, IssueSVID, RevokeSVID, RotateSVID
    +-- SPIRE Server --> CA signing, Bundle endpoint
    +-- PostgreSQL --> Workload registrations, Attestation records
    +-- OTel  --> Traces/Metrics
    +-- SPIRE Agent --> Workload API (Unix socket)
```

- gRPC port: 50058 (internal)
- HTTP health port: 8080
- SPIFFE trust domain: `trust.example.org`
- SVID TTL: 1 hour (X.509), 15 minutes (JWT)
- CA TTL: 72 hours

## Health Checks

| Endpoint | Method | Expected Response | Notes |
|----------|--------|-------------------|-------|
| `/healthz` | GET | 200 OK | Liveness + readiness |
| `:50058` | gRPC reflection | ListServices response | gRPC health |

**K8s probes:**
- Liveness: HTTP GET `/healthz` on port `http`, initialDelay 15s, period 20s
- Readiness: HTTP GET `/healthz` on port `http`, initialDelay 5s, period 10s

## Common Alerts

### SPIREServerUnhealthy
**Meaning:** SPIRE Server healthz endpoint is failing. SVID issuance is blocked.
**Investigation:**
1. Check SPIRE Server pods: `kubectl get pods -n production -l app.kubernetes.io/name=spire-server`
2. Check server logs for SQLite errors or disk full
3. Check SPIRE Server ConfigMap for misconfiguration
4. Verify data volume is not full

### CertificateExpiry
**Meaning:** A SVID is expiring within 24 hours. Normal rotation should handle this.
**Investigation:**
1. Check which workload's SVID is affected
2. Verify SPIRE Agent is running on the affected node
3. Check workload API socket accessibility
4. If rotation is not happening, restart the affected pod to force re-attestation

### HighErrorRate (identity)
**Meaning:** Attestation or SVID issuance failures exceed 5%.
**Investigation:**
1. Check SPIRE Server gRPC endpoint availability
2. Review attestation logs for invalid service account tokens
3. Check PostgreSQL connectivity for registration lookups
4. Verify entry registrations match deployed workloads

## Troubleshooting Steps

### SVID issuance failing for a workload
1. Check SPIRE Agent on the affected node: `kubectl get pods -n production -l app.kubernetes.io/name=spire-agent -o wide`
2. Verify the workload's service account has the correct SPIFFE annotation: `kubectl get sa <service-name> -n production -o yaml`
3. Check SPIRE entry registrations match the workload: `kubectl exec -n production <spire-server-pod> -- /opt/spire/bin/spire-server entry show`
4. Verify the workload has `spiffe.io/inject: "true"` annotation

### mTLS handshake failures
1. Check SVID expiry: `openssl x509 -in /run/spire/svid.pem -noout -dates`
2. Verify trust bundle is current: `kubectl get configmap spire-bundle -n production -o yaml`
3. Check both services have valid SVIDs
4. Run full mTLS verification: `./scripts/mtls-verify.sh`

### SPIRE Server leader election failure
1. Check all 3 SPIRE Server pods are running
2. Verify network connectivity between server pods
3. Check SQLite data volume health
4. If quorum is lost, may need to bootstrap a new cluster from bundle

## Scaling Considerations

- **No HPA:** Identity service has predictable, low load (2 replicas sufficient)
- **Stateful:** SVID state is managed by SPIRE Server, not the identity service
- **PDB:** maxUnavailable: 1
- **SPIRE Server:** Separate StatefulSet with 3 replicas and its own PDB (minAvailable: 2)

## Dependencies

### Upstream
- All services (SVID attestation requests)
- SPIRE Agent (workload API)

### Downstream
- SPIRE Server (CA signing, registration API)
- PostgreSQL (attestation records)

### Platform dependencies
- OTel Collector (telemetry)
- SPIRE Agent DaemonSet

## Deployment

### How to Deploy
1. Merge PR to `main` — ArgoCD auto-sync applies
2. Rust binary restart is very fast (< 1 second)
3. Existing SVIDs remain valid during restart (handled by SPIRE Agent)
4. Monitor attestation success rate post-deployment

### Rollback Procedure
1. `kubectl rollout undo deployment/identity -n production`
2. Verify SVID issuance resumes correctly
3. Run mTLS verification: `./scripts/mtls-verify.sh`
4. Check all services have valid SVIDs after rollback

### Emergency: SPIRE Cluster Recovery
```bash
# If SPIRE Server cluster is corrupted
kubectl scale statefulset spire-server -n production --replicas=0
# Wait for pods to terminate
kubectl scale statefulset spire-server -n production --replicas=1
# Verify single server is healthy
kubectl scale statefulset spire-server -n production --replicas=3
# Re-register all workload entries
```

## On-Call Escalation

| Severity | Response Time | Contact | Channel |
|----------|---------------|---------|---------|
| SEV1 (SVID issuance failing) | 5 minutes | Security On-Call | PagerDuty #security |
| SEV2 (SPIRE Server unhealthy) | 10 minutes | Security On-Call | PagerDuty #security |
| SEV3 (Certificate rotation issues) | 30 minutes | Security Engineer | Slack #security-alerts |
| SEV4 (Minor issues) | 8 hours | Security Engineer | Slack #security |

**Escalation path:** On-Call Engineer → Security Lead → VP Engineering → CISO (if security breach suspected)

**Note:** Identity/SPIRE is critical infrastructure. If SVIDs cannot be issued, all mTLS communication will begin failing within the SVID TTL window (1 hour). This is a SEV1 priority issue.
