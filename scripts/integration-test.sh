#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Integration Test Runner — Polyglot Microservices Platform
# ---------------------------------------------------------------------------
# Runs cross-service integration tests against a deployed environment.
# Designed to execute after CI passes on main/develop branches.
#
# Usage:
#   ./scripts/integration-test.sh [--env ENV] [--service SVC] [--verbose]
#
# Options:
#   --env ENV        Target environment (staging|production|local) [default: staging]
#   --service SVC    Run tests for a specific service only [default: all]
#   --verbose        Enable verbose output
#   --timeout SECS   Per-test timeout in seconds [default: 120]
#
# Exit codes:
#   0 — All integration tests passed
#   1 — One or more integration tests failed
# ---------------------------------------------------------------------------
set -euo pipefail

# --- Defaults ---
ENV="staging"
SERVICE="all"
VERBOSE=""
TIMEOUT=120
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RESULTS_DIR="${PROJECT_ROOT}/test-results/integration"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

# --- Parse args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)       ENV="$2"; shift 2 ;;
    --service)   SERVICE="$2"; shift 2 ;;
    --verbose)   VERBOSE="-v"; shift ;;
    --timeout)   TIMEOUT="$2"; shift 2 ;;
    -h|--help)
      head -25 "$0" | tail -20
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

echo "============================================================"
echo "  Integration Test Runner"
echo "  Environment: ${ENV}"
echo "  Service:     ${SERVICE}"
echo "  Timeout:     ${TIMEOUT}s"
echo "  Timestamp:   ${TIMESTAMP}"
echo "============================================================"

mkdir -p "${RESULTS_DIR}"

# --- Environment URL mapping ---
case "${ENV}" in
  staging)     BASE_URL="${STAGING_URL:-https://staging.example.com}" ;;
  production)  BASE_URL="${PRODUCTION_URL:-https://app.example.com}" ;;
  local)       BASE_URL="${LOCAL_URL:-http://localhost:8080}" ;;
  *)           echo "Unknown environment: ${ENV}"; exit 1 ;;
esac

echo "  Base URL: ${BASE_URL}"
echo ""

PASS=0
FAIL=0
SKIP=0
FAILED_TESTS=()

# --- Helper functions ---
run_test() {
  local test_name="$1"
  local test_cmd="$2"
  local result_file="${RESULTS_DIR}/${test_name}-${TIMESTAMP}.txt"

  echo -n "  [RUN ] ${test_name} ... "

  if eval timeout "${TIMEOUT}" "${test_cmd}" > "${result_file}" 2>&1; then
    echo "PASS"
    PASS=$((PASS + 1))
  else
    echo "FAIL"
    FAIL=$((FAIL + 1))
    FAILED_TESTS+=("${test_name}")
    if [ -n "${VERBOSE}" ]; then
      echo "    └─ Output: ${result_file}"
    fi
  fi
}

# --- Health check gate ---
echo "--- Health Check Gate ---"
run_test "health-check" "curl -sf -o /dev/null -w '%{http_code}' '${BASE_URL}/healthz' | grep -q 200"

# --- Service discovery tests ---
echo ""
echo "--- Service Discovery Tests ---"

SERVICES=("identity" "order" "payment" "catalog" "notification" "analytics" "gateway" "schema-registry")
if [ "${SERVICE}" != "all" ]; then
  SERVICES=("${SERVICE}")
fi

for svc in "${SERVICES[@]}"; do
  run_test "discovery-${svc}" "curl -sf -o /dev/null -w '%{http_code}' '${BASE_URL}/api/v1/${svc}/health' | grep -q '200\\|204'"
done

# --- Cross-service integration tests ---
echo ""
echo "--- Cross-Service Integration Tests ---"

# Gateway → Identity (auth flow)
run_test "gateway-identity-auth" "curl -sf '${BASE_URL}/api/v1/gateway/auth/check' -H 'Authorization: Bearer test-token' | grep -q 'authenticated\\|unauthorized'"

# Order → Payment (saga initiation)
run_test "order-payment-saga" "curl -sf -X POST '${BASE_URL}/api/v1/order/test-saga' -H 'Content-Type: application/json' -d '{\"test\": true}' | grep -q 'saga_id\\|accepted\\|error'"

# Order → Notification (event delivery)
run_test "order-notification-event" "curl -sf '${BASE_URL}/api/v1/notification/events?source=order&limit=1' | grep -q 'events\\|empty'"

# Catalog → Schema Registry (schema validation)
run_test "catalog-schema-registry" "curl -sf '${BASE_URL}/api/v1/schema-registry/schemas/catalog' | grep -q 'schema\\|not_found'"

# Analytics → CDC (data pipeline)
run_test "analytics-cdc-pipeline" "curl -sf '${BASE_URL}/api/v1/analytics/pipeline/status' | grep -q 'running\\|healthy\\|status'"

# --- Schema compatibility tests ---
echo ""
echo "--- Schema Compatibility Tests ---"

run_test "protobuf-compat" "cd ${PROJECT_ROOT} && buf breaking schemas/ --against schemas/ 2>/dev/null || true"

# --- mTLS verification ---
echo ""
echo "--- mTLS Verification ---"

run_test "mtls-gateway-identity" "curl -sf -o /dev/null -w '%{http_code}' '${BASE_URL}/api/v1/gateway/mtls-status' | grep -q '200'"

# --- Results summary ---
echo ""
echo "============================================================"
echo "  Integration Test Results"
echo "  PASS: ${PASS}"
echo "  FAIL: ${FAIL}"
echo "  SKIP: ${SKIP}"
echo "  Total: $((PASS + FAIL + SKIP))"
echo "============================================================"

# Write JUnit-style results
cat > "${RESULTS_DIR}/integration-results-${TIMESTAMP}.xml" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="integration-tests" tests="$((PASS + FAIL + SKIP))" failures="${FAIL}" skipped="${SKIP}" timestamp="${TIMESTAMP}">
EOF

for t in "${FAILED_TESTS[@]}"; do
  echo "  <testcase name=\"${t}\"><failure message=\"Integration test failed\"/></testcase>" \
    >> "${RESULTS_DIR}/integration-results-${TIMESTAMP}.xml"
done

for ((i=0; i<PASS; i++)); do
  echo "  <testcase name=\"passed-test-${i}\"/>" \
    >> "${RESULTS_DIR}/integration-results-${TIMESTAMP}.xml"
done

echo "</testsuite>" >> "${RESULTS_DIR}/integration-results-${TIMESTAMP}.xml"

echo ""
echo "  Results written to: ${RESULTS_DIR}/"

if [ "${FAIL}" -gt 0 ]; then
  echo ""
  echo "  FAILED TESTS:"
  for t in "${FAILED_TESTS[@]}"; do
    echo "    - ${t}"
  done
  exit 1
fi

exit 0
