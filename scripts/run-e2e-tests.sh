#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# E2E Test Runner — Polyglot Microservices Platform
# ---------------------------------------------------------------------------
# Comprehensive end-to-end test runner that:
#   - Starts a kind cluster if not running
#   - Deploys all services using kustomize production overlay
#   - Waits for all services to be healthy
#   - Runs SPIRE initialization and workload registration
#   - Seeds test data
#   - Runs the E2E test suite with pytest
#   - Collects results and generates HTML report
#   - Cleans up the kind cluster on exit
#
# Usage:
#   ./scripts/run-e2e-tests.sh [OPTIONS]
#
# Options:
#   --suite SUITE      Run specific test suite (saga|cdc|discovery|observability|resilience|security|all) [default: all]
#   --cluster NAME     Kind cluster name [default: polyglot-e2e]
#   --namespace NS     Kubernetes namespace [default: production]
#   --timeout SECS     Per-test timeout in seconds [default: 300]
#   --parallel N       Number of parallel test workers [default: 1]
#   --keep-cluster     Keep kind cluster after tests (for debugging)
#   --skip-deploy      Skip cluster creation and deployment (use existing)
#   --skip-seed        Skip test data seeding
#   --verbose          Enable verbose output
#   --offline-only     Run only offline/manifest validation tests
#   -h, --help         Show this help message
#
# Exit codes:
#   0 — All E2E tests passed
#   1 — One or more E2E tests failed
#   2 — Setup/deployment failure
# ---------------------------------------------------------------------------
set -euo pipefail

# --- Defaults ---
SUITE="all"
CLUSTER_NAME="polyglot-e2e"
NAMESPACE="production"
TIMEOUT=300
PARALLEL=1
KEEP_CLUSTER=false
SKIP_DEPLOY=false
SKIP_SEED=false
VERBOSE=""
OFFLINE_ONLY=false

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RESULTS_DIR="${PROJECT_ROOT}/test-results/e2e"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
KUSTOMIZE_DIR="${PROJECT_ROOT}/infra/kubernetes/overlays/production"

# --- Parse args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --suite)         SUITE="$2"; shift 2 ;;
    --cluster)       CLUSTER_NAME="$2"; shift 2 ;;
    --namespace)     NAMESPACE="$2"; shift 2 ;;
    --timeout)       TIMEOUT="$2"; shift 2 ;;
    --parallel)      PARALLEL="$2"; shift 2 ;;
    --keep-cluster)  KEEP_CLUSTER=true; shift ;;
    --skip-deploy)   SKIP_DEPLOY=true; shift ;;
    --skip-seed)     SKIP_SEED=true; shift ;;
    --verbose)       VERBOSE="-v"; shift ;;
    --offline-only)  OFFLINE_ONLY=true; shift ;;
    -h|--help)
      sed -n '3,30p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

echo "============================================================"
echo "  E2E Test Runner — Polyglot Microservices Platform"
echo "  Suite:       ${SUITE}"
echo "  Cluster:     ${CLUSTER_NAME}"
echo "  Namespace:   ${NAMESPACE}"
echo "  Timeout:     ${TIMEOUT}s"
echo "  Parallel:    ${PARALLEL}"
echo "  Timestamp:   ${TIMESTAMP}"
echo "  Keep Cluster: ${KEEP_CLUSTER}"
echo "  Skip Deploy:  ${SKIP_DEPLOY}"
echo "  Offline Only: ${OFFLINE_ONLY}"
echo "============================================================"

mkdir -p "${RESULTS_DIR}"

# --- Cleanup function ---
cleanup() {
  local exit_code=$?
  if [[ "${KEEP_CLUSTER}" != "true" && "${SKIP_DEPLOY}" != "true" ]]; then
    echo ""
    echo "--- Cleanup: Destroying kind cluster ---"
    kind delete cluster --name "${CLUSTER_NAME}" 2>/dev/null || true
  fi
  echo ""
  if [[ ${exit_code} -eq 0 ]]; then
    echo "  E2E Tests: ALL PASSED"
  else
    echo "  E2E Tests: FAILED (exit code ${exit_code})"
  fi
  echo "  Results: ${RESULTS_DIR}/"
  exit ${exit_code}
}
trap cleanup EXIT

# --- Step 1: Start kind cluster ---
if [[ "${SKIP_DEPLOY}" != "true" ]]; then
  echo ""
  echo "--- Step 1: Start kind cluster ---"

  if kind get clusters 2>/dev/null | grep -q "${CLUSTER_NAME}"; then
    echo "  Cluster '${CLUSTER_NAME}' already exists, reusing..."
  else
    echo "  Creating kind cluster '${CLUSTER_NAME}'..."
    kind create cluster \
      --name "${CLUSTER_NAME}" \
      --image kindest/node:v1.29.2 \
      --wait 120s \
      --config=- <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: ${CLUSTER_NAME}
nodes:
  - role: control-plane
    kubeadmConfigPatches:
      - |
        kind: InitConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            node-labels: "ingress-ready=true"
    extraPortMappings:
      - containerPort: 80
        hostPort: 80
        protocol: TCP
      - containerPort: 443
        hostPort: 443
        protocol: TCP
  - role: worker
  - role: worker
EOF
    echo "  Kind cluster created successfully"
  fi

  # Set kubectl context
  kubectl config set-context --current --namespace="${NAMESPACE}" 2>/dev/null || true
fi

# --- Step 2: Deploy all services ---
if [[ "${SKIP_DEPLOY}" != "true" ]]; then
  echo ""
  echo "--- Step 2: Deploy all services ---"

  # Apply base infrastructure first
  echo "  Deploying base infrastructure..."
  kubectl apply -k "${PROJECT_ROOT}/infra/kubernetes/base/" --wait=true 2>/dev/null || {
    echo "  WARNING: Base infrastructure deployment had issues, continuing..."
  }

  # Apply platform components (OTel, SPIRE, Kafka, Debezium)
  echo "  Deploying platform components..."
  kubectl apply -k "${PROJECT_ROOT}/infra/kubernetes/platform/" --wait=true 2>/dev/null || {
    echo "  WARNING: Platform components deployment had issues, continuing..."
  }

  # Apply production overlay (services + resource budgets)
  echo "  Deploying production overlay with all services..."
  kubectl apply -k "${KUSTOMIZE_DIR}" --wait=true 2>/dev/null || {
    echo "  WARNING: Production overlay deployment had issues, continuing..."
  }

  echo "  All manifests applied"
fi

# --- Step 3: Wait for all services to be healthy ---
if [[ "${SKIP_DEPLOY}" != "true" ]]; then
  echo ""
  echo "--- Step 3: Wait for service readiness ---"

  SERVICES=(
    "gateway" "identity" "catalog" "order" "payment"
    "notification" "analytics" "rl-engine" "schema-registry"
  )

  PLATFORM_COMPONENTS=(
    "spire-server" "spire-agent" "otel-collector"
    "kafka" "debezium" "prometheus" "tempo" "loki" "grafana"
  )

  wait_for_deployment() {
    local name="$1"
    local timeout=180
    local interval=10
    local elapsed=0

    echo -n "  [WAIT] ${name} ... "
    while [[ ${elapsed} -lt ${timeout} ]]; do
      if kubectl -n "${NAMESPACE}" get deployment "${name}" -o jsonpath='{.status.readyReplicas}' 2>/dev/null | grep -qE '^[1-9]'; then
        echo "READY"
        return 0
      fi
      sleep ${interval}
      elapsed=$((elapsed + interval))
    done
    echo "TIMEOUT"
    return 1
  }

  # Wait for platform components first
  for svc in "${PLATFORM_COMPONENTS[@]}"; do
    wait_for_deployment "${svc}" || echo "  WARNING: ${svc} not ready within timeout"
  done

  # Wait for application services
  for svc in "${SERVICES[@]}"; do
    wait_for_deployment "${svc}" || echo "  WARNING: ${svc} not ready within timeout"
  done

  echo "  Service readiness check complete"
fi

# --- Step 4: SPIRE initialization and workload registration ---
if [[ "${SKIP_DEPLOY}" != "true" ]]; then
  echo ""
  echo "--- Step 4: SPIRE initialization ---"

  # Wait for SPIRE server to be healthy
  echo -n "  Waiting for SPIRE server... "
  for i in $(seq 1 30); do
    if kubectl -n "${NAMESPACE}" exec spire-server-0 -c spire-server -- \
      /opt/spire/bin/spire-server healthcheck 2>/dev/null; then
      echo "HEALTHY"
      break
    fi
    if [[ $i -eq 30 ]]; then
      echo "TIMEOUT"
      echo "  WARNING: SPIRE server not healthy, SVID-based tests may fail"
    fi
    sleep 5
  done

  # Register workloads with SPIRE
  TRUST_DOMAIN="trust.example.org"
  PARENT_ID="spiffe://${TRUST_DOMAIN}/ns/${NAMESPACE}/sa/spire-agent"

  echo "  Registering workload entries..."
  for svc in "${SERVICES[@]}"; do
    SPIFFE_ID="spiffe://${TRUST_DOMAIN}/ns/${NAMESPACE}/sa/${svc}"
    SELECTOR="k8s:ns:${NAMESPACE},k8s:sa:${svc}"

    # Check if entry already exists
    existing=$(kubectl -n "${NAMESPACE}" exec spire-server-0 -c spire-server -- \
      /opt/spire/bin/spire-server entry show -spiffeID "${SPIFFE_ID}" 2>/dev/null || true)

    if echo "${existing}" | grep -q "Entry ID"; then
      echo "  [SKIP] ${svc} already registered"
    else
      kubectl -n "${NAMESPACE}" exec spire-server-0 -c spire-server -- \
        /opt/spire/bin/spire-server entry create \
        -spiffeID "${SPIFFE_ID}" \
        -parentID "${PARENT_ID}" \
        -selector "${SELECTOR}" \
        -ttl 3600 2>/dev/null && \
        echo "  [OK  ] ${svc} registered" || \
        echo "  [WARN] ${svc} registration failed"
    fi
  done
fi

# --- Step 5: Seed test data ---
if [[ "${SKIP_SEED}" != "true" && "${OFFLINE_ONLY}" != "true" ]]; then
  echo ""
  echo "--- Step 5: Seed test data ---"

  if [[ -f "${SCRIPT_DIR}/seed-test-data.sh" ]]; then
    bash "${SCRIPT_DIR}/seed-test-data.sh" \
      --namespace "${NAMESPACE}" \
      --cluster "${CLUSTER_NAME}" \
      ${VERBOSE}
  else
    echo "  WARNING: seed-test-data.sh not found, skipping data seeding"
  fi
fi

# --- Step 6: Build pytest markers based on suite ---
echo ""
echo "--- Step 6: Configure test suite ---"

MARKER_ARG=""
case "${SUITE}" in
  saga)          MARKER_ARG="-m saga" ;;
  cdc)           MARKER_ARG="-m cdc" ;;
  discovery)     MARKER_ARG="-m discovery" ;;
  observability) MARKER_ARG="-m observability" ;;
  resilience)    MARKER_ARG="-m resilience" ;;
  security)      MARKER_ARG="-m security" ;;
  all)           MARKER_ARG="-m e2e" ;;
  *)             echo "Unknown suite: ${SUITE}"; exit 1 ;;
esac

if [[ "${OFFLINE_ONLY}" == "true" ]]; then
  MARKER_ARG="-m offline"
fi

# Add destructive tests exclusion unless explicitly running resilience/security
if [[ "${SUITE}" != "resilience" && "${SUITE}" != "security" && "${SUITE}" != "all" ]]; then
  MARKER_ARG="${MARKER_ARG} and not destructive"
fi

echo "  Pytest markers: ${MARKER_ARG}"

# --- Step 7: Run E2E tests ---
echo ""
echo "--- Step 7: Run E2E tests ---"

E2E_DIR="${PROJECT_ROOT}/tests/e2e"
REPORT_FILE="${RESULTS_DIR}/e2e-report-${TIMESTAMP}.html"
JUNIT_FILE="${RESULTS_DIR}/e2e-junit-${TIMESTAMP}.xml"
LOG_FILE="${RESULTS_DIR}/e2e-log-${TIMESTAMP}.txt"

# Export environment variables for test configuration
export E2E_NAMESPACE="${NAMESPACE}"
export E2E_CLUSTER_NAME="${CLUSTER_NAME}"
export E2E_TRUST_DOMAIN="trust.example.org"
export E2E_GATEWAY_URL="http://localhost:8080"
export E2E_USE_MTLS="true"

# Run pytest with HTML report and JUnit output
PYTEST_ARGS=(
  "${E2E_DIR}"
  ${MARKER_ARG}
  --timeout="${TIMEOUT}"
  -n "${PARALLEL}"
  --tb=short
  --html="${REPORT_FILE}"
  --self-contained-html
  --junitxml="${JUNIT_FILE}"
  ${VERBOSE}
  --durations=20
  2>&1 | tee "${LOG_FILE}"
)

echo "  Running: pytest ${PYTEST_ARGS[*]}"
echo ""

PYTEST_EXIT=0
python -m pytest "${PYTEST_ARGS[@]}" || PYTEST_EXIT=$?

# --- Step 8: Results summary ---
echo ""
echo "============================================================"
echo "  E2E Test Results"
echo "============================================================"

if [[ -f "${JUNIT_FILE}" ]]; then
  # Parse JUnit results
  TOTAL=$(python3 -c "
import xml.etree.ElementTree as ET
tree = ET.parse('${JUNIT_FILE}')
root = tree.getroot()
ts = root.find('testsuite') if root.find('testsuite') is not None else root
print(ts.get('tests', '0'))" 2>/dev/null || echo "0")

  FAILURES=$(python3 -c "
import xml.etree.ElementTree as ET
tree = ET.parse('${JUNIT_FILE}')
root = tree.getroot()
ts = root.find('testsuite') if root.find('testsuite') is not None else root
print(ts.get('failures', '0'))" 2>/dev/null || echo "0")

  ERRORS=$(python3 -c "
import xml.etree.ElementTree as ET
tree = ET.parse('${JUNIT_FILE}')
root = tree.getroot()
ts = root.find('testsuite') if root.find('testsuite') is not None else root
print(ts.get('errors', '0'))" 2>/dev/null || echo "0")

  SKIPPED=$(python3 -c "
import xml.etree.ElementTree as ET
tree = ET.parse('${JUNIT_FILE}')
root = tree.getroot()
ts = root.find('testsuite') if root.find('testsuite') is not None else root
print(ts.get('skipped', '0'))" 2>/dev/null || echo "0")

  PASSED=$((TOTAL - FAILURES - ERRORS - SKIPPED))

  echo "  Total:   ${TOTAL}"
  echo "  Passed:  ${PASSED}"
  echo "  Failed:  ${FAILURES}"
  echo "  Errors:  ${ERRORS}"
  echo "  Skipped: ${SKIPPED}"
else
  echo "  No JUnit results file found"
  PASSED=0
  FAILURES=0
fi

echo ""
echo "  HTML Report: ${REPORT_FILE}"
echo "  JUnit XML:   ${JUNIT_FILE}"
echo "  Log File:    ${LOG_FILE}"
echo "============================================================"

if [[ ${PYTEST_EXIT} -ne 0 ]]; then
  echo ""
  echo "  E2E TESTS FAILED"
  exit 1
fi

echo ""
echo "  E2E TESTS PASSED"
exit 0
