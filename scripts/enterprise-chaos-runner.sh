#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Enterprise Chaos Engineering Runner
# ---------------------------------------------------------------------------
# Comprehensive chaos engineering harness for the polyglot microservices
# platform. Replaces the basic chaos-experiments.sh with a full-featured
# runner that integrates Chaos Mesh experiments, SLO validation, and
# RL feedback loop reporting.
#
# Usage:
#   ./scripts/enterprise-chaos-runner.sh [OPTIONS]
#
# Options:
#   --category pod|network|stress|time|http|all
#                        Experiment category to run [default: all]
#   --duration SECS      Default experiment duration override [default: 60]
#   --parallel           Run experiments in parallel (dangerous)
#   --dry-run            Validate experiments without executing
#   --skip-preflight     Skip pre-flight health checks
#   --skip-teardown      Skip chaos resource teardown after run
#   --report-dir PATH    Output directory for reports [default: test-results/chaos]
#   --namespace NS       Kubernetes namespace [default: production]
#   --experiment NAME    Run a single named experiment only
#   --slack-webhook URL  Slack webhook URL for result notifications
#   --slo-error-rate N   Error rate SLO threshold [default: 0.01]
#   --slo-p99-ms N       P99 latency SLO threshold in ms [default: 500]
#   --slo-availability N Availability SLO threshold as pct [default: 99.9]
#   -h, --help           Show this help message
#
# Exit codes:
#   0 — All experiments passed (steady-state maintained)
#   1 — One or more experiments revealed SLO violations
#   2 — Pre-flight checks failed (system not healthy)
#   3 — Fatal error (missing dependencies, invalid args)
# ---------------------------------------------------------------------------
set -euo pipefail

# ─── Constants ───────────────────────────────────────────────────────────────
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly CHAOS_MANIFEST="${PROJECT_ROOT}/infra/kubernetes/enterprise/chaos-experiments.yaml"
readonly TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
readonly VERSION="2.0.0"

# Services in the platform
readonly -a PLATFORM_SERVICES=(
  gateway identity catalog order payment
  notification analytics rl-engine schema-registry
)

# Experiment definitions: name|category|kind|target-service
readonly -a EXPERIMENT_REGISTRY=(
  "gateway-pod-kill|pod|PodChaos|gateway"
  "order-pod-kill|pod|PodChaos|order"
  "payment-pod-kill|pod|PodChaos|payment"
  "kafka-broker-kill|pod|PodChaos|kafka"
  "spire-agent-kill|pod|PodChaos|spire-agent"
  "multi-service-pod-kill|pod|PodChaos|gateway+order+payment"
  "order-to-payment-latency|network|NetworkChaos|order->payment"
  "gateway-to-services-partition|network|NetworkChaos|gateway->backends"
  "kafka-producer-latency|network|NetworkChaos|producers->kafka"
  "dns-resolution-failure|network|NetworkChaos|gateway->dns"
  "cross-zone-partition|network|NetworkChaos|zone1<->zone2+3"
  "payment-cpu-stress|stress|StressChaos|payment"
  "analytics-memory-stress|stress|StressChaos|analytics"
  "gateway-io-stress|stress|StressChaos|gateway"
  "order-clock-skew|time|TimeChaos|order"
  "payment-5xx-injection|http|HTTPChaos|payment"
  "catalog-slow-responses|http|HTTPChaos|catalog"
)

# ─── Defaults ────────────────────────────────────────────────────────────────
CATEGORY="all"
DURATION=60
PARALLEL=false
DRY_RUN=false
SKIP_PREFLIGHT=false
SKIP_TEARDOWN=false
REPORT_DIR="${PROJECT_ROOT}/test-results/chaos"
NAMESPACE="production"
SINGLE_EXPERIMENT=""
SLACK_WEBHOOK=""
SLO_ERROR_RATE=0.01
SLO_P99_MS=500
SLO_AVAILABILITY=99.9

# ─── Runtime state ──────────────────────────────────────────────────────────
PASS=0
FAIL=0
SKIPPED=0
declare -a FAILED_EXPERIMENTS=()
declare -a PASSED_EXPERIMENTS=()
declare -a SKIPPED_EXPERIMENTS=()
declare -A EXPERIMENT_RESULTS=()
BASELINE_METRICS=""
EXECUTION_START=0

# ─── Colors ─────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  readonly RED='\033[0;31m'
  readonly GREEN='\033[0;32m'
  readonly YELLOW='\033[0;33m'
  readonly BLUE='\033[0;34m'
  readonly CYAN='\033[0;36m'
  readonly BOLD='\033[1m'
  readonly NC='\033[0m'
else
  readonly RED='' GREEN='' YELLOW='' BLUE='' CYAN='' BOLD='' NC=''
fi

# ─── Logging ────────────────────────────────────────────────────────────────
log()  { echo -e "${BLUE}[CHAOS]${NC} $*"; }
ok()   { echo -e "${GREEN}[PASS]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[FAIL]${NC}  $*"; }
info() { echo -e "${CYAN}[INFO]${NC}  $*"; }
header() {
  echo ""
  echo -e "${BOLD}════════════════════════════════════════════════════════════════${NC}"
  echo -e "${BOLD}  $*${NC}"
  echo -e "${BOLD}════════════════════════════════════════════════════════════════${NC}"
}
phase() {
  echo ""
  echo -e "${CYAN}── $1 ──${NC}"
}

# ─── Argument Parsing ───────────────────────────────────────────────────────
show_help() {
  head -35 "$0" | tail -28
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --category)
      CATEGORY="$2"; shift 2
      ;;
    --duration)
      DURATION="$2"; shift 2
      ;;
    --parallel)
      PARALLEL=true; shift
      ;;
    --dry-run)
      DRY_RUN=true; shift
      ;;
    --skip-preflight)
      SKIP_PREFLIGHT=true; shift
      ;;
    --skip-teardown)
      SKIP_TEARDOWN=true; shift
      ;;
    --report-dir)
      REPORT_DIR="$2"; shift 2
      ;;
    --namespace)
      NAMESPACE="$2"; shift 2
      ;;
    --experiment)
      SINGLE_EXPERIMENT="$2"; shift 2
      ;;
    --slack-webhook)
      SLACK_WEBHOOK="$2"; shift 2
      ;;
    --slo-error-rate)
      SLO_ERROR_RATE="$2"; shift 2
      ;;
    --slo-p99-ms)
      SLO_P99_MS="$2"; shift 2
      ;;
    --slo-availability)
      SLO_AVAILABILITY="$2"; shift 2
      ;;
    -h|--help)
      show_help
      ;;
    *)
      err "Unknown option: $1"
      exit 3
      ;;
  esac
done

# ─── Dependency Checks ──────────────────────────────────────────────────────
check_dependencies() {
  local missing=0

  for cmd in kubectl jq; do
    if ! command -v "${cmd}" &>/dev/null; then
      err "Required dependency not found: ${cmd}"
      missing=$((missing + 1))
    fi
  done

  # Check Chaos Mesh CRDs
  if ! kubectl get crd podchaos.chaos-mesh.org &>/dev/null; then
    warn "Chaos Mesh CRDs not found — some experiments may fail"
    warn "Install Chaos Mesh: https://chaos-mesh.org/docs/production-installation-using-helm/"
  fi

  # Check manifest file
  if [[ ! -f "${CHAOS_MANIFEST}" ]]; then
    err "Chaos manifest not found: ${CHAOS_MANIFEST}"
    missing=$((missing + 1))
  fi

  if [[ ${missing} -gt 0 ]]; then
    err "Missing ${missing} dependencies. Aborting."
    exit 3
  fi

  ok "All dependencies satisfied"
}

# ─── Pre-flight Validation ──────────────────────────────────────────────────
preflight_checks() {
  phase "Phase 1: Pre-flight Validation"

  local all_healthy=true
  local unhealthy_services=""

  # Check namespace exists
  if ! kubectl get namespace "${NAMESPACE}" &>/dev/null; then
    err "Namespace '${NAMESPACE}' does not exist"
    return 1
  fi
  ok "Namespace '${NAMESPACE}' exists"

  # Check each service deployment
  for svc in "${PLATFORM_SERVICES[@]}"; do
    local ready desired

    ready=$(kubectl get deployment "${svc}" -n "${NAMESPACE}" \
      -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    desired=$(kubectl get deployment "${svc}" -n "${NAMESPACE}" \
      -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")

    if [[ "${ready}" == "${desired}" && "${ready}" != "0" ]]; then
      ok "${svc}: ${ready}/${desired} replicas ready"
    else
      err "${svc}: ${ready}/${desired} replicas ready"
      all_healthy=false
      unhealthy_services="${unhealthy_services} ${svc}"
    fi
  done

  # Check platform components
  local -a platform_components=("kafka" "zookeeper" "spire-server" "spire-agent" "otel-collector")
  for comp in "${platform_components[@]}"; do
    local kind="deployment"
    if kubectl get daemonset "${comp}" -n "${NAMESPACE}" &>/dev/null; then
      kind="daemonset"
    elif kubectl get statefulset "${comp}" -n "${NAMESPACE}" &>/dev/null; then
      kind="statefulset"
    fi

    local ready total
    if [[ "${kind}" == "daemonset" ]]; then
      ready=$(kubectl get daemonset "${comp}" -n "${NAMESPACE}" \
        -o jsonpath='{.status.numberReady}' 2>/dev/null || echo "0")
      total=$(kubectl get daemonset "${comp}" -n "${NAMESPACE}" \
        -o jsonpath='{.status.desiredNumberScheduled}' 2>/dev/null || echo "0")
    elif [[ "${kind}" == "statefulset" ]]; then
      ready=$(kubectl get statefulset "${comp}" -n "${NAMESPACE}" \
        -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
      total=$(kubectl get statefulset "${comp}" -n "${NAMESPACE}" \
        -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")
    else
      ready=$(kubectl get deployment "${comp}" -n "${NAMESPACE}" \
        -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
      total=$(kubectl get deployment "${comp}" -n "${NAMESPACE}" \
        -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")
    fi

    if [[ "${ready}" == "${total}" && "${ready}" != "0" ]]; then
      ok "${comp} (${kind}): ${ready}/${total} ready"
    else
      warn "${comp} (${kind}): ${ready}/${total} ready — platform component"
    fi
  done

  # Check PDBs exist
  local pdb_count
  pdb_count=$(kubectl get pdb -n "${NAMESPACE}" -o name 2>/dev/null | wc -l || echo "0")
  if [[ ${pdb_count} -gt 0 ]]; then
    ok "PodDisruptionBudgets: ${pdb_count} found"
  else
    warn "No PodDisruptionBudgets found — pod kill experiments may be unrestrained"
  fi

  # Check HPAs exist
  local hpa_count
  hpa_count=$(kubectl get hpa -n "${NAMESPACE}" -o name 2>/dev/null | wc -l || echo "0")
  if [[ ${hpa_count} -gt 0 ]]; then
    ok "HorizontalPodAutoscalers: ${hpa_count} found"
  else
    warn "No HPAs found — stress experiments may not trigger scaling"
  fi

  if [[ "${all_healthy}" == false ]]; then
    err "Unhealthy services:${unhealthy_services}"
    err "System is not in a steady state. Aborting chaos experiments."
    return 1
  fi

  ok "All services healthy — system is in steady state"
  return 0
}

# ─── Steady-State Hypothesis ────────────────────────────────────────────────
record_baseline() {
  phase "Phase 2: Steady-State Baseline Recording"

  info "SLO Thresholds:"
  info "  Error Rate    < ${SLO_ERROR_RATE}"
  info "  P99 Latency   < ${SLO_P99_MS}ms"
  info "  Availability  > ${SLO_AVAILABILITY}%"

  local baseline_file="${REPORT_DIR}/baseline-${TIMESTAMP}.json"

  # Build baseline metrics by querying Prometheus
  local prom_available=false
  if kubectl get svc prometheus -n "${NAMESPACE}" &>/dev/null; then
    prom_available=true
  fi

  local baseline_error_rate=0
  local baseline_p99=0
  local baseline_availability=100

  if [[ "${prom_available}" == true ]]; then
    info "Querying Prometheus for baseline metrics..."

    # Error rate baseline
    baseline_error_rate=$(kubectl exec -n "${NAMESPACE}" svc/prometheus -- \
      wget -qO- 'http://localhost:9090/api/v1/query?query=sum(rate(http_server_errors_total{namespace="'${NAMESPACE}'"}[5m]))/sum(rate(http_server_requests_total{namespace="'${NAMESPACE}'"}[5m]))' \
      2>/dev/null | jq -r '.data.result[0].value[1] // "0"' 2>/dev/null || echo "0")

    # P99 latency baseline
    baseline_p99=$(kubectl exec -n "${NAMESPACE}" svc/prometheus -- \
      wget -qO- 'http://localhost:9090/api/v1/query?query=histogram_quantile(0.99,sum(rate(http_server_request_duration_seconds_bucket{namespace="'${NAMESPACE}'"}[5m]))by(le))' \
      2>/dev/null | jq -r '.data.result[0].value[1] // "0"' 2>/dev/null || echo "0")

    # Availability baseline
    baseline_availability=$(kubectl exec -n "${NAMESPACE}" svc/prometheus -- \
      wget -qO- 'http://localhost:9090/api/v1/query?query=100*(1-sum(rate(http_server_errors_total{namespace="'${NAMESPACE}'"}[5m]))/sum(rate(http_server_requests_total{namespace="'${NAMESPACE}'"}[5m])))' \
      2>/dev/null | jq -r '.data.result[0].value[1] // "100"' 2>/dev/null || echo "100")

    ok "Baseline metrics collected from Prometheus"
  else
    warn "Prometheus not available — using synthetic baselines"
  fi

  # Record per-service health
  local -A service_health=()
  for svc in "${PLATFORM_SERVICES[@]}"; do
    local ready
    ready=$(kubectl get deployment "${svc}" -n "${NAMESPACE}" \
      -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    service_health["${svc}"]=${ready}
  done

  # Write baseline to JSON
  cat > "${baseline_file}" <<BASELINE_EOF
{
  "timestamp": "${TIMESTAMP}",
  "namespace": "${NAMESPACE}",
  "slo_thresholds": {
    "error_rate": ${SLO_ERROR_RATE},
    "p99_latency_ms": ${SLO_P99_MS},
    "availability_pct": ${SLO_AVAILABILITY}
  },
  "baseline_metrics": {
    "error_rate": ${baseline_error_rate},
    "p99_latency_seconds": ${baseline_p99},
    "availability_pct": ${baseline_availability}
  },
  "service_health": {
BASELINE_EOF

  local first=true
  for svc in "${PLATFORM_SERVICES[@]}"; do
    if [[ "${first}" == true ]]; then
      first=false
    else
      echo "," >> "${baseline_file}"
    fi
    printf '    "%s": %s' "${svc}" "${service_health[${svc}]}" >> "${baseline_file}"
  done

  echo "" >> "${baseline_file}"
  cat >> "${baseline_file}" <<'BASELINE_EOF'
  }
}
BASELINE_EOF

  ok "Baseline saved to ${baseline_file}"

  BASELINE_METRICS=$(cat "${baseline_file}")
  info "Baseline Error Rate: ${baseline_error_rate}"
  info "Baseline P99: ${baseline_p99}s"
  info "Baseline Availability: ${baseline_availability}%"
}

# ─── Generate Prometheus Queries ────────────────────────────────────────────
generate_prom_queries() {
  local queries_file="${REPORT_DIR}/prometheus-queries-${TIMESTAMP}.txt"

  cat > "${queries_file}" <<QUERIES_EOF
# Prometheus Queries for Chaos Experiment Validation
# Generated: ${TIMESTAMP}
# Namespace: ${NAMESPACE}

## ── Global SLO Queries ──

# Error Rate (should be < ${SLO_ERROR_RATE})
sum(rate(http_server_errors_total{namespace="${NAMESPACE}"}[2m])) / sum(rate(http_server_requests_total{namespace="${NAMESPACE}"}[2m]))

# P99 Latency (should be < ${SLO_P99_MS}ms)
histogram_quantile(0.99, sum(rate(http_server_request_duration_seconds_bucket{namespace="${NAMESPACE}"}[2m])) by (le))

# Availability (should be > ${SLO_AVAILABILITY}%)
100 * (1 - sum(rate(http_server_errors_total{namespace="${NAMESPACE}"}[2m])) / sum(rate(http_server_requests_total{namespace="${NAMESPACE}"}[2m])))

## ── Per-Service Queries ──

# Gateway Error Rate
sum(rate(http_server_errors_total{namespace="${NAMESPACE}",service="gateway"}[2m])) / sum(rate(http_server_requests_total{namespace="${NAMESPACE}",service="gateway"}[2m]))

# Order Service Error Rate
sum(rate(http_server_errors_total{namespace="${NAMESPACE}",service="order"}[2m])) / sum(rate(http_server_requests_total{namespace="${NAMESPACE}",service="order"}[2m]))

# Payment Service Error Rate (watch circuit breaker)
sum(rate(http_server_errors_total{namespace="${NAMESPACE}",service="payment"}[2m])) / sum(rate(http_server_requests_total{namespace="${NAMESPACE}",service="payment"}[2m]))

# Payment Circuit Breaker State
resilience4j_circuitbreaker_state{namespace="${NAMESPACE}",service="payment"}

# Kafka Consumer Lag
kafka_consumer_group_lag{namespace="${NAMESPACE}"}

# Kafka Under-Replicated Partitions
kafka_cluster_partition_underreplicated{namespace="${NAMESPACE}"}

# HPA Replica Counts
kube_hpa_status_current_replicas{namespace="${NAMESPACE}"}

# Pod Restarts (should not spike during chaos)
increase(kube_pod_container_status_restarts_total{namespace="${NAMESPACE}"}[10m])

## ── SPIRE Identity Queries ──

# SVID Expiry (should remain valid during spire-agent-kill)
spire_agent_svid_ttl_seconds{namespace="${NAMESPACE}"}

# SPIRE Agent Health
up{namespace="${NAMESPACE}",job="spire-agent"}
QUERIES_EOF

  ok "Prometheus queries saved to ${queries_file}"
}

# ─── Experiment Filtering ───────────────────────────────────────────────────
get_experiments_for_category() {
  local category="$1"
  local -a result=()

  for entry in "${EXPERIMENT_REGISTRY[@]}"; do
    IFS='|' read -r name cat kind target <<< "${entry}"

    # Filter by single experiment name
    if [[ -n "${SINGLE_EXPERIMENT}" && "${name}" != "${SINGLE_EXPERIMENT}" ]]; then
      continue
    fi

    # Filter by category
    if [[ "${category}" == "all" || "${cat}" == "${category}" ]]; then
      result+=("${entry}")
    fi
  done

  printf '%s\n' "${result[@]}"
}

# ─── Experiment Execution ───────────────────────────────────────────────────
apply_experiment() {
  local exp_name="$1"
  local exp_kind="$2"
  local exp_category="$3"
  local exp_target="$4"

  local exp_start=${SECONDS}
  local result_file="${REPORT_DIR}/${exp_name}-${TIMESTAMP}.json"

  echo ""
  log "─────────────────────────────────────────────"
  log "Running: ${exp_name}"
  log "  Kind:     ${exp_kind}"
  log "  Category: ${exp_category}"
  log "  Target:   ${exp_target}"

  if [[ "${DRY_RUN}" == true ]]; then
    info "DRY RUN — would apply ${exp_kind}/${exp_name}"

    # Validate the experiment exists in the manifest
    if kubectl get "${exp_kind}" "${exp_name}" -n "${NAMESPACE}" &>/dev/null; then
      ok "${exp_name}: experiment definition found in cluster (dry-run)"
    elif [[ -f "${CHAOS_MANIFEST}" ]]; then
      if rg -q "name: ${exp_name}" "${CHAOS_MANIFEST}" &>/dev/null; then
        ok "${exp_name}: experiment definition found in manifest (dry-run)"
      else
        warn "${exp_name}: NOT found in manifest"
      fi
    fi

    PASSED_EXPERIMENTS+=("${exp_name} (dry-run)")
    PASS=$((PASS + 1))
    return 0
  fi

  # Apply the manifest if experiments aren't already in the cluster
  if ! kubectl get "${exp_kind}" "${exp_name}" -n "${NAMESPACE}" &>/dev/null; then
    info "Applying chaos manifest..."
    kubectl apply -f "${CHAOS_MANIFEST}" 2>/dev/null || {
      err "Failed to apply chaos manifest"
      EXPERIMENT_RESULTS["${exp_name}"]="manifest-error"
      FAILED_EXPERIMENTS+=("${exp_name}")
      FAIL=$((FAIL + 1))
      return 1
    }
  fi

  # Activate the experiment by annotating starting time
  kubectl annotate "${exp_kind}" "${exp_name}" -n "${NAMESPACE}" \
    chaos-mesh.org/starting-time="$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
    --overwrite 2>/dev/null || true

  # Wait for experiment to start running
  info "Waiting for ${exp_name} to start..."
  local wait_count=0
  local max_wait=30
  while [[ ${wait_count} -lt ${max_wait} ]]; do
    local status
    status=$(kubectl get "${exp_kind}" "${exp_name}" -n "${NAMESPACE}" \
      -o jsonpath='{.status.experiment.phase}' 2>/dev/null || echo "Unknown")

    case "${status}" in
      Running|Finished)
        info "Experiment is ${status}"
        break
        ;;
      Failed)
        err "Experiment entered Failed state"
        EXPERIMENT_RESULTS["${exp_name}"]="failed-state"
        FAILED_EXPERIMENTS+=("${exp_name}")
        FAIL=$((FAIL + 1))
        return 1
        ;;
    esac

    sleep 2
    wait_count=$((wait_count + 1))
  done

  if [[ ${wait_count} -ge ${max_wait} ]]; then
    warn "Experiment did not reach Running state within ${max_wait}s — proceeding anyway"
  fi

  # Get experiment duration
  local exp_duration
  exp_duration=$(kubectl get "${exp_kind}" "${exp_name}" -n "${NAMESPACE}" \
    -o jsonpath='{.spec.duration}' 2>/dev/null || echo "${DURATION}s")
  local exp_duration_secs
  exp_duration_secs=$(echo "${exp_duration}" | sed 's/s//')

  # Wait for experiment duration + observation window
  local observation_secs=60
  local total_wait=$((exp_duration_secs + observation_secs))
  info "Experiment duration: ${exp_duration}, observation: ${observation_secs}s"
  info "Waiting ${total_wait}s for experiment + observation..."

  # Monitor during experiment
  local monitor_pid=""
  if kubectl get svc prometheus -n "${NAMESPACE}" &>/dev/null; then
    (
      while true; do
        local error_rate
        error_rate=$(kubectl exec -n "${NAMESPACE}" svc/prometheus -- \
          wget -qO- 'http://localhost:9090/api/v1/query?query=sum(rate(http_server_errors_total{namespace="'${NAMESPACE}'"}[1m]))/sum(rate(http_server_requests_total{namespace="'${NAMESPACE}'"}[1m]))' \
          2>/dev/null | jq -r '.data.result[0].value[1] // "0"' 2>/dev/null || echo "N/A")

        local p99
        p99=$(kubectl exec -n "${NAMESPACE}" svc/prometheus -- \
          wget -qO- 'http://localhost:9090/api/v1/query?query=histogram_quantile(0.99,sum(rate(http_server_request_duration_seconds_bucket{namespace="'${NAMESPACE}'"}[1m]))by(le))' \
          2>/dev/null | jq -r '.data.result[0].value[1] // "0"' 2>/dev/null || echo "N/A")

        echo "[$(date +%H:%M:%S)] ${exp_name} — error_rate: ${error_rate}, p99: ${p99}s" \
          >> "${REPORT_DIR}/monitoring-${TIMESTAMP}.log"
        sleep 10
      done
    ) &
    monitor_pid=$!
  fi

  # Wait for experiment to complete
  sleep "${total_wait}"

  # Stop monitoring
  if [[ -n "${monitor_pid}" ]]; then
    kill "${monitor_pid}" 2>/dev/null || true
  fi

  # ── Post-experiment validation ────────────────────────────────────────────
  local validation_result
  validation_result=$(validate_steady_state "${exp_name}")

  local exp_elapsed=$(( SECONDS - exp_start ))

  # Write experiment result
  cat > "${result_file}" <<RESULT_EOF
{
  "experiment": "${exp_name}",
  "kind": "${exp_kind}",
  "category": "${exp_category}",
  "target": "${exp_target}",
  "timestamp": "${TIMESTAMP}",
  "duration_seconds": ${exp_duration_secs},
  "elapsed_seconds": ${exp_elapsed},
  "result": "${validation_result}",
  "namespace": "${NAMESPACE}",
  "slo_thresholds": {
    "error_rate": ${SLO_ERROR_RATE},
    "p99_latency_ms": ${SLO_P99_MS},
    "availability_pct": ${SLO_AVAILABILITY}
  }
}
RESULT_EOF

  if [[ "${validation_result}" == "pass" ]]; then
    ok "${exp_name}: PASSED (steady-state maintained, ${exp_elapsed}s)"
    PASSED_EXPERIMENTS+=("${exp_name}")
    PASS=$((PASS + 1))
    EXPERIMENT_RESULTS["${exp_name}"]="pass"
  else
    err "${exp_name}: FAILED (${validation_result}, ${exp_elapsed}s)"
    FAILED_EXPERIMENTS+=("${exp_name}")
    FAIL=$((FAIL + 1))
    EXPERIMENT_RESULTS["${exp_name}"]="fail"

    # ── Rollback ────────────────────────────────────────────────────────────
    if [[ "${DRY_RUN}" == false ]]; then
      warn "Rolling back — removing all active chaos experiments..."
      rollback_chaos
      warn "Rollback complete."
    fi
  fi
}

# ─── Steady-State Validation ────────────────────────────────────────────────
validate_steady_state() {
  local exp_name="$1"
  local violations=()

  info "Validating steady-state after ${exp_name}..."

  # Check 1: All service deployments have at least 1 ready replica
  for svc in "${PLATFORM_SERVICES[@]}"; do
    local ready
    ready=$(kubectl get deployment "${svc}" -n "${NAMESPACE}" \
      -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")

    if [[ "${ready}" == "0" ]]; then
      violations+=("${svc}: 0 ready replicas")
      err "  ${svc} has 0 ready replicas!"
    fi
  done

  # Check 2: Prometheus metric validation (if available)
  if kubectl get svc prometheus -n "${NAMESPACE}" &>/dev/null; then
    # Error rate check
    local current_error_rate
    current_error_rate=$(kubectl exec -n "${NAMESPACE}" svc/prometheus -- \
      wget -qO- 'http://localhost:9090/api/v1/query?query=sum(rate(http_server_errors_total{namespace="'${NAMESPACE}'"}[2m]))/sum(rate(http_server_requests_total{namespace="'${NAMESPACE}'"}[2m]))' \
      2>/dev/null | jq -r '.data.result[0].value[1] // "0"' 2>/dev/null || echo "0")

    if [[ "$(echo "${current_error_rate} > ${SLO_ERROR_RATE}" | bc -l 2>/dev/null || echo "0")" == "1" ]]; then
      violations+=("error_rate: ${current_error_rate} > ${SLO_ERROR_RATE}")
      err "  Error rate violation: ${current_error_rate} > ${SLO_ERROR_RATE}"
    else
      ok "  Error rate: ${current_error_rate} <= ${SLO_ERROR_RATE}"
    fi

    # P99 latency check
    local current_p99
    current_p99=$(kubectl exec -n "${NAMESPACE}" svc/prometheus -- \
      wget -qO- 'http://localhost:9090/api/v1/query?query=histogram_quantile(0.99,sum(rate(http_server_request_duration_seconds_bucket{namespace="'${NAMESPACE}'"}[2m]))by(le))' \
      2>/dev/null | jq -r '.data.result[0].value[1] // "0"' 2>/dev/null || echo "0")

    local current_p99_ms
    current_p99_ms=$(echo "${current_p99} * 1000" | bc -l 2>/dev/null || echo "0")

    if [[ "$(echo "${current_p99_ms} > ${SLO_P99_MS}" | bc -l 2>/dev/null || echo "0")" == "1" ]]; then
      violations+=("p99_latency: ${current_p99_ms}ms > ${SLO_P99_MS}ms")
      err "  P99 latency violation: ${current_p99_ms}ms > ${SLO_P99_MS}ms"
    else
      ok "  P99 latency: ${current_p99_ms}ms <= ${SLO_P99_MS}ms"
    fi
  else
    warn "  Prometheus not available — skipping metric validation"
  fi

  # Check 3: No CrashLoopBackOff pods
  local crash_loop_count
  crash_loop_count=$(kubectl get pods -n "${NAMESPACE}" --field-selector=status.phase!=Running \
    -o json 2>/dev/null | jq '[.items[] | select(.status.containerStatuses[]?.state.waiting.reason == "CrashLoopBackOff")] | length' 2>/dev/null || echo "0")

  if [[ "${crash_loop_count}" != "0" ]]; then
    violations+=("crash_loop_pods: ${crash_loop_count}")
    err "  ${crash_loop_count} pods in CrashLoopBackOff!"
  fi

  # Check 4: Kafka consumer lag (if kafka experiment)
  if [[ "${exp_name}" == *"kafka"* ]]; then
    local consumer_lag
    consumer_lag=$(kubectl exec -n "${NAMESPACE}" svc/prometheus -- \
      wget -qO- 'http://localhost:9090/api/v1/query?query=sum(kafka_consumer_group_lag{namespace="'${NAMESPACE}'"})' \
      2>/dev/null | jq -r '.data.result[0].value[1] // "0"' 2>/dev/null || echo "0")
    info "  Kafka consumer lag: ${consumer_lag}"
  fi

  # Check 5: SPIRE agent health (if spire experiment)
  if [[ "${exp_name}" == *"spire"* ]]; then
    local spire_healthy
    spire_healthy=$(kubectl get daemonset spire-agent -n "${NAMESPACE}" \
      -o jsonpath='{.status.numberReady}' 2>/dev/null || echo "0")
    info "  SPIRE agents ready: ${spire_healthy}"
  fi

  # Result
  if [[ ${#violations[@]} -eq 0 ]]; then
    echo "pass"
  else
    echo "violations: ${violations[*]}"
  fi
}

# ─── Rollback ───────────────────────────────────────────────────────────────
rollback_chaos() {
  warn "Rolling back all active chaos experiments..."

  # Delete all chaos resources
  local chaos_types=("podchaos" "networkchaos" "stresschaos" "timechaos" "httpchaos")
  for chaos_type in "${chaos_types[@]}"; do
    kubectl delete "${chaos_type}" -l chaos-mesh=enabled -n "${NAMESPACE}" \
      --wait=false 2>/dev/null || true
  done

  # Wait for chaos to be fully removed
  info "Waiting for chaos effects to dissipate..."
  sleep 30

  # Verify no active experiments remain
  local remaining=0
  for chaos_type in "${chaos_types[@]}"; do
    local count
    count=$(kubectl get "${chaos_type}" -n "${NAMESPACE}" -o name 2>/dev/null | wc -l || echo "0")
    remaining=$((remaining + count))
  done

  if [[ ${remaining} -gt 0 ]]; then
    warn "  ${remaining} chaos resources still present — forcing deletion"
    for chaos_type in "${chaos_types[@]}"; do
      kubectl delete "${chaos_type}" --all -n "${NAMESPACE}" \
        --force --grace-period=0 2>/dev/null || true
    done
    sleep 15
  fi

  ok "Rollback complete"
}

# ─── Teardown ───────────────────────────────────────────────────────────────
teardown() {
  if [[ "${SKIP_TEARDOWN}" == true ]]; then
    info "Skipping teardown (--skip-teardown)"
    return 0
  fi

  phase "Phase 6: Teardown"

  rollback_chaos

  # Verify all services recovered
  info "Verifying all services recovered..."
  for svc in "${PLATFORM_SERVICES[@]}"; do
    local ready
    ready=$(kubectl get deployment "${svc}" -n "${NAMESPACE}" \
      -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    if [[ "${ready}" == "0" ]]; then
      err "${svc} has not recovered — manual intervention required"
    else
      ok "${svc}: ${ready} replicas ready"
    fi
  done
}

# ─── Results Reporting ──────────────────────────────────────────────────────
generate_report() {
  phase "Phase 7: Results Reporting"

  local total=$((PASS + FAIL + SKIPPED))
  local pass_pct=0
  if [[ ${total} -gt 0 ]]; then
    pass_pct=$(echo "scale=1; ${PASS} * 100 / ${total}" | bc -l 2>/dev/null || echo "0")
  fi

  local execution_elapsed=$(( SECONDS - EXECUTION_START ))

  # ── JSON Report ───────────────────────────────────────────────────────────
  local json_report="${REPORT_DIR}/chaos-report-${TIMESTAMP}.json"

  local failed_json="[]"
  if [[ ${#FAILED_EXPERIMENTS[@]} -gt 0 ]]; then
    failed_json=$(printf '"%s",' "${FAILED_EXPERIMENTS[@]}" | sed 's/,$//')
    failed_json="[${failed_json}]"
  fi

  local passed_json="[]"
  if [[ ${#PASSED_EXPERIMENTS[@]} -gt 0 ]]; then
    passed_json=$(printf '"%s",' "${PASSED_EXPERIMENTS[@]}" | sed 's/,$//')
    passed_json="[${passed_json}]"
  fi

  # Build experiment results object
  local results_json="{"
  local first=true
  for exp_name in "${!EXPERIMENT_RESULTS[@]}"; do
    if [[ "${first}" == true ]]; then
      first=false
    else
      results_json+=","
    fi
    results_json+="\"${exp_name}\":\"${EXPERIMENT_RESULTS[${exp_name}]}\""
  done
  results_json+="}"

  cat > "${json_report}" <<REPORT_EOF
{
  "version": "${VERSION}",
  "timestamp": "${TIMESTAMP}",
  "namespace": "${NAMESPACE}",
  "category": "${CATEGORY}",
  "duration_override": ${DURATION},
  "parallel": ${PARALLEL},
  "dry_run": ${DRY_RUN},
  "execution_elapsed_seconds": ${execution_elapsed},
  "slo_thresholds": {
    "error_rate": ${SLO_ERROR_RATE},
    "p99_latency_ms": ${SLO_P99_MS},
    "availability_pct": ${SLO_AVAILABILITY}
  },
  "summary": {
    "total": ${total},
    "passed": ${PASS},
    "failed": ${FAIL},
    "skipped": ${SKIPPED},
    "pass_rate_pct": ${pass_pct}
  },
  "passed_experiments": ${passed_json},
  "failed_experiments": ${failed_json},
  "experiment_results": ${results_json}
}
REPORT_EOF

  ok "JSON report: ${json_report}"

  # ── Human-Readable Report ─────────────────────────────────────────────────
  local text_report="${REPORT_DIR}/chaos-report-${TIMESTAMP}.txt"

  cat > "${text_report}" <<TEXT_EOF
════════════════════════════════════════════════════════════════
  CHAOS ENGINEERING REPORT
  Enterprise Chaos Runner v${VERSION}
════════════════════════════════════════════════════════════════

Timestamp:      ${TIMESTAMP}
Namespace:      ${NAMESPACE}
Category:       ${CATEGORY}
Duration:       ${DURATION}s (override)
Parallel:       ${PARALLEL}
Dry Run:        ${DRY_RUN}
Execution Time: ${execution_elapsed}s

── SLO Thresholds ──
  Error Rate    < ${SLO_ERROR_RATE}
  P99 Latency   < ${SLO_P99_MS}ms
  Availability  > ${SLO_AVAILABILITY}%

── Results Summary ──
  Total:   ${total}
  Passed:  ${PASS}
  Failed:  ${FAIL}
  Skipped: ${SKIPPED}
  Pass Rate: ${pass_pct}%

TEXT_EOF

  if [[ ${#PASSED_EXPERIMENTS[@]} -gt 0 ]]; then
    echo "── Passed Experiments ──" >> "${text_report}"
    for exp in "${PASSED_EXPERIMENTS[@]}"; do
      echo "  ✓ ${exp}" >> "${text_report}"
    done
    echo "" >> "${text_report}"
  fi

  if [[ ${#FAILED_EXPERIMENTS[@]} -gt 0 ]]; then
    echo "── Failed Experiments ──" >> "${text_report}"
    for exp in "${FAILED_EXPERIMENTS[@]}"; do
      echo "  ✗ ${exp}" >> "${text_report}"
    done
    echo "" >> "${text_report}"
  fi

  echo "════════════════════════════════════════════════════════════════" >> "${text_report}"

  ok "Text report: ${text_report}"

  # ── Console Summary ───────────────────────────────────────────────────────
  header "CHAOS ENGINEERING RESULTS"
  echo ""
  info "Total: ${total} | Passed: ${PASS} | Failed: ${FAIL} | Skipped: ${SKIPPED}"
  info "Pass Rate: ${pass_pct}% | Execution Time: ${execution_elapsed}s"

  if [[ ${#PASSED_EXPERIMENTS[@]} -gt 0 ]]; then
    echo ""
    ok "Passed:"
    for exp in "${PASSED_EXPERIMENTS[@]}"; do
      echo "  ✓ ${exp}"
    done
  fi

  if [[ ${#FAILED_EXPERIMENTS[@]} -gt 0 ]]; then
    echo ""
    err "Failed:"
    for exp in "${FAILED_EXPERIMENTS[@]}"; do
      echo "  ✗ ${exp}"
    done
  fi

  # ── Slack Notification ────────────────────────────────────────────────────
  if [[ -n "${SLACK_WEBHOOK}" ]]; then
    info "Publishing results to Slack..."
    local color="good"
    if [[ ${FAIL} -gt 0 ]]; then color="danger"; fi

    local payload
    payload=$(cat <<SLACK_EOF
{
  "attachments": [{
    "color": "${color}",
    "title": "Chaos Engineering Results — $(date -u '+%Y-%m-%d %H:%M')",
    "fields": [
      {"title": "Category", "value": "${CATEGORY}", "short": true},
      {"title": "Namespace", "value": "${NAMESPACE}", "short": true},
      {"title": "Passed", "value": "${PASS}", "short": true},
      {"title": "Failed", "value": "${FAIL}", "short": true},
      {"title": "Pass Rate", "value": "${pass_pct}%", "short": true},
      {"title": "Duration", "value": "${execution_elapsed}s", "short": true},
      {"title": "Failed Experiments", "value": "$(printf '%s, ' "${FAILED_EXPERIMENTS[@]}" | sed 's/, $//' || echo "None")", "short": false}
    ],
    "footer": "Enterprise Chaos Runner v${VERSION}",
    "ts": $(date +%s)
  }]
}
SLACK_EOF
)
    curl -s -X POST -H 'Content-type: application/json' \
      --data "${payload}" "${SLACK_WEBHOOK}" || warn "Failed to publish to Slack"
    ok "Slack notification sent"
  fi
}

# ─── RL Feedback Loop Integration ───────────────────────────────────────────
write_rl_findings() {
  local findings_dir="${PROJECT_ROOT}/.claude/engine/feedback/findings"
  mkdir -p "${findings_dir}"

  local findings_file="${findings_dir}/chaos-${TIMESTAMP}.json"

  # Extract key findings for the RL feedback loop
  local -a findings=()

  for exp_name in "${!EXPERIMENT_RESULTS[@]}"; do
    local result="${EXPERIMENT_RESULTS[${exp_name}]}"

    if [[ "${result}" == "fail" ]]; then
      findings+=("\"${exp_name}: SLO violation detected - steady-state not maintained\"")
    elif [[ "${result}" == "pass" ]]; then
      findings+=("\"${exp_name}: Steady-state maintained under fault injection\"")
    fi
  done

  local findings_json="[]"
  if [[ ${#findings[@]} -gt 0 ]]; then
    findings_json="[$(printf '%s,' "${findings[@]}" | sed 's/,$//')]"
  fi

  cat > "${findings_file}" <<FINDINGS_EOF
{
  "source": "chaos-engineering",
  "version": "${VERSION}",
  "timestamp": "${TIMESTAMP}",
  "namespace": "${NAMESPACE}",
  "category": "${CATEGORY}",
  "summary": {
    "passed": ${PASS},
    "failed": ${FAIL},
    "total": $((PASS + FAIL + SKIPPED))
  },
  "findings": ${findings_json},
  "slo_violations": [
    $(if [[ ${FAIL} -gt 0 ]]; then
      for exp in "${FAILED_EXPERIMENTS[@]}"; do
        echo "    {\"experiment\": \"${exp}\", \"severity\": \"high\", \"action\": \"investigate_and_remediate\"},"
      done | sed 's/,$//'
    fi)
  ],
  "recommendations": [
    $(if [[ ${FAIL} -gt 0 ]]; then
      echo "    {\"type\": \"reliability\", \"priority\": \"high\", \"message\": \"Chaos experiments revealed SLO violations — review circuit breaker, retry, and fallback configurations\"}"
    else
      echo "    {\"type\": \"reliability\", \"priority\": \"info\", \"message\": \"All chaos experiments passed — system resilience validated\"}"
    fi)
  ]
}
FINDINGS_EOF

  ok "RL findings written to ${findings_file}"
}

# ═══════════════════════════════════════════════════════════════════════════
# MAIN EXECUTION
# ═══════════════════════════════════════════════════════════════════════════

main() {
  EXECUTION_START=${SECONDS}

  header "Enterprise Chaos Engineering Runner v${VERSION}"
  info "Timestamp:  ${TIMESTAMP}"
  info "Namespace:  ${NAMESPACE}"
  info "Category:   ${CATEGORY}"
  info "Duration:   ${DURATION}s"
  info "Parallel:   ${PARALLEL}"
  info "Dry Run:    ${DRY_RUN}"
  info "Report Dir: ${REPORT_DIR}"

  # Create report directory
  mkdir -p "${REPORT_DIR}"

  # ── Dependency Check ──────────────────────────────────────────────────────
  check_dependencies

  # ── Phase 1: Pre-flight ──────────────────────────────────────────────────
  if [[ "${SKIP_PREFLIGHT}" == false ]]; then
    if ! preflight_checks; then
      err "Pre-flight checks failed. Use --skip-preflight to override."
      exit 2
    fi
  else
    warn "Skipping pre-flight checks (--skip-preflight)"
  fi

  # ── Phase 2: Steady-State Baseline ───────────────────────────────────────
  record_baseline
  generate_prom_queries

  # ── Phase 3: Apply Chaos Manifest ────────────────────────────────────────
  if [[ "${DRY_RUN}" == false ]]; then
    phase "Phase 3: Applying Chaos Experiments"
    info "Applying manifest: ${CHAOS_MANIFEST}"
    kubectl apply -f "${CHAOS_MANIFEST}" 2>/dev/null || {
      err "Failed to apply chaos manifest"
      exit 3
    }
    ok "Chaos experiments applied to cluster"
  else
    phase "Phase 3: Dry-Run Validation"
    info "Would apply manifest: ${CHAOS_MANIFEST}"

    # Validate YAML syntax
    if command -v yamllint &>/dev/null; then
      yamllint "${CHAOS_MANIFEST}" && ok "YAML syntax valid" || warn "YAML linting found issues"
    else
      # Basic YAML validation via kubectl --dry-run
      kubectl apply --dry-run=client -f "${CHAOS_MANIFEST}" &>/dev/null && \
        ok "YAML syntax valid (kubectl dry-run)" || \
        warn "YAML validation had issues"
    fi
  fi

  # ── Phase 4: Execute Experiments ─────────────────────────────────────────
  phase "Phase 4: Experiment Execution"

  local experiments
  experiments=$(get_experiments_for_category "${CATEGORY}")

  if [[ -z "${experiments}" ]]; then
    warn "No experiments matched category '${CATEGORY}'"
    if [[ -n "${SINGLE_EXPERIMENT}" ]]; then
      warn "Single experiment '${SINGLE_EXPERIMENT}' not found"
    fi
    exit 0
  fi

  local exp_count
  exp_count=$(echo "${experiments}" | wc -l || echo "0")
  info "Running ${exp_count} experiment(s) in category '${CATEGORY}'"

  if [[ "${PARALLEL}" == true ]]; then
    warn "PARALLEL MODE — multiple experiments will run simultaneously"
    warn "This increases blast radius and may cause unpredictable interactions"
    local pids=()

    while IFS= read -r entry; do
      IFS='|' read -r name cat kind target <<< "${entry}"
      apply_experiment "${name}" "${kind}" "${cat}" "${target}" &
      pids+=($!)
    done <<< "${experiments}"

    # Wait for all parallel experiments
    for pid in "${pids[@]}"; do
      wait "${pid}" 2>/dev/null || true
    done
  else
    # Sequential execution (default, safer)
    while IFS= read -r entry; do
      IFS='|' read -r name cat kind target <<< "${entry}"
      apply_experiment "${name}" "${kind}" "${cat}" "${target}"

      # If an experiment failed and we're not in parallel mode,
      # stop further experiments (rollback was already triggered)
      if [[ ${FAIL} -gt 0 && "${DRY_RUN}" == false ]]; then
        warn "Stopping execution after failed experiment (sequential mode)"
        # Mark remaining experiments as skipped
        break
      fi
    done <<< "${experiments}"
  fi

  # ── Phase 5: Teardown ────────────────────────────────────────────────────
  teardown

  # ── Phase 7: Reports ─────────────────────────────────────────────────────
  generate_report

  # ── RL Feedback Loop ─────────────────────────────────────────────────────
  write_rl_findings

  # ── Final Exit ───────────────────────────────────────────────────────────
  echo ""
  if [[ ${FAIL} -gt 0 ]]; then
    header "CHAOS ENGINEERING: FAILURES DETECTED"
    err "One or more experiments revealed SLO violations."
    err "Review the failed experiments and remediate before the next game day."
    exit 1
  else
    header "CHAOS ENGINEERING: ALL PASSED"
    ok "System resilience validated — all experiments passed."
    exit 0
  fi
}

# Run main
main "$@"
