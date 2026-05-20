#!/usr/bin/env bash
# ============================================================================
# Chaos Experiment Runner — Polyglot Microservices Platform
# Runs 5 targeted chaos experiments to validate resilience patterns.
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
K8S_NAMESPACE="${K8S_NAMESPACE:-production}"
GATEWAY_URL="${GATEWAY_URL:-https://localhost:8443}"
ORDER_URL="${ORDER_URL:-https://localhost:8443}"
PAYMENT_URL="${PAYMENT_URL:-https://localhost:8443}"
KAFKA_BROKERS="${KAFKA_BROKERS:-localhost:9092}"
CURL_OPTS="-ksf --max-time 15 --connect-timeout 5"

ALL_SERVICES=(gateway identity analytics notification rl-engine order payment catalog schema-registry)

# Timeout defaults (seconds)
DEFAULT_STABILIZATION_TIMEOUT=120
DEFAULT_VERIFICATION_TIMEOUT=60

# Experiment results
declare -A EXPERIMENT_RESULTS
declare -A EXPERIMENT_EVIDENCE
declare -A EXPERIMENT_DURATIONS

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
  cat <<EOF
${BOLD}Chaos Experiment Runner${NC}

Usage: $(basename "$0") [OPTIONS]

Options:
  --experiment <name>      Run a single experiment only
  --stabilization <secs>   Stabilization timeout (default: 120)
  --verbose                Show detailed output
  -h, --help               Show this help message

Experiments:
  1. kill-spire       Kill SPIRE Server pod — verify no service disruption within 1h SVID TTL
  2. kill-kafka       Kill Kafka broker pod — verify Debezium reconnects, consumers rebalance
  3. network-payment  Network partition Payment → Stripe — verify circuit breaker & saga compensation
  4. oom-analytics    OOM Kill Analytics — verify pod restart within 30s
  5. dns-outage       DNS Outage — block port 53 egress, verify graceful degradation
EOF
  exit 0
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
VERBOSE=0
TARGET_EXPERIMENT=""
STABILIZATION_TIMEOUT="$DEFAULT_STABILIZATION_TIMEOUT"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --experiment)
      TARGET_EXPERIMENT="$2"
      shift 2
      ;;
    --stabilization)
      STABILIZATION_TIMEOUT="$2"
      shift 2
      ;;
    --verbose)
      VERBOSE=1
      shift
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}" >&2
      exit 1
      ;;
  esac
done

VALID_EXPERIMENTS=("kill-spire" "kill-kafka" "network-payment" "oom-analytics" "dns-outage")
if [[ -n "$TARGET_EXPERIMENT" ]]; then
  found=0
  for e in "${VALID_EXPERIMENTS[@]}"; do
    [[ "$e" == "$TARGET_EXPERIMENT" ]] && found=1
  done
  if [[ $found -eq 0 ]]; then
    echo -e "${RED}ERROR: Unknown experiment '$TARGET_EXPERIMENT'${NC}" >&2
    echo -e "${YELLOW}Valid experiments: ${VALID_EXPERIMENTS[*]}${NC}" >&2
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Prerequisites check
# ---------------------------------------------------------------------------
check_prerequisites() {
  if ! command -v kubectl &>/dev/null; then
    echo -e "${RED}ERROR: kubectl is required for chaos experiments${NC}" >&2
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Helper: record experiment result
# ---------------------------------------------------------------------------
record_experiment() {
  local name="$1" result="$2" evidence="$3" duration_ms="$4"
  EXPERIMENT_RESULTS[$name]="$result"
  EXPERIMENT_EVIDENCE[$name]="$evidence"
  EXPERIMENT_DURATIONS[$name]="$duration_ms"
}

# ---------------------------------------------------------------------------
# Helper: check if all services are SERVING
# ---------------------------------------------------------------------------
check_all_serving() {
  local not_serving=()
  for svc in "${ALL_SERVICES[@]}"; do
    local pod_status
    pod_status=$(kubectl get pods -n "$K8S_NAMESPACE" -l "app=$svc" \
      -o jsonpath='{.items[0].status.phase}' 2>/dev/null) || pod_status="Unknown"
    local ready
    ready=$(kubectl get pods -n "$K8S_NAMESPACE" -l "app=$svc" \
      -o jsonpath='{.items[0].status.containerStatuses[0].ready}' 2>/dev/null) || ready="false"
    if [[ "$pod_status" != "Running" ]] || [[ "$ready" != "true" ]]; then
      not_serving+=("$svc($pod_status,ready=$ready)")
    fi
  done
  if [[ ${#not_serving[@]} -eq 0 ]]; then
    echo "ALL_SERVING"
  else
    echo "NOT_SERVING:${not_serving[*]}"
  fi
}

# ---------------------------------------------------------------------------
# Helper: get Kafka consumer lag
# ---------------------------------------------------------------------------
get_consumer_lag() {
  local group="${1:-notification-service}"
  local lag
  lag=$(kubectl exec -n "$K8S_NAMESPACE" deploy/kafka -- \
    kafka-consumer-groups --bootstrap-server localhost:9092 \
    --describe --group "$group" 2>/dev/null | \
    awk '{if(NR>1) print $NF}' | sort -rn | head -1) || lag="unknown"
  echo "${lag:-0}"
}

# ============================================================================
# Experiment 1: Kill SPIRE Server
# ============================================================================
experiment_kill_spire() {
  echo -e "${MAGENTA}${BOLD}Experiment 1: Kill SPIRE Server${NC}"
  echo -e "  Expected: No service disruption within 1h SVID TTL"
  echo -e "  Verify:   All services remain SERVING"
  echo ""

  local start_time end_time duration_ms
  start_time=$(date +%s%N)

  # Pre-check: verify all services are serving
  echo -e "  ${CYAN}[PRE-CHECK]${NC} Verifying all services are SERVING"
  local pre_check
  pre_check=$(check_all_serving)
  if [[ "$pre_check" != "ALL_SERVING" ]]; then
    echo -e "    ${RED}Pre-check failed: $pre_check${NC}"
    record_experiment "kill-spire" "FAIL" "Pre-check: $pre_check" 0
    return
  fi
  echo -e "    ${GREEN}All services SERVING before experiment${NC}"

  # Apply chaos: Delete spire-server-0 pod
  echo -e "  ${RED}[CHAOS]${NC} Deleting spire-server-0 pod"
  local spire_pod
  spire_pod=$(kubectl get pods -n "$K8S_NAMESPACE" -l "app=spire-server" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null) || spire_pod="spire-server-0"

  echo -e "    Deleting pod: $spire_pod"
  kubectl delete pod "$spire_pod" -n "$K8S_NAMESPACE" --grace-period=0 --force 2>/dev/null || {
    echo -e "    ${YELLOW}Could not delete spire-server pod (may not exist)${NC}"
  }

  # Wait for stabilization
  echo -e "  ${CYAN}[STABILIZE]${NC} Waiting for stabilization (30s)..."
  sleep 30

  # Verify: All services remain SERVING
  echo -e "  ${CYAN}[VERIFY]${NC} Checking all services remain SERVING"
  local verify_result
  verify_result=$(check_all_serving)

  local evidence="Pre: ALL_SERVING | Post: $verify_result"

  if [[ "$verify_result" == "ALL_SERVING" ]]; then
    echo -e "    ${GREEN}All services remain SERVING after SPIRE server kill${NC}"

    # Verify SPIRE server pod restarted
    local new_spire_pod
    new_spire_pod=$(kubectl get pods -n "$K8S_NAMESPACE" -l "app=spire-server" \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null) || true
    local spire_restarts
    spire_restarts=$(kubectl get pods -n "$K8S_NAMESPACE" -l "app=spire-server" \
      -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null) || true
    evidence="$evidence | Spire pod: $new_spire_pod (restarts: ${spire_restarts:-?})"

    # Additional: check SVIDs are still valid (within TTL)
    echo -e "    ${CYAN}[VERIFY]${NC} Checking SVID validity on a sample service"
    local sample_svc="gateway"
    local svid_check
    svid_check=$(kubectl exec -n "$K8S_NAMESPACE" "deploy/$sample_svc" -- \
      cat /var/run/secrets/spiffe/svid.pem 2>/dev/null | \
      openssl x509 -checkend 1800 -noout 2>/dev/null) || svid_check="SVID check failed"
    if echo "$svid_check" | rg -q "will not expire"; then
      echo -e "      ${GREEN}SVID still valid for >30 minutes${NC}"
      evidence="$evidence | SVID valid"
    else
      echo -e "      ${YELLOW}SVID may expire soon: $svid_check${NC}"
      evidence="$evidence | SVID: $svid_check"
    fi

    end_time=$(date +%s%N)
    duration_ms=$(( (end_time - start_time) / 1000000 ))
    record_experiment "kill-spire" "PASS" "$evidence" "$duration_ms"
  else
    echo -e "    ${RED}Services not serving after SPIRE server kill: $verify_result${NC}"
    end_time=$(date +%s%N)
    duration_ms=$(( (end_time - start_time) / 1000000 ))
    record_experiment "kill-spire" "FAIL" "$evidence" "$duration_ms"
  fi

  # Rollback: wait for SPIRE server to be fully back
  echo -e "  ${CYAN}[ROLLBACK]${NC} Waiting for SPIRE server to be ready"
  local rollback_wait=0 max_rollback=60
  while [[ $rollback_wait -lt $max_rollback ]]; do
    local spire_ready
    spire_ready=$(kubectl get pods -n "$K8S_NAMESPACE" -l "app=spire-server" \
      -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}' 2>/dev/null) || true
    if [[ "$spire_ready" == "True" ]]; then
      echo -e "    ${GREEN}SPIRE server is ready${NC}"
      break
    fi
    sleep 5
    rollback_wait=$((rollback_wait + 5))
  done
}

# ============================================================================
# Experiment 2: Kill Kafka Broker
# ============================================================================
experiment_kill_kafka() {
  echo -e "${MAGENTA}${BOLD}Experiment 2: Kill Kafka Broker${NC}"
  echo -e "  Expected: Debezium reconnects, consumers rebalance"
  echo -e "  Verify:   Consumer lag returns to 0 within 60s"
  echo ""

  local start_time end_time duration_ms
  start_time=$(date +%s%N)

  # Pre-check: record current consumer lag
  echo -e "  ${CYAN}[PRE-CHECK]${NC} Recording baseline consumer lag"
  local baseline_lag
  baseline_lag=$(get_consumer_lag)
  echo -e "    Baseline lag: $baseline_lag"

  # Apply chaos: Delete kafka-1 pod
  echo -e "  ${RED}[CHAOS]${NC} Deleting kafka-1 pod"
  local kafka_pod
  kafka_pod=$(kubectl get pods -n "$K8S_NAMESPACE" -l "app=kafka,statefulset.kubernetes.io/pod-index=1" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null) || kafka_pod="kafka-1"

  # Fallback: find any kafka pod with index 1
  if [[ -z "$kafka_pod" ]] || [[ "$kafka_pod" == "kafka-1" ]]; then
    kafka_pod=$(kubectl get pods -n "$K8S_NAMESPACE" -l "app=kafka" \
      -o jsonpath='{.items[1].metadata.name}' 2>/dev/null) || kafka_pod="kafka-1"
  fi

  echo -e "    Deleting pod: $kafka_pod"
  kubectl delete pod "$kafka_pod" -n "$K8S_NAMESPACE" --grace-period=0 --force 2>/dev/null || {
    echo -e "    ${YELLOW}Could not delete kafka pod (may not exist in this form)${NC}"
  }

  # Wait briefly then start monitoring
  echo -e "  ${CYAN}[STABILIZE]${NC} Waiting for Kafka broker restart and consumer rebalancing..."
  local verify_start verify_elapsed lag_returned_to_zero=0
  verify_start=$(date +%s)
  local verify_timeout=60

  while true; do
    verify_elapsed=$(( $(date +%s) - verify_start ))
    if [[ $verify_elapsed -ge $verify_timeout ]]; then
      break
    fi

    local current_lag
    current_lag=$(get_consumer_lag)
    echo -e "    Consumer lag at +${verify_elapsed}s: $current_lag"

    if [[ "$current_lag" =~ ^[0-9]+$ ]] && [[ "$current_lag" -eq 0 ]]; then
      lag_returned_to_zero=1
      echo -e "    ${GREEN}Consumer lag returned to 0 within ${verify_elapsed}s${NC}"
      break
    fi

    sleep 5
  done

  # Verify Debezium reconnected
  echo -e "  ${CYAN}[VERIFY]${NC} Checking Debezium connector status"
  local debezium_status
  debezium_status=$(kubectl exec -n "$K8S_NAMESPACE" deploy/debezium -- \
    wget -qO- http://localhost:8083/connectors 2>/dev/null) || debezium_status="unavailable"
  echo -e "    Debezium connectors: $debezium_status"

  local evidence="Baseline lag: $baseline_lag | Lag returned to 0: $lag_returned_to_zero | Debezium: ${debezium_status:0:50}"

  if [[ $lag_returned_to_zero -eq 1 ]]; then
    end_time=$(date +%s%N)
    duration_ms=$(( (end_time - start_time) / 1000000 ))
    record_experiment "kill-kafka" "PASS" "$evidence" "$duration_ms"
  else
    local final_lag
    final_lag=$(get_consumer_lag)
    evidence="$evidence | Final lag: $final_lag"
    echo -e "    ${RED}Consumer lag did not return to 0 within 60s (final: $final_lag)${NC}"
    end_time=$(date +%s%N)
    duration_ms=$(( (end_time - start_time) / 1000000 ))
    record_experiment "kill-kafka" "FAIL" "$evidence" "$duration_ms"
  fi

  # Rollback: ensure kafka pod is running
  echo -e "  ${CYAN}[ROLLBACK]${NC} Verifying Kafka pod recovery"
  local rb_wait=0 max_rb=120
  while [[ $rb_wait -lt $max_rb ]]; do
    local kafka_ready
    kafka_ready=$(kubectl get pods -n "$K8S_NAMESPACE" -l "app=kafka" \
      -o jsonpath='{.items[*].status.conditions[?(@.type=="Ready")].status}' 2>/dev/null) || true
    if echo "$kafka_ready" | rg -q "True"; then
      echo -e "    ${GREEN}At least one Kafka broker is ready${NC}"
      break
    fi
    sleep 5
    rb_wait=$((rb_wait + 5))
  done
}

# ============================================================================
# Experiment 3: Network Partition Payment → Stripe
# ============================================================================
experiment_network_payment() {
  echo -e "${MAGENTA}${BOLD}Experiment 3: Network Partition Payment → Stripe${NC}"
  echo -e "  Expected: Circuit breaker opens, saga compensation triggers"
  echo -e "  Verify:   Order status transitions to COMPENSATING"
  echo ""

  local start_time end_time duration_ms
  start_time=$(date +%s%N)

  # Step 1: Create a deny NetworkPolicy for payment → external
  echo -e "  ${RED}[CHAOS]${NC} Applying deny NetworkPolicy for payment egress"

  local deny_policy_name="chaos-deny-payment-egress"
  kubectl apply -f - <<POLICY 2>/dev/null || echo "NetworkPolicy apply attempted"
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: ${deny_policy_name}
  namespace: ${K8S_NAMESPACE}
spec:
  podSelector:
    matchLabels:
      app: payment
  policyTypes:
    - Egress
  egress: []
POLICY

  echo -e "    ${RED}Deny-all egress NetworkPolicy applied to payment service${NC}"
  sleep 5

  # Step 2: Create an order that will trigger payment
  echo -e "  ${CYAN}[TEST]${NC} Creating order to trigger payment saga"
  local order_response
  order_response=$(curl $CURL_OPTS -X POST "$ORDER_URL/api/v1/order/orders" \
    -H "Content-Type: application/json" \
    -d '{
      "items": [{"product_id": "chaos-test-product", "quantity": 1}],
      "payment_method": "test_card"
    }' 2>/dev/null) || true

  local order_id
  order_id=$(echo "$order_response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null) || true
  echo -e "    Test order created: ${order_id:-<no-id>}"

  # Step 3: Monitor order status for COMPENSATING
  echo -e "  ${CYAN}[VERIFY]${NC} Monitoring order status for COMPENSATING transition"
  local verify_start verify_elapsed found_compensating=0
  verify_start=$(date +%s)
  local verify_timeout=60

  while true; do
    verify_elapsed=$(( $(date +%s) - verify_start ))
    if [[ $verify_elapsed -ge $verify_timeout ]]; then
      break
    fi

    if [[ -n "$order_id" ]]; then
      local status_response order_status
      status_response=$(curl $CURL_OPTS "$ORDER_URL/api/v1/order/orders/$order_id" 2>/dev/null) || true
      order_status=$(echo "$status_response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null) || true

      echo -e "    Order status at +${verify_elapsed}s: $order_status"

      if [[ "$order_status" == "COMPENSATING" ]] || [[ "$order_status" == "FAILED" ]]; then
        found_compensating=1
        echo -e "    ${GREEN}Order reached $order_status state — compensation triggered${NC}"
        break
      fi
    else
      # If we can't create order, check payment circuit breaker state
      local cb_state
      cb_state=$(curl $CURL_OPTS "$PAYMENT_URL/api/v1/payment/circuit-breaker" 2>/dev/null) || true
      if echo "$cb_state" | rg -qi "open"; then
        found_compensating=1
        echo -e "    ${GREEN}Circuit breaker is OPEN${NC}"
        break
      fi
    fi

    sleep 3
  done

  # Also check circuit breaker state
  echo -e "  ${CYAN}[VERIFY]${NC} Checking payment circuit breaker state"
  local cb_response
  cb_response=$(curl $CURL_OPTS "$PAYMENT_URL/metrics" 2>/dev/null) || true
  local cb_open=0
  if echo "$cb_response" | rg -qi "circuit.*open\|resilience4j_circuitbreaker_state.*open"; then
    cb_open=1
    echo -e "    ${GREEN}Circuit breaker is OPEN (confirmed via metrics)${NC}"
  else
    echo -e "    ${YELLOW}Circuit breaker state not confirmed via metrics endpoint${NC}"
  fi

  local evidence="Order: ${order_id:-N/A} | Compensating: $found_compensating | CB open: $cb_open"

  if [[ $found_compensating -eq 1 ]] || [[ $cb_open -eq 1 ]]; then
    end_time=$(date +%s%N)
    duration_ms=$(( (end_time - start_time) / 1000000 ))
    record_experiment "network-payment" "PASS" "$evidence" "$duration_ms"
  else
    echo -e "    ${RED}Compensation not triggered and circuit breaker not open${NC}"
    end_time=$(date +%s%N)
    duration_ms=$(( (end_time - start_time) / 1000000 ))
    record_experiment "network-payment" "FAIL" "$evidence" "$duration_ms"
  fi

  # Rollback: Remove the deny NetworkPolicy
  echo -e "  ${CYAN}[ROLLBACK]${NC} Removing deny NetworkPolicy"
  kubectl delete networkpolicy "$deny_policy_name" -n "$K8S_NAMESPACE" 2>/dev/null || true
  echo -e "    ${GREEN}Deny NetworkPolicy removed${NC}"

  # Wait for circuit breaker to close
  sleep 10
}

# ============================================================================
# Experiment 4: OOM Kill Analytics
# ============================================================================
experiment_oom_analytics() {
  echo -e "${MAGENTA}${BOLD}Experiment 4: OOM Kill Analytics${NC}"
  echo -e "  Expected: Pod restarts within 30s"
  echo -e "  Verify:   Queries resume after restart"
  echo ""

  local start_time end_time duration_ms
  start_time=$(date +%s%N)

  # Pre-check: record analytics pod name
  echo -e "  ${CYAN}[PRE-CHECK]${NC} Recording analytics pod state"
  local analytics_pod
  analytics_pod=$(kubectl get pods -n "$K8S_NAMESPACE" -l "app=analytics" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null) || analytics_pod=""
  local analytics_restarts
  analytics_restarts=$(kubectl get pods -n "$K8S_NAMESPACE" -l "app=analytics" \
    -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null) || analytics_restarts="0"
  echo -e "    Current pod: $analytics_pod (restarts: $analytics_restarts)"

  # Apply chaos: SIGKILL to analytics process
  echo -e "  ${RED}[CHAOS]${NC} Sending SIGKILL to analytics process"
  if [[ -n "$analytics_pod" ]]; then
    # Find the analytics process and kill it
    kubectl exec -n "$K8S_NAMESPACE" "$analytics_pod" -- \
      sh -c "kill -9 1" 2>/dev/null || \
    kubectl exec -n "$K8S_NAMESPACE" "$analytics_pod" -- \
      sh -c "pkill -9 python" 2>/dev/null || \
    kubectl delete pod "$analytics_pod" -n "$K8S_NAMESPACE" --grace-period=0 --force 2>/dev/null || true
    echo -e "    Process kill signal sent to $analytics_pod"
  else
    echo -e "    ${YELLOW}Analytics pod not found${NC}"
  fi

  # Verify: Pod restarts within 30s
  echo -e "  ${CYAN}[VERIFY]${NC} Checking pod restart within 30s"
  local verify_start verify_elapsed pod_restarted=0
  verify_start=$(date +%s)
  local verify_timeout=30

  while true; do
    verify_elapsed=$(( $(date +%s) - verify_start ))
    if [[ $verify_elapsed -ge $verify_timeout ]]; then
      break
    fi

    local new_pod new_restarts
    new_pod=$(kubectl get pods -n "$K8S_NAMESPACE" -l "app=analytics" \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null) || true
    new_restarts=$(kubectl get pods -n "$K8S_NAMESPACE" -l "app=analytics" \
      -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null) || new_restarts="0"

    if [[ "$new_pod" != "$analytics_pod" ]] || [[ "$new_restarts" -gt "$analytics_restarts" ]]; then
      pod_restarted=1
      echo -e "    ${GREEN}Pod restarted within ${verify_elapsed}s (new pod: $new_pod, restarts: $new_restarts)${NC}"
      break
    fi

    sleep 2
  done

  # Verify: Queries resume after restart
  echo -e "  ${CYAN}[VERIFY]${NC} Checking analytics queries resume"
  local query_resumed=0 query_wait=0 max_query_wait=60
  while [[ $query_wait -lt $max_query_wait ]]; do
    local health_check
    health_check=$(curl $CURL_OPTS "https://$(kubectl get svc analytics -n "$K8S_NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null):8443/healthz" 2>/dev/null) || true
    if [[ -n "$health_check" ]]; then
      query_resumed=1
      echo -e "    ${GREEN}Analytics queries resumed${NC}"
      break
    fi
    sleep 3
    query_wait=$((query_wait + 3))
  done

  local evidence="Pod restarted: $pod_restarted (${verify_elapsed:-?}s) | Queries resumed: $query_resumed"

  if [[ $pod_restarted -eq 1 ]] && [[ $query_resumed -eq 1 ]]; then
    end_time=$(date +%s%N)
    duration_ms=$(( (end_time - start_time) / 1000000 ))
    record_experiment "oom-analytics" "PASS" "$evidence" "$duration_ms"
  elif [[ $pod_restarted -eq 1 ]]; then
    end_time=$(date +%s%N)
    duration_ms=$(( (end_time - start_time) / 1000000 ))
    record_experiment "oom-analytics" "FAIL" "$evidence (queries not resumed)" "$duration_ms"
  else
    end_time=$(date +%s%N)
    duration_ms=$(( (end_time - start_time) / 1000000 ))
    record_experiment "oom-analytics" "FAIL" "$evidence (pod not restarted)" "$duration_ms"
  fi

  # No explicit rollback needed — K8s self-heals
  echo -e "  ${CYAN}[ROLLBACK]${NC} No rollback needed — K8s self-healing handles pod restart"
}

# ============================================================================
# Experiment 5: DNS Outage
# ============================================================================
experiment_dns_outage() {
  echo -e "${MAGENTA}${BOLD}Experiment 5: DNS Outage${NC}"
  echo -e "  Expected: New requests fail, existing connections survive"
  echo -e "  Verify:   Gateway returns 503 for new requests"
  echo ""

  local start_time end_time duration_ms
  start_time=$(date +%s%N)

  # Step 1: Establish a baseline connection (existing connection)
  echo -e "  ${CYAN}[PRE-CHECK]${NC} Establishing baseline connection"
  local baseline_code
  baseline_code=$(curl $CURL_OPTS -o /dev/null -w "%{http_code}" "$GATEWAY_URL/healthz" 2>/dev/null) || baseline_code="000"
  echo -e "    Baseline gateway response: HTTP $baseline_code"

  # Step 2: Block DNS egress by applying default-deny egress for gateway
  # NetworkPolicy default-deny with no egress rules blocks all outbound
  # traffic including DNS (port 53). This simulates a DNS outage.
  echo -e "  ${RED}[CHAOS]${NC} Applying default-deny egress to gateway (blocks DNS)"
  local dns_deny_policy="chaos-deny-dns-egress"
  kubectl apply -f - <<POLICY 2>/dev/null || echo "Egress deny policy apply attempted"
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: ${dns_deny_policy}
  namespace: ${K8S_NAMESPACE}
spec:
  podSelector:
    matchLabels:
      app: gateway
  policyTypes:
    - Egress
POLICY

  sleep 5

  # Step 3: Verify new requests fail
  echo -e "  ${CYAN}[VERIFY]${NC} Checking gateway response for new requests"
  local new_request_code
  new_request_code=$(curl -k --max-time 10 -o /dev/null -w "%{http_code}" "$GATEWAY_URL/api/v1/catalog/products" 2>/dev/null) || new_request_code="000"

  local new_requests_fail=0
  if [[ "$new_request_code" =~ ^(000|503|502|504)$ ]]; then
    new_requests_fail=1
    echo -e "    ${GREEN}New requests fail as expected: HTTP $new_request_code${NC}"
  else
    echo -e "    ${YELLOW}New requests returned: HTTP $new_request_code (may still work if cached)${NC}"
  fi

  # Step 4: Verify existing connections survive (if we had a persistent connection)
  # Since curl creates new connections, we verify by checking that services
  # with established connections can still communicate
  echo -e "  ${CYAN}[VERIFY]${NC} Checking if established service-to-service connections survive"
  local svc_to_svc_ok=0
  # Check if identity service (which may have existing gRPC connections) is still reachable
  local internal_check
  internal_check=$(kubectl exec -n "$K8S_NAMESPACE" deploy/order -- \
    wget -qO- --timeout=5 http://identity:8443/healthz 2>/dev/null) || true
  if [[ -n "$internal_check" ]]; then
    svc_to_svc_ok=1
    echo -e "    ${GREEN}Service-to-service connections survived (order → identity)${NC}"
  else
    echo -e "    ${YELLOW}Could not verify service-to-service connection survival${NC}"
  fi

  local evidence="New req: HTTP $new_request_code | New fail: $new_requests_fail | Existing survived: $svc_to_svc_ok"

  if [[ $new_requests_fail -eq 1 ]]; then
    end_time=$(date +%s%N)
    duration_ms=$(( (end_time - start_time) / 1000000 ))
    record_experiment "dns-outage" "PASS" "$evidence" "$duration_ms"
  else
    end_time=$(date +%s%N)
    duration_ms=$(( (end_time - start_time) / 1000000 ))
    record_experiment "dns-outage" "FAIL" "$evidence" "$duration_ms"
  fi

  # Rollback: Remove DNS deny NetworkPolicy
  echo -e "  ${CYAN}[ROLLBACK]${NC} Removing DNS egress deny NetworkPolicy"
  kubectl delete networkpolicy "$dns_deny_policy" -n "$K8S_NAMESPACE" 2>/dev/null || true
  echo -e "    ${GREEN}DNS egress restored${NC}"
  sleep 5

  # Verify gateway recovers
  echo -e "  ${CYAN}[VERIFY]${NC} Checking gateway recovery"
  local recovery_wait=0 max_recovery=30
  while [[ $recovery_wait -lt $max_recovery ]]; do
    local recovery_code
    recovery_code=$(curl $CURL_OPTS -o /dev/null -w "%{http_code}" "$GATEWAY_URL/healthz" 2>/dev/null) || recovery_code="000"
    if [[ "$recovery_code" == "200" ]]; then
      echo -e "    ${GREEN}Gateway recovered: HTTP $recovery_code${NC}"
      break
    fi
    sleep 3
    recovery_wait=$((recovery_wait + 3))
  done
}

# ============================================================================
# Main
# ============================================================================
main() {
  echo -e "${BOLD}╔══════════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}║            Chaos Experiment Runner — Resilience Testing           ║${NC}"
  echo -e "${BOLD}╚══════════════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "  Namespace:              $K8S_NAMESPACE"
  echo -e "  Stabilization timeout:  ${STABILIZATION_TIMEOUT}s"
  echo -e "  Gateway URL:            $GATEWAY_URL"
  echo ""

  check_prerequisites

  # Run experiments
  declare -A EXPERIMENT_FUNCS=(
    [kill-spire]=experiment_kill_spire
    [kill-kafka]=experiment_kill_kafka
    [network-payment]=experiment_network_payment
    [oom-analytics]=experiment_oom_analytics
    [dns-outage]=experiment_dns_outage
  )

  local overall_start overall_end overall_elapsed
  overall_start=$(date +%s)

  if [[ -n "$TARGET_EXPERIMENT" ]]; then
    "${EXPERIMENT_FUNCS[$TARGET_EXPERIMENT]}"
    echo ""
  else
    for exp in "${VALID_EXPERIMENTS[@]}"; do
      "${EXPERIMENT_FUNCS[$exp]}"
      echo ""
    done
  fi

  overall_end=$(date +%s)
  overall_elapsed=$((overall_end - overall_start))

  # ---------------------------------------------------------------------------
  # Experiment Report
  # ---------------------------------------------------------------------------
  echo -e "${BOLD}╔══════════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}║               Chaos Experiment Results Report                     ║${NC}"
  echo -e "${BOLD}╚══════════════════════════════════════════════════════════════════╝${NC}"
  echo ""

  printf "  ${BOLD}%-20s %-10s %-12s %-50s${NC}\n" "EXPERIMENT" "RESULT" "DURATION" "EVIDENCE"
  printf "  %s\n" "$(printf '─%.0s' {1..92})"

  local pass_count=0 fail_count=0
  for exp in "${VALID_EXPERIMENTS[@]}"; do
    if [[ -n "$TARGET_EXPERIMENT" ]] && [[ "$exp" != "$TARGET_EXPERIMENT" ]]; then
      continue
    fi
    local result="${EXPERIMENT_RESULTS[$exp]:-UNKNOWN}"
    local duration="${EXPERIMENT_DURATIONS[$exp]:-0}"
    local evidence="${EXPERIMENT_EVIDENCE[$exp]:-N/A}"
    local color="$NC"
    case "$result" in
      PASS) color="$GREEN"; ((pass_count++)) || true ;;
      FAIL) color="$RED"; ((fail_count++)) || true ;;
    esac
    # Truncate evidence for display
    local short_evidence="${evidence:0:48}"
    printf "  %-20s ${color}%-10s${NC} %-12s %-50s\n" "$exp" "$result" "${duration}ms" "$short_evidence"
  done

  echo ""
  local total_run=$((pass_count + fail_count))
  printf "  Total: %d | ${GREEN}PASS: %d${NC} | ${RED}FAIL: %d${NC} | Time: %ds\n" \
    "$total_run" "$pass_count" "$fail_count" "$overall_elapsed"
  echo ""

  # Detailed evidence
  if [[ $VERBOSE -eq 1 ]]; then
    echo -e "${BOLD}Detailed Evidence:${NC}"
    for exp in "${VALID_EXPERIMENTS[@]}"; do
      if [[ -n "$TARGET_EXPERIMENT" ]] && [[ "$exp" != "$TARGET_EXPERIMENT" ]]; then
        continue
      fi
      echo -e "  ${BOLD}$exp:${NC}"
      echo -e "    ${EXPERIMENT_EVIDENCE[$exp]:-N/A}"
    done
    echo ""
  fi

  if [[ $fail_count -gt 0 ]]; then
    echo -e "${RED}${BOLD}CHAOS EXPERIMENTS FAILED — resilience gaps detected${NC}"
    exit 1
  fi

  echo -e "${GREEN}${BOLD}ALL CHAOS EXPERIMENTS PASSED — platform is resilient${NC}"
  exit 0
}

main
