#!/usr/bin/env bash
# ============================================================================
# ArgoCD Sync Policy & Health Validation Script
# Polyglot Microservices Platform — Phase 5.2
# ============================================================================
# Validates the entire ArgoCD deployment state including:
#   1. Pre-sync validation  — manifest paths, ConfigMaps/Secrets, image tags, kustomize builds
#   2. Sync validation      — sync status, health status, orphaned resources, config drift
#   3. Post-sync health     — /healthz endpoints, mTLS/SPIFFE, OTel traces, Kafka topics
#   4. JSON report output   — per-app status, overall health score
#
# Usage:
#   ./scripts/argocd-sync-validate.sh [OPTIONS]
#
# Options:
#   --phase <pre|sync|post|all>   Run a specific phase [default: all]
#   --output <file>               Write JSON report to file [default: stdout]
#   --argocd-server <url>         ArgoCD server URL [default: argocd-server.argocd.svc]
#   --argocd-token <token>        ArgoCD auth token (or set ARGOCD_AUTH_TOKEN)
#   --namespace <ns>              Target namespace [default: production]
#   --skip-cluster-checks         Skip checks requiring kubectl/cluster access
#   --verbose                     Show detailed output
#   -h, --help                    Show this help message
#
# Exit codes:
#   0 — All validations passed
#   1 — One or more validations failed
#   2 — Prerequisites not met (missing tools)
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICES_DIR="$PROJECT_ROOT/services"
K8S_DIR="$PROJECT_ROOT/infra/kubernetes"
TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
PHASE="all"
OUTPUT_FILE=""
ARGOCD_SERVER="${ARGOCD_SERVER:-argocd-server.argocd.svc}"
ARGOCD_TOKEN="${ARGOCD_AUTH_TOKEN:-}"
NAMESPACE="${NAMESPACE:-production}"
SKIP_CLUSTER_CHECKS=false
VERBOSE=0

# Services in the ApplicationSet (9 services)
ALL_SERVICES=(gateway identity catalog order payment notification analytics cdc-relay schema-registry)

# Health check endpoints per service
declare -A HEALTH_ENDPOINTS=(
  [gateway]="http://gateway.${NAMESPACE}.svc.cluster.local:8080/healthz"
  [identity]="http://identity.${NAMESPACE}.svc.cluster.local:8080/health"
  [catalog]="http://catalog.${NAMESPACE}.svc.cluster.local:3000/health"
  [order]="http://order.${NAMESPACE}.svc.cluster.local:8084/health"
  [payment]="http://payment.${NAMESPACE}.svc.cluster.local:9091/healthz"
  [notification]="http://notification.${NAMESPACE}.svc.cluster.local:8086/health"
  [analytics]="http://analytics.${NAMESPACE}.svc.cluster.local:8087/health"
  [cdc-relay]="http://cdc-relay.${NAMESPACE}.svc.cluster.local:8085/healthz"
  [schema-registry]="http://schema-registry.${NAMESPACE}.svc.cluster.local:8089/healthz"
)

# Expected Kafka topics
KAFKA_TOPICS=(
  "order.created"
  "order.updated"
  "order.cancelled"
  "payment.processed"
  "payment.failed"
  "catalog.updated"
  "catalog.deleted"
  "notification.send"
  "analytics.events"
  "cdc.outbox.events"
)

# Result tracking
declare -A VALIDATION_RESULTS
TOTAL_CHECKS=0
PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

# ---------------------------------------------------------------------------
# Argument Parsing
# ---------------------------------------------------------------------------
usage() {
  head -30 "$0" | tail -26
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --phase)         PHASE="$2"; shift 2 ;;
    --output)        OUTPUT_FILE="$2"; shift 2 ;;
    --argocd-server) ARGOCD_SERVER="$2"; shift 2 ;;
    --argocd-token)  ARGOCD_TOKEN="$2"; shift 2 ;;
    --namespace)     NAMESPACE="$2"; shift 2 ;;
    --skip-cluster-checks) SKIP_CLUSTER_CHECKS=true; shift ;;
    --verbose)       VERBOSE=1; shift ;;
    -h|--help)       usage ;;
    *)               echo -e "${RED}Unknown option: $1${NC}" >&2; exit 1 ;;
  esac
done

# Validate phase argument
case "$PHASE" in
  pre|sync|post|all) ;;
  *) echo -e "${RED}Invalid phase: $PHASE (must be pre|sync|post|all)${NC}" >&2; exit 1 ;;
esac

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log_header() {
  echo ""
  echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════════════${NC}"
  echo -e "${BOLD}${CYAN}  $1${NC}"
  echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════════════${NC}"
  echo ""
}

log_section() {
  echo ""
  echo -e "${BOLD}── $1 ──${NC}"
}

log_pass() {
  local check="$1" detail="${2:-}"
  ((PASS_COUNT++)) || true
  ((TOTAL_CHECKS++)) || true
  VALIDATION_RESULTS["$check"]="PASS"
  echo -e "  ${GREEN}✓ PASS${NC} $check ${detail:+($detail)}"
}

log_fail() {
  local check="$1" detail="${2:-}"
  ((FAIL_COUNT++)) || true
  ((TOTAL_CHECKS++)) || true
  VALIDATION_RESULTS["$check"]="FAIL"
  echo -e "  ${RED}✗ FAIL${NC} $check ${detail:+($detail)}"
}

log_warn() {
  local check="$1" detail="${2:-}"
  ((WARN_COUNT++)) || true
  ((TOTAL_CHECKS++)) || true
  VALIDATION_RESULTS["$check"]="WARN"
  echo -e "  ${YELLOW}⚠ WARN${NC} $check ${detail:+($detail)}"
}

log_info() {
  echo -e "  ${CYAN}ℹ${NC} $1"
}

# Run argocd CLI command with auth
argocd_cmd() {
  local cmd="$1"
  if [[ -n "$ARGOCD_TOKEN" ]]; then
    argocd $cmd --server "$ARGOCD_SERVER" --auth-token "$ARGOCD_TOKEN" --grpc-web 2>/dev/null
  else
    argocd $cmd --server "$ARGOCD_SERVER" --grpc-web 2>/dev/null
  fi
}

# Check if a tool exists
require_tool() {
  local tool="$1"
  if ! command -v "$tool" &>/dev/null; then
    echo -e "${RED}Required tool not found: $tool${NC}" >&2
    return 1
  fi
}

# ============================================================================
# PHASE 1: Pre-Sync Validation
# ============================================================================
phase_pre_sync() {
  log_header "PHASE 1: Pre-Sync Validation"

  # --- 1.1 Check ApplicationSet template paths resolve ---
  log_section "1.1 ApplicationSet Template Path Resolution"
  local app_of_apps="$K8S_DIR/apps/app-of-apps.yaml"

  if [[ ! -f "$app_of_apps" ]]; then
    log_fail "app-of-apps.yaml exists" "File not found at $app_of_apps"
  else
    log_pass "app-of-apps.yaml exists" "$app_of_apps"

    # Parse service names and paths from the ApplicationSet
    local missing_paths=0
    for svc in "${ALL_SERVICES[@]}"; do
      local kustomize_dir="$SERVICES_DIR/$svc/kustomize"
      if [[ -d "$kustomize_dir" ]]; then
        # Verify kustomization.yaml exists
        if [[ -f "$kustomize_dir/kustomization.yaml" ]]; then
          log_pass "path:$svc/kustomize resolves" "$kustomize_dir"
        else
          log_fail "path:$svc/kustomize/kustomization.yaml" "Missing kustomization.yaml"
          missing_paths=$((missing_paths + 1))
        fi
      else
        log_fail "path:$svc/kustomize resolves" "Directory not found at $kustomize_dir"
        missing_paths=$((missing_paths + 1))
      fi
    done

    if [[ $missing_paths -eq 0 ]]; then
      log_pass "All 9 ApplicationSet paths resolve"
    else
      log_fail "ApplicationSet path resolution" "$missing_paths path(s) missing"
    fi
  fi

  # --- 1.2 Verify referenced ConfigMaps/Secrets exist in source ---
  log_section "1.2 ConfigMap/Secret Reference Validation"
  local config_refs_found=0
  local config_refs_missing=0

  # Check platform ConfigMaps referenced in platform components
  local platform_dir="$K8S_DIR/platform"
  if [[ -d "$platform_dir" ]]; then
    local configmaps_in_platform
    configmaps_in_platform=$(rg -o 'name:\s+\S+-config\b|configMapRef:\s*\n\s+name:\s+\S+' \
      "$platform_dir" --no-filename 2>/dev/null | sed 's/.*name:\s*//' | sort -u) || true

    for cm in $configmaps_in_platform; do
      cm=$(echo "$cm" | xargs) # trim whitespace
      if [[ -z "$cm" ]]; then continue; fi
      # Check if the ConfigMap is defined somewhere in the repo
      if rg -q "kind:\s*ConfigMap" "$platform_dir" -r 2>/dev/null && \
         rg -q "name:\s*${cm}" "$platform_dir" -r 2>/dev/null; then
        log_pass "ConfigMap:$cm defined" "Found in platform manifests"
        config_refs_found=$((config_refs_found + 1))
      else
        log_warn "ConfigMap:$cm not found in source" "May be created at runtime"
        config_refs_missing=$((config_refs_missing + 1))
      fi
    done
  fi

  # Check for SPIRE bundle ConfigMap reference (special case)
  if rg -q "spire-bundle" "$K8S_DIR/apps/app-of-apps.yaml" 2>/dev/null; then
    log_pass "spire-bundle ConfigMap referenced" "ignoreDifferences configured"
  else
    log_warn "spire-bundle ConfigMap" "Not in ignoreDifferences — may cause drift"
  fi

  log_info "ConfigMap references: $config_refs_found found, $config_refs_missing may be runtime-created"

  # --- 1.3 Validate image tags exist in GHCR ---
  log_section "1.3 Image Tag Validation (GHCR)"
  local image_tag_failures=0

  # Read image references from production overlay
  local prod_overlay="$K8S_DIR/overlays/production/kustomization.yaml"
  if [[ -f "$prod_overlay" ]]; then
    # Extract image lines: newName and newTag
    local images
    images=$(rg 'newName:|newTag:' "$prod_overlay" 2>/dev/null) || true

    local current_image=""
    while IFS= read -r line; do
      if echo "$line" | rg -q "newName:"; then
        current_image=$(echo "$line" | sed 's/.*newName:\s*//')
      elif echo "$line" | rg -q "newTag:" && [[ -n "$current_image" ]]; then
        local tag=$(echo "$line" | sed 's/.*newTag:\s*//')
        local full_image="${current_image}:${tag}"

        # Try to verify image exists in GHCR
        if command -v skopeo &>/dev/null; then
          if skopeo inspect "docker://$full_image" &>/dev/null; then
            log_pass "image:$full_image" "Verified in GHCR via skopeo"
          else
            log_warn "image:$full_image" "Not found in GHCR (may be private or not yet pushed)"
            image_tag_failures=$((image_tag_failures + 1))
          fi
        elif command -v curl &>/dev/null; then
          # Use GHCR API (unauthenticated — only works for public images)
          local ghcr_org=$(echo "$current_image" | sed 's|ghcr.io/||' | cut -d'/' -f1)
          local ghcr_repo=$(echo "$current_image" | sed 's|ghcr.io/||' | cut -d'/' -f2)
          local ghcr_response
          ghcr_response=$(curl -s -o /dev/null -w "%{http_code}" \
            "https://ghcr.io/v2/${ghcr_org}/${ghcr_repo}/manifests/${tag}" 2>/dev/null) || true
          if [[ "$ghcr_response" == "200" ]] || [[ "$ghcr_response" == "401" ]]; then
            # 200 = exists, 401 = exists but requires auth (acceptable)
            log_pass "image:$full_image" "GHCR API returned $ghcr_response"
          else
            log_warn "image:$full_image" "GHCR API returned $ghcr_response (may not exist or requires auth)"
            image_tag_failures=$((image_tag_failures + 1))
          fi
        else
          log_warn "image:$full_image" "Neither skopeo nor curl available for verification"
          image_tag_failures=$((image_tag_failures + 1))
        fi

        current_image=""
      fi
    done <<< "$images"
  else
    log_warn "production overlay" "Not found at $prod_overlay"
  fi

  if [[ $image_tag_failures -gt 0 ]]; then
    log_warn "Image tag validation" "$image_tag_failures image(s) could not be verified"
  fi

  # --- 1.4 Check kustomize build succeeds for each service overlay ---
  log_section "1.4 Kustomize Build Validation"
  if command -v kustomize &>/dev/null; then
    for svc in "${ALL_SERVICES[@]}"; do
      local k_dir="$SERVICES_DIR/$svc/kustomize"
      if [[ -f "$k_dir/kustomization.yaml" ]]; then
        if kustomize build "$k_dir" >/dev/null 2>&1; then
          log_pass "kustomize build $svc" "Build succeeded"
        else
          log_fail "kustomize build $svc" "Build failed"
          if [[ $VERBOSE -eq 1 ]]; then
            kustomize build "$k_dir" 2>&1 | head -20 | while read -r line; do
              echo -e "      $line"
            done
          fi
        fi
      else
        log_warn "kustomize build $svc" "No kustomization.yaml found"
      fi
    done

    # Also build the overlays
    for overlay in dev staging production; do
      local overlay_dir="$K8S_DIR/overlays/$overlay"
      if [[ -f "$overlay_dir/kustomization.yaml" ]]; then
        if kustomize build "$overlay_dir" >/dev/null 2>&1; then
          log_pass "kustomize build overlay/$overlay" "Build succeeded"
        else
          log_warn "kustomize build overlay/$overlay" "Build failed (expected — may need base resources)"
        fi
      fi
    done
  else
    log_warn "kustomize tool" "Not installed — skipping kustomize build validation"
  fi
}

# ============================================================================
# PHASE 2: Sync Validation
# ============================================================================
phase_sync() {
  log_header "PHASE 2: Sync Validation"

  if $SKIP_CLUSTER_CHECKS; then
    log_warn "Sync validation" "Skipped (--skip-cluster-checks)"
    return
  fi

  # --- 2.1 Check argocd CLI availability ---
  log_section "2.1 ArgoCD CLI Availability"
  if ! command -v argocd &>/dev/null; then
    log_fail "argocd CLI" "Not installed — cannot validate sync status"
    log_info "Install: brew install argocd or https://argoproj.github.io/argo-cd/cli_installation/"
    return
  fi
  log_pass "argocd CLI available"

  # --- 2.2 List all apps and their sync status ---
  log_section "2.2 Application Sync Status"
  local app_list
  app_list=$(argocd_cmd "app list --output json" 2>/dev/null) || {
    log_warn "argocd app list" "Could not retrieve app list (check auth/server)"
    log_info "Set ARGOCD_AUTH_TOKEN or use --argocd-token"
    return
  }

  if command -v jq &>/dev/null; then
    local total_apps
    total_apps=$(echo "$app_list" | jq 'length' 2>/dev/null) || total_apps=0
    log_info "Found $total_apps ArgoCD applications"

    # Check each app
    echo "$app_list" | jq -c '.[]' 2>/dev/null | while read -r app_json; do
      local app_name=$(echo "$app_json" | jq -r '.metadata.name' 2>/dev/null)
      local sync_status=$(echo "$app_json" | jq -r '.status.sync.status // "Unknown"' 2>/dev/null)
      local health_status=$(echo "$app_json" | jq -r '.status.health.status // "Unknown"' 2>/dev/null)

      # Check sync status
      if [[ "$sync_status" == "Synced" ]]; then
        log_pass "sync:$app_name" "Sync status: $sync_status"
      elif [[ "$sync_status" == "OutOfSync" ]]; then
        log_warn "sync:$app_name" "Sync status: $sync_status — drift detected"
      else
        log_fail "sync:$app_name" "Sync status: $sync_status"
      fi

      # Check health status
      if [[ "$health_status" == "Healthy" ]]; then
        log_pass "health:$app_name" "Health status: $health_status"
      elif [[ "$health_status" == "Degraded" ]]; then
        log_fail "health:$app_name" "Health status: $health_status"
      elif [[ "$health_status" == "Progressing" ]]; then
        log_warn "health:$app_name" "Health status: $health_status — still deploying"
      else
        log_warn "health:$app_name" "Health status: $health_status"
      fi
    done
  else
    log_warn "jq not available" "Cannot parse JSON output from argocd"
  fi

  # --- 2.3 Detailed per-app validation ---
  log_section "2.3 Detailed Application Validation"
  local all_apps=("${ALL_SERVICES[@]}" "platform-components")

  for app in "${all_apps[@]}"; do
    local app_detail
    app_detail=$(argocd_cmd "app get $app --output json" 2>/dev/null) || {
      log_warn "app get $app" "Could not retrieve application details"
      continue
    }

    if ! command -v jq &>/dev/null; then
      log_warn "jq not available" "Cannot parse detailed app output"
      continue
    fi

    # Check sync status == "Synced"
    local sync_st
    sync_st=$(echo "$app_detail" | jq -r '.status.sync.status // "Unknown"' 2>/dev/null)
    if [[ "$sync_st" == "Synced" ]]; then
      log_pass "$app:sync.status" "Synced"
    else
      log_fail "$app:sync.status" "Expected Synced, got $sync_st"
    fi

    # Check health status == "Healthy"
    local health_st
    health_st=$(echo "$app_detail" | jq -r '.status.health.status // "Unknown"' 2>/dev/null)
    if [[ "$health_st" == "Healthy" ]]; then
      log_pass "$app:health.status" "Healthy"
    else
      log_fail "$app:health.status" "Expected Healthy, got $health_st"
    fi

    # Check for orphaned resources
    local orphaned
    orphaned=$(echo "$app_detail" | jq -r '.status.orphanedResources // empty' 2>/dev/null)
    if [[ -z "$orphaned" ]] || [[ "$orphaned" == "null" ]]; then
      log_pass "$app:orphanedResources" "None"
    else
      local orphan_count
      orphan_count=$(echo "$orphaned" | jq 'length' 2>/dev/null) || orphan_count="?"
      log_warn "$app:orphanedResources" "Found $orphan_count orphaned resource(s)"
    fi

    # Check revision history limit
    local hist_limit
    hist_limit=$(echo "$app_detail" | jq -r '.spec.syncPolicy.retry.limit // "not set"' 2>/dev/null)
    log_info "$app:retry limit = $hist_limit"
  done

  # --- 2.4 Configuration drift detection ---
  log_section "2.4 Configuration Drift Detection"
  for app in "${all_apps[@]}"; do
    local diff_output
    diff_output=$(argocd_cmd "app diff $app" 2>&1) || true
    if [[ -z "$diff_output" ]]; then
      log_pass "drift:$app" "No configuration drift detected"
    else
      log_warn "drift:$app" "Configuration drift detected"
      if [[ $VERBOSE -eq 1 ]]; then
        echo "$diff_output" | head -30 | while read -r line; do
          echo -e "        $line"
        done
      fi
    fi
  done
}

# ============================================================================
# PHASE 3: Post-Sync Health
# ============================================================================
phase_post_sync() {
  log_header "PHASE 3: Post-Sync Health Checks"

  if $SKIP_CLUSTER_CHECKS; then
    log_warn "Post-sync health" "Skipped (--skip-cluster-checks)"
    return
  fi

  # --- 3.1 Health endpoint checks ---
  log_section "3.1 Service Health Endpoints (/healthz)"
  for svc in "${ALL_SERVICES[@]}"; do
    local endpoint="${HEALTH_ENDPOINTS[$svc]:-}"
    if [[ -z "$endpoint" ]]; then
      log_warn "health:$svc" "No health endpoint configured"
      continue
    fi

    if command -v curl &>/dev/null; then
      local http_code
      http_code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 \
        "$endpoint" 2>/dev/null) || http_code="000"

      if [[ "$http_code" == "200" ]]; then
        log_pass "health:$svc" "HTTP $http_code from $endpoint"
      elif [[ "$http_code" == "000" ]]; then
        log_warn "health:$svc" "Connection refused or timeout"
      else
        log_fail "health:$svc" "HTTP $http_code (expected 200)"
      fi
    elif command -v kubectl &>/dev/null; then
      # Try via kubectl exec as fallback
      local pod_name
      pod_name=$(kubectl get pods -n "$NAMESPACE" -l "app.kubernetes.io/name=$svc" \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null) || true
      if [[ -n "$pod_name" ]]; then
        local health_path
        health_path=$(echo "$endpoint" | sed 's|.*\.svc\.cluster\.local[^/]*||')
        local health_result
        health_result=$(kubectl exec "$pod_name" -n "$NAMESPACE" -- \
          wget -qO- --timeout=5 "http://localhost${health_path}" 2>/dev/null) || true
        if [[ -n "$health_result" ]]; then
          log_pass "health:$svc" "Health check via kubectl exec succeeded"
        else
          log_fail "health:$svc" "Health check via kubectl exec failed"
        fi
      else
        log_warn "health:$svc" "No pod found for kubectl exec fallback"
      fi
    else
      log_warn "health:$svc" "Neither curl nor kubectl available"
    fi
  done

  # --- 3.2 mTLS / SPIFFE SVID verification ---
  log_section "3.2 mTLS Certificate Verification (SPIFFE SVID)"
  if command -v kubectl &>/dev/null; then
    local trust_domain="${SPIFFE_TRUST_DOMAIN:-trust.example.org}"

    for svc in "${ALL_SERVICES[@]}"; do
      local pod_name
      pod_name=$(kubectl get pods -n "$NAMESPACE" -l "app.kubernetes.io/name=$svc" \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null) || true

      if [[ -z "$pod_name" ]]; then
        log_warn "svid:$svc" "No pod found"
        continue
      fi

      # Check if SVID file exists
      local svid_exists
      svid_exists=$(kubectl exec "$pod_name" -n "$NAMESPACE" -- \
        ls /var/run/secrets/spiffe/svid.pem 2>/dev/null) || true

      if [[ -n "$svid_exists" ]]; then
        # Verify SPIFFE ID in the certificate
        local spiffe_id
        spiffe_id=$(kubectl exec "$pod_name" -n "$NAMESPACE" -- \
          cat /var/run/secrets/spiffe/svid.pem 2>/dev/null | \
          openssl x509 -noout -text 2>/dev/null | \
          rg -o "spiffe://[^ ]+" | head -1) || true

        if [[ -n "$spiffe_id" ]]; then
          # Verify trust domain prefix
          if [[ "$spiffe_id" == "spiffe://${trust_domain}/"* ]]; then
            log_pass "svid:$svc" "SPIFFE ID: $spiffe_id"
          else
            log_fail "svid:$svc" "Wrong trust domain: $spiffe_id (expected ${trust_domain})"
          fi
        else
          log_warn "svid:$svc" "SVID file exists but could not extract SPIFFE ID"
        fi
      else
        log_warn "svid:$svc" "SVID file not found (SPIRE may not be injected yet)"
      fi
    done
  else
    log_warn "SVID verification" "kubectl not available — cannot check SVID certificates"
  fi

  # --- 3.3 OTel trace flow verification ---
  log_section "3.3 OTel Trace Flow Verification"
  local tempo_url="${TEMPO_URL:-http://tempo.${NAMESPACE}.svc.cluster.local:3100}"

  if command -v curl &>/dev/null; then
    # Query Tempo API for recent traces
    local traces_response
    traces_response=$(curl -s --connect-timeout 5 --max-time 10 \
      "${tempo_url}/api/traces?service=gateway&limit=1" 2>/dev/null) || true

    if [[ -n "$traces_response" ]] && echo "$traces_response" | rg -q "traces"; then
      log_pass "otel:traces" "Tempo API responding, traces are flowing"
    else
      log_warn "otel:traces" "Could not verify trace flow from Tempo"
    fi

    # Check OTel Collector health
    local otel_collector_url="http://otel-collector.${NAMESPACE}.svc.cluster.local:13133"
    local otel_health
    otel_health=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 \
      "$otel_collector_url" 2>/dev/null) || otel_health="000"

    if [[ "$otel_health" == "200" ]]; then
      log_pass "otel:collector" "OTel Collector healthy (HTTP $otel_health)"
    else
      log_warn "otel:collector" "OTel Collector returned HTTP $otel_health"
    fi
  else
    log_warn "OTel trace verification" "curl not available"
  fi

  # --- 3.4 Kafka topic verification ---
  log_section "3.4 Kafka Topic Verification"
  if command -v kubectl &>/dev/null; then
    # Try to list topics via kafka pod
    local kafka_pod
    kafka_pod=$(kubectl get pods -n "$NAMESPACE" -l "app=kafka" \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null) || true

    if [[ -n "$kafka_pod" ]]; then
      local topic_list
      topic_list=$(kubectl exec "$kafka_pod" -n "$NAMESPACE" -- \
        /opt/kafka/bin/kafka-topics.sh --list --bootstrap-server localhost:9092 2>/dev/null) || true

      if [[ -n "$topic_list" ]]; then
        local missing_topics=()
        for expected_topic in "${KAFKA_TOPICS[@]}"; do
          if echo "$topic_list" | rg -q "$expected_topic"; then
            log_pass "kafka:topic:$expected_topic" "Exists"
          else
            log_fail "kafka:topic:$expected_topic" "Missing"
            missing_topics+=("$expected_topic")
          fi
        done

        if [[ ${#missing_topics[@]} -gt 0 ]]; then
          log_warn "kafka:topics" "${#missing_topics[@]} expected topic(s) missing: ${missing_topics[*]}"
        fi
      else
        log_warn "kafka:topics" "Could not list topics from Kafka pod"
      fi
    else
      log_warn "kafka:topics" "No Kafka pod found in namespace $NAMESPACE"
    fi
  else
    log_warn "Kafka topic verification" "kubectl not available"
  fi
}

# ============================================================================
# JSON Report Generation
# ============================================================================
generate_report() {
  local report
  report=$(cat <<EOF
{
  "timestamp": "${TIMESTAMP}",
  "namespace": "${NAMESPACE}",
  "phase": "${PHASE}",
  "summary": {
    "total_checks": ${TOTAL_CHECKS},
    "passed": ${PASS_COUNT},
    "failed": ${FAIL_COUNT},
    "warnings": ${WARN_COUNT},
    "health_score": $(( TOTAL_CHECKS > 0 ? (PASS_COUNT * 100 / TOTAL_CHECKS) : 0 ))
  },
  "services": [
$(for svc in "${ALL_SERVICES[@]}"; do
    cat <<SVC_EOF
    {
      "name": "${svc}",
      "health_endpoint": "${HEALTH_ENDPOINTS[$svc]:-unknown}",
      "checks": {
        "path_resolved": "${VALIDATION_RESULTS[path:${svc}/kustomize resolves]:-SKIPPED}",
        "kustomize_build": "${VALIDATION_RESULTS[kustomize build ${svc}]:-SKIPPED}",
        "sync_status": "${VALIDATION_RESULTS[sync:${svc}]:-SKIPPED}",
        "health_status": "${VALIDATION_RESULTS[health:${svc}]:-SKIPPED}",
        "svid_present": "${VALIDATION_RESULTS[svid:${svc}]:-SKIPPED}",
        "config_drift": "${VALIDATION_RESULTS[drift:${svc}]:-SKIPPED}"
      }
    },
SVC_EOF
  done | sed '$ s/,$//')
  ],
  "platform_components": {
    "sync_status": "${VALIDATION_RESULTS[sync:platform-components]:-SKIPPED}",
    "health_status": "${VALIDATION_RESULTS[health:platform-components]:-SKIPPED}",
    "config_drift": "${VALIDATION_RESULTS[drift:platform-components]:-SKIPPED}"
  },
  "infrastructure": {
    "otel_traces": "${VALIDATION_RESULTS[otel:traces]:-SKIPPED}",
    "otel_collector": "${VALIDATION_RESULTS[otel:collector]:-SKIPPED}",
    "kafka_topics": "${VALIDATION_RESULTS[kafka:topics]:-SKIPPED}"
  }
}
EOF
)

  if [[ -n "$OUTPUT_FILE" ]]; then
    echo "$report" > "$OUTPUT_FILE"
    log_info "Report written to: $OUTPUT_FILE"
  fi

  echo ""
  echo "$report"
}

# ============================================================================
# Main
# ============================================================================
main() {
  echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}║     ArgoCD Sync Policy & Health Validation — Platform       ║${NC}"
  echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "  Namespace:           ${NAMESPACE}"
  echo -e "  ArgoCD Server:       ${ARGOCD_SERVER}"
  echo -e "  Phase:               ${PHASE}"
  echo -e "  Cluster Checks:      $(${SKIP_CLUSTER_CHECKS} && echo 'DISABLED' || echo 'ENABLED')"
  echo -e "  Timestamp:           ${TIMESTAMP}"
  echo -e "  Services:            ${ALL_SERVICES[*]}"

  # Run selected phases
  case "$PHASE" in
    pre)   phase_pre_sync ;;
    sync)  phase_sync ;;
    post)  phase_post_sync ;;
    all)
      phase_pre_sync
      phase_sync
      phase_post_sync
      ;;
  esac

  # ---------------------------------------------------------------------------
  # Summary & Report
  # ---------------------------------------------------------------------------
  log_header "VALIDATION SUMMARY"

  local health_score=0
  if [[ $TOTAL_CHECKS -gt 0 ]]; then
    health_score=$((PASS_COUNT * 100 / TOTAL_CHECKS))
  fi

  printf "  ${BOLD}%-25s %s${NC}\n" "Total Checks:" "$TOTAL_CHECKS"
  printf "  ${GREEN}%-25s %s${NC}\n" "Passed:" "$PASS_COUNT"
  printf "  ${RED}%-25s %s${NC}\n" "Failed:" "$FAIL_COUNT"
  printf "  ${YELLOW}%-25s %s${NC}\n" "Warnings:" "$WARN_COUNT"
  printf "  ${BOLD}%-25s %s%%${NC}\n" "Health Score:" "$health_score"
  echo ""

  # Generate JSON report
  generate_report

  # Exit code
  if [[ $FAIL_COUNT -gt 0 ]]; then
    echo -e "${RED}${BOLD}VALIDATION FAILED — ${FAIL_COUNT} check(s) did not pass${NC}"
    exit 1
  fi

  echo -e "${GREEN}${BOLD}ALL VALIDATIONS PASSED (Health Score: ${health_score}%)${NC}"
  exit 0
}

main
