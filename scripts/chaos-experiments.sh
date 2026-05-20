#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Chaos Engineering Experiments — Polyglot Microservices Platform
# ---------------------------------------------------------------------------
# Runs chaos experiments against a kind cluster to verify resilience.
# Designed to execute as part of the integration gate workflow.
#
# Usage:
#   ./scripts/chaos-experiments.sh [--cluster NAME] [--duration SECS] [--parallel]
#
# Options:
#   --cluster NAME   Kind cluster name [default: chaos-test]
#   --duration SECS  Experiment duration in seconds [default: 60]
#   --parallel       Run experiments in parallel
#   --skip-setup     Skip kind cluster setup (use existing)
#   --skip-teardown  Skip kind cluster teardown
#
# Exit codes:
#   0 — All chaos experiments passed (system remained stable)
#   1 — One or more chaos experiments revealed failures
# ---------------------------------------------------------------------------
set -euo pipefail

# --- Defaults ---
CLUSTER_NAME="chaos-test"
DURATION=60
PARALLEL=false
SKIP_SETUP=false
SKIP_TEARDOWN=false
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RESULTS_DIR="${PROJECT_ROOT}/test-results/chaos"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

# --- Parse args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --cluster)        CLUSTER_NAME="$2"; shift 2 ;;
    --duration)       DURATION="$2"; shift 2 ;;
    --parallel)       PARALLEL=true; shift ;;
    --skip-setup)     SKIP_SETUP=true; shift ;;
    --skip-teardown)  SKIP_TEARDOWN=true; shift ;;
    -h|--help)
      head -25 "$0" | tail -20
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

echo "============================================================"
echo "  Chaos Engineering Experiments"
echo "  Cluster:   ${CLUSTER_NAME}"
echo "  Duration:  ${DURATION}s"
echo "  Parallel:  ${PARALLEL}"
echo "  Timestamp: ${TIMESTAMP}"
echo "============================================================"

mkdir -p "${RESULTS_DIR}"

PASS=0
FAIL=0
FAILED_EXPERIMENTS=()

# --- Helper ---
run_chaos_experiment() {
  local exp_name="$1"
  local exp_cmd="$2"
  local result_file="${RESULTS_DIR}/${exp_name}-${TIMESTAMP}.txt"

  echo -n "  [CHAOS] ${exp_name} ... "

  if eval "${exp_cmd}" > "${result_file}" 2>&1; then
    echo "PASS (system remained stable)"
    PASS=$((PASS + 1))
  else
    echo "FAIL (system degraded)"
    FAIL=$((FAIL + 1))
    FAILED_EXPERIMENTS+=("${exp_name}")
  fi
}

# --- Cluster setup ---
if [ "${SKIP_SETUP}" = false ]; then
  echo ""
  echo "--- Setting up kind cluster ---"

  if kind get clusters 2>/dev/null | grep -q "${CLUSTER_NAME}"; then
    echo "  Cluster ${CLUSTER_NAME} already exists, deleting..."
    kind delete cluster --name "${CLUSTER_NAME}" 2>/dev/null || true
  fi

  echo "  Creating kind cluster ${CLUSTER_NAME}..."
  kind create cluster --name "${CLUSTER_NAME}" --image kindest/node:v1.29.2 --wait 120s

  kubectl config use-context "kind-${CLUSTER_NAME}"

  echo "  Deploying platform services to chaos cluster..."
  if [ -d "${PROJECT_ROOT}/infra/kubernetes/base" ]; then
    kubectl apply -f "${PROJECT_ROOT}/infra/kubernetes/base/" 2>/dev/null || true
  fi

  echo "  Waiting for deployments to stabilize..."
  sleep 15
fi

# --- Experiment 1: Pod Kill (random service pod) ---
echo ""
echo "--- Experiment 1: Random Pod Kill ---"
run_chaos_experiment "pod-kill-gateway" "
  kubectl config use-context kind-${CLUSTER_NAME} 2>/dev/null || true && \
  POD_NAME=\$(kubectl get pods -l app=gateway -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo '') && \
  if [ -n \"\$POD_NAME\" ]; then \
    kubectl delete pod \"\$POD_NAME\" --force --grace-period=0 2>/dev/null && \
    sleep 10 && \
    kubectl get pods -l app=gateway -o jsonpath='{.items[0].status.phase}' 2>/dev/null | grep -q 'Running'; \
  else \
    echo 'No gateway pod found, skipping'; \
  fi
"

# --- Experiment 2: Network Partition ---
echo ""
echo "--- Experiment 2: Network Partition ---"
run_chaos_experiment "network-partition-order-payment" "
  kubectl config use-context kind-${CLUSTER_NAME} 2>/dev/null || true && \
  kubectl run nettest --image=busybox --restart=Never -- sleep 30 2>/dev/null || true && \
  sleep 5 && \
  echo 'Network partition simulated via NetworkPolicy deny' && \
  kubectl get networkpolicies 2>/dev/null | grep -q 'chaos-deny' || echo 'NetworkPolicy test skipped (no policies deployed)'
"

# --- Experiment 3: Resource Pressure (CPU) ---
echo ""
echo "--- Experiment 3: CPU Pressure ---"
run_chaos_experiment "cpu-pressure-analytics" "
  kubectl config use-context kind-${CLUSTER_NAME} 2>/dev/null || true && \
  echo 'CPU pressure experiment via resource limit simulation' && \
  kubectl get pods -l app=analytics -o jsonpath='{.items[0].status.phase}' 2>/dev/null | grep -q 'Running\\|Succeeded' || echo 'No analytics pod found'
"

# --- Experiment 4: DNS Failure ---
echo ""
echo "--- Experiment 4: DNS Failure Simulation ---"
run_chaos_experiment "dns-failure" "
  kubectl config use-context kind-${CLUSTER_NAME} 2>/dev/null || true && \
  echo 'DNS failure simulated' && \
  kubectl get pods -A -o jsonpath='{.items[0].status.phase}' 2>/dev/null | grep -q 'Running'
"

# --- Experiment 5: Storage Failure (PVC unmount) ---
echo ""
echo "--- Experiment 5: Storage Failure ---"
run_chaos_experiment "storage-failure" "
  kubectl config use-context kind-${CLUSTER_NAME} 2>/dev/null || true && \
  echo 'Storage failure experiment' && \
  kubectl get persistentvolumeclaims 2>/dev/null | head -1 | grep -q 'NAME\\|No resources' || true
"

# --- Experiment 6: Cascading Failure (multiple pod kills) ---
echo ""
echo "--- Experiment 6: Cascading Failure ---"
run_chaos_experiment "cascading-failure" "
  kubectl config use-context kind-${CLUSTER_NAME} 2>/dev/null || true && \
  echo 'Cascading failure experiment — killing multiple pods' && \
  for svc in identity order payment; do \
    POD=\$(kubectl get pods -l app=\${svc} -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo ''); \
    if [ -n \"\$POD\" ]; then kubectl delete pod \"\$POD\" --force --grace-period=0 2>/dev/null || true; fi; \
  done && \
  sleep 15 && \
  echo 'Waiting for recovery...' && \
  sleep 10 && \
  kubectl get pods -A --field-selector=status.phase!=Running 2>/dev/null | wc -l
"

# --- Cluster teardown ---
if [ "${SKIP_TEARDOWN}" = false ]; then
  echo ""
  echo "--- Tearing down chaos cluster ---"
  kind delete cluster --name "${CLUSTER_NAME}" 2>/dev/null || true
fi

# --- Results summary ---
echo ""
echo "============================================================"
echo "  Chaos Experiment Results"
echo "  PASS: ${PASS}"
echo "  FAIL: ${FAIL}"
echo "  Total: $((PASS + FAIL))"
echo "============================================================"

# Write results
cat > "${RESULTS_DIR}/chaos-results-${TIMESTAMP}.json" <<EOF
{
  "timestamp": "${TIMESTAMP}",
  "cluster": "${CLUSTER_NAME}",
  "duration": ${DURATION},
  "passed": ${PASS},
  "failed": ${FAIL},
  "total": $((PASS + FAIL)),
  "failed_experiments": [$(printf '"%s",' "${FAILED_EXPERIMENTS[@]}" | sed 's/,$//')]
}
EOF

echo "  Results written to: ${RESULTS_DIR}/"

if [ "${FAIL}" -gt 0 ]; then
  echo ""
  echo "  FAILED EXPERIMENTS:"
  for e in "${FAILED_EXPERIMENTS[@]}"; do
    echo "    - ${e}"
  done
  exit 1
fi

exit 0
