# Agent Context — Task 2: ArgoCD GitOps Sync Validation & ApplicationSet Health Checks
# Phase 5.2 — Polyglot Microservices Platform

## Task Summary
Built comprehensive ArgoCD sync validation and health check infrastructure for the polyglot microservices platform, including validation scripts, ConfigMaps, notification configurations, and enhanced ApplicationSet definitions.

## Deliverables

### 1. scripts/argocd-sync-validate.sh
**Comprehensive ArgoCD sync validation script** with 3 phases:

- **Pre-sync validation**:
  - Checks all 9 ApplicationSet template paths resolve to actual kustomize directories
  - Verifies ConfigMap/Secret references exist in source (platform + spire-bundle)
  - Validates image tags via GHCR API (skopeo or curl)
  - Runs `kustomize build` for each service overlay (dev, staging, production)

- **Sync validation**:
  - Runs `argocd app list` to get all apps and their sync status
  - For each app: checks `status.sync.status == "Synced"`, `status.health.status == "Healthy"`, no orphanedResources
  - Runs `argocd app diff` to detect configuration drift
  - Supports `--skip-cluster-checks` for offline validation

- **Post-sync health**:
  - Checks /healthz endpoints for each service (HTTP 200)
  - Verifies mTLS certificates issued (SPIFFE SVID present in /var/run/secrets/spiffe/)
  - Checks OTel traces flowing via Tempo API
  - Validates Kafka topics exist (10 expected topics)
  - Generates JSON report with per-app status and overall health score

### 2. infra/kubernetes/apps/health-checks.yaml
**Health check ConfigMap** containing:

- `health-endpoints.yaml` — Health check URLs for all 9 services + 4 platform components (Kafka, SPIRE, OTel Collector, Tempo)
- `sync-windows.yaml` — 4 sync windows (weekday morning maintenance, weekend freeze, holiday freeze, platform allow window)
- `resource-thresholds.yaml` — CPU/memory/restart/eviction/PVC/availability thresholds + per-service resource budgets from performance-budget.md
- `notification-webhooks.yaml` — Slack webhooks (platform team + oncall), PagerDuty webhook, notification routing rules per trigger type

### 3. infra/kubernetes/apps/argocd-notifications.yaml
**ArgoCD NotificationConfiguration** with:

- **6 Triggers**: on-health-degraded (>5m Degraded), on-out-of-sync (>10m OutOfSync), on-sync-failed, on-sync-succeeded (audit), on-app-deleted, on-app-created
- **6 Slack templates**: Each with rich Slack Block Kit attachments (colored by severity: red=Degraded/Failed, orange=OutOfSync, green=Succeeded, gray=Deleted, blue=Created). All include ArgoCD UI link + runbook link
- **3 Services**: Slack (bot token), Email (SMTP), Webhook (PagerDuty)
- **4 Subscriptions**: project-wide alerts, audit logging, platform component elevated alerts, lifecycle notifications
- **Secret template**: argocd-notifications-secret with placeholders for Slack token, SMTP credentials, PagerDuty routing key

### 4. scripts/kustomize-validate.sh
**Kustomize build validation script** with 6 checks:

1. **Kustomize build per service** — Iterates all 9 services, runs `kustomize build`, validates success
2. **Kustomize build per overlay** — Builds dev, staging, production overlays + kubeconform validation
3. **Resource naming conventions** — Checks all resources have `app.kubernetes.io/name` label, verifies commonLabels in kustomization.yaml
4. **Port uniqueness** — Collects containerPorts and Service ports, detects shared ports (warns, doesn't fail — acceptable in K8s with ClusterIPs)
5. **GHCR image registry** — Verifies all images reference `ghcr.io`, checks base deployment.yaml and all overlay replacements
6. **Production topology spread** — Validates `topologySpreadConstraints` in production overlay, checks zone-based spread, DoNotSchedule enforcement, maxSkew=1

Outputs JSON validation report to `test-results/kustomize-validation-report.json`.

### 5. Enhanced app-of-apps.yaml
**Updates to ApplicationSet template**:

- Added `ignoreDifferences` for SPIRE bundle ConfigMap (jsonPointer /data) to services
- Changed `syncOptions`: `CreateNamespace=true` (was false), added `ServerSideApply=true`
- Added `revisionHistoryLimit: 3`
- Added `app.kubernetes.io/managed-by: argocd` label to template metadata
- Added `info` section with 4 links: Runbook, Architecture, ArgoCD Dashboard, On-Call Escalation
- Verified retry strategy with exponential backoff (5s, factor 2, maxDuration 3m) — already present
- Added `app.kubernetes.io/managed-by: argocd` label to AppProject and platform-components Application
- Added `revisionHistoryLimit: 3` and `info` section to platform-components Application
- Added `ServerSideApply=true` and `CreateNamespace=true` to platform-components syncOptions

## Validation Results

- Bash syntax check: PASS for both scripts
- YAML validation: PASS for all 3 YAML files (app-of-apps.yaml, health-checks.yaml, argocd-notifications.yaml)
- kustomize/kubeconform not available in sandbox — scripts are designed to gracefully skip these checks

## File Locations

| File | Path |
|------|------|
| Sync validation script | `/home/z/my-project/scripts/argocd-sync-validate.sh` |
| Kustomize validation script | `/home/z/my-project/scripts/kustomize-validate.sh` |
| Health check ConfigMap | `/home/z/my-project/infra/kubernetes/apps/health-checks.yaml` |
| Notification config | `/home/z/my-project/infra/kubernetes/apps/argocd-notifications.yaml` |
| Enhanced app-of-apps | `/home/z/my-project/infra/kubernetes/apps/app-of-apps.yaml` |
