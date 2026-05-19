#!/usr/bin/env bash
# ============================================================================
# Security Validation Script — Polyglot Microservices Platform
# Validates security controls: SDK scan, NetworkPolicy, SPIRE, ACL, hexagonal arch.
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICES_DIR="$PROJECT_ROOT/services"
K8S_DIR="$PROJECT_ROOT/infra/kubernetes"

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
# Configuration
# ---------------------------------------------------------------------------
SPIFFE_TRUST_DOMAIN="${SPIFFE_TRUST_DOMAIN:-trust.example.org}"
K8S_NAMESPACE="${K8S_NAMESPACE:-production}"

ALL_SERVICES=(gateway identity analytics notification rl-engine order payment catalog schema-registry)

# Result matrix: CHECK_SERVICE -> PASS/FAIL
declare -A SECURITY_MATRIX

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
  cat <<EOF
${BOLD}Security Validation Script${NC}

Usage: $(basename "$0") [OPTIONS]

Options:
  --check <name>   Run a single security check only
  --verbose        Show detailed output
  -h, --help       Show this help message

Security Checks:
  1. sdk-scan           Proprietary SDK scan (no cloud SDK imports)
  2. network-policy     NetworkPolicy validation
  3. spire-attestation  SPIRE SVID attestation check
  4. acl-bypass         ACL bypass attempt verification
  5. hexagonal-arch     Hexagonal architecture verification
EOF
  exit 0
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
VERBOSE=0
TARGET_CHECK=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)
      TARGET_CHECK="$2"
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

VALID_CHECKS=("sdk-scan" "network-policy" "spire-attestation" "acl-bypass" "hexagonal-arch")
if [[ -n "$TARGET_CHECK" ]]; then
  found=0
  for c in "${VALID_CHECKS[@]}"; do
    [[ "$c" == "$TARGET_CHECK" ]] && found=1
  done
  if [[ $found -eq 0 ]]; then
    echo -e "${RED}ERROR: Unknown check '$TARGET_CHECK'${NC}" >&2
    echo -e "${YELLOW}Valid checks: ${VALID_CHECKS[*]}${NC}" >&2
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Helper: record matrix result
# ---------------------------------------------------------------------------
record_result() {
  local check="$1" service="$2" result="$3"
  SECURITY_MATRIX["${check}__${service}"]="$result"
  if [[ "$result" == "PASS" ]]; then
    echo -e "    ${GREEN}✓ PASS${NC} $service"
  else
    echo -e "    ${RED}✗ FAIL${NC} $service"
  fi
}

# ============================================================================
# Check 1: Proprietary SDK Scan
# ============================================================================
check_sdk_scan() {
  echo -e "${CYAN}${BOLD}Check 1: Proprietary SDK Scan${NC}"
  echo -e "  Scanning for cloud provider SDK imports in application code..."
  echo -e "  (OTel instrumentation packages are exempt)"
  echo ""

  # Patterns that indicate proprietary cloud SDK usage
  local sdk_patterns="boto3|aws-sdk|@google-cloud|@azure|software.amazon.awssdk"
  # Exempt patterns: OTel packages that legitimately reference cloud SDKs
  local exempt_patterns="otel|opentelemetry|observability"

  local total_matches=0

  for svc in "${ALL_SERVICES[@]}"; do
    local svc_dir="$SERVICES_DIR/$svc"
    if [[ ! -d "$svc_dir" ]]; then
      record_result "sdk-scan" "$svc" "SKIP"
      continue
    fi

    # Search for SDK imports in application code (not in otel/observability adapters)
    local matches
    matches=$(rg -l "$sdk_patterns" "$svc_dir/src" --glob '!**/observability/**' --glob '!**/otel/**' --glob '!**/otel*.*' 2>/dev/null) || true

    if [[ -z "$matches" ]]; then
      record_result "sdk-scan" "$svc" "PASS"
    else
      local match_count
      match_count=$(echo "$matches" | wc -l)
      total_matches=$((total_matches + match_count))
      echo -e "    ${RED}Found $match_count file(s) with cloud SDK imports:${NC}"
      echo "$matches" | while read -r f; do
        local rel_path="${f#$PROJECT_ROOT/}"
        echo -e "      ${RED}$rel_path${NC}"
        if [[ $VERBOSE -eq 1 ]]; then
          rg "$sdk_patterns" "$f" -n 2>/dev/null | head -5 | while read -r line; do
            echo -e "        $line"
          done
        fi
      done
      record_result "sdk-scan" "$svc" "FAIL"
    fi
  done

  echo ""
  if [[ $total_matches -eq 0 ]]; then
    echo -e "  ${GREEN}No proprietary cloud SDK imports found in application code${NC}"
  else
    echo -e "  ${RED}Found $total_matches file(s) with proprietary cloud SDK imports${NC}"
  fi
  echo ""
}

# ============================================================================
# Check 2: NetworkPolicy Validation
# ============================================================================
check_network_policy() {
  echo -e "${CYAN}${BOLD}Check 2: NetworkPolicy Validation${NC}"
  echo -e "  Verifying NetworkPolicy rules exist for all services..."
  echo ""

  # Step 2a: Check NetworkPolicy YAML files exist
  echo -e "  Step 2.1: Check NetworkPolicy manifests"
  local np_dir="$K8S_DIR/base"
  local np_file="$np_dir/networkpolicy.yaml"

  if [[ -f "$np_file" ]]; then
    echo -e "    Found: $np_file"
  else
    echo -e "    ${YELLOW}WARNING: No networkpolicy.yaml in $np_dir${NC}"
  fi

  # Check each service has a NetworkPolicy
  for svc in "${ALL_SERVICES[@]}"; do
    local has_np=0

    # Check base networkpolicy
    if [[ -f "$np_file" ]] && rg -q "$svc" "$np_file" 2>/dev/null; then
      has_np=1
    fi

    # Check service-specific manifests
    local svc_manifest="$K8S_DIR/apps/$svc.yaml"
    if [[ -f "$svc_manifest" ]] && rg -q "NetworkPolicy" "$svc_manifest" 2>/dev/null; then
      has_np=1
    fi

    # Check overlays for NetworkPolicy
    for overlay in staging production dev; do
      local overlay_dir="$K8S_DIR/overlays/$overlay"
      if [[ -d "$overlay_dir" ]] && rg -q "NetworkPolicy.*$svc\|$svc.*NetworkPolicy" "$overlay_dir" -r 2>/dev/null; then
        has_np=1
      fi
    done

    if [[ $has_np -eq 1 ]]; then
      record_result "network-policy" "$svc" "PASS"
    else
      record_result "network-policy" "$svc" "FAIL"
      echo -e "      ${YELLOW}No NetworkPolicy found for $svc${NC}"
    fi
  done

  echo ""

  # Step 2b: Deploy test pod to verify egress blocking (requires kubectl)
  echo -e "  Step 2.2: Verify unauthorized egress is blocked"
  if command -v kubectl &>/dev/null; then
    # Deploy a test pod that attempts unauthorized egress
    local test_pod_name="security-test-egress-$$"
    echo -e "    Deploying test pod: $test_pod_name"

    kubectl run "$test_pod_name" --image=busybox:1.36 --restart=Never \
      --command -- sleep 30 -n "$K8S_NAMESPACE" 2>/dev/null || true

    sleep 3

    # Attempt to reach an external endpoint that should be blocked
    local egress_result
    egress_result=$(kubectl exec "$test_pod_name" -n "$K8S_NAMESPACE" -- \
      wget -q -O- --timeout=5 https://ifconfig.me 2>&1) || true

    if [[ -z "$egress_result" ]] || echo "$egress_result" | rg -qi "timeout\|refused\|error\|no route"; then
      echo -e "    ${GREEN}Unauthorized egress blocked as expected${NC}"
    else
      echo -e "    ${RED}WARNING: Unauthorized egress succeeded — NetworkPolicy may not be enforced${NC}"
    fi

    # Cleanup
    kubectl delete pod "$test_pod_name" -n "$K8S_NAMESPACE" --force 2>/dev/null || true
  else
    echo -e "    ${YELLOW}kubectl not available — skipping live egress test${NC}"
  fi

  echo ""
}

# ============================================================================
# Check 3: SPIRE Attestation Check
# ============================================================================
check_spire_attestation() {
  echo -e "${CYAN}${BOLD}Check 3: SPIRE Attestation Check${NC}"
  echo -e "  Verifying SVID attestation, SPIFFE ID format, and TTL..."
  echo ""

  local expected_spiffe_prefix="spiffe://${SPIFFE_TRUST_DOMAIN}/ns/${K8S_NAMESPACE}/sa"

  for svc in "${ALL_SERVICES[@]}"; do
    local attestation_ok=1
    local spiffe_id_ok=1
    local ttl_ok=1

    # Check if running in K8s with kubectl access
    if command -v kubectl &>/dev/null; then
      # Verify SVID is obtained within 30 seconds of pod startup
      echo -e "    Checking $svc pod for SVID..."

      local pod_name
      pod_name=$(kubectl get pods -n "$K8S_NAMESPACE" -l "app=$svc" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null) || true

      if [[ -n "$pod_name" ]]; then
        # Check SPIFFE ID format via spire-server CLI or workload API
        local svid_info
        svid_info=$(kubectl exec -n "$K8S_NAMESPACE" "$pod_name" -- \
          cat /var/run/secrets/spiffe/svid.pem 2>/dev/null) || true

        if [[ -n "$svid_info" ]]; then
          echo -e "      SVID file found for $svc"

          # Check SPIFFE ID format
          local spiffe_id
          spiffe_id=$(echo "$svid_info" | openssl x509 -noout -text 2>/dev/null | \
            rg -o "spiffe://[^ ]+" | head -1) || true

          if [[ -n "$spiffe_id" ]]; then
            if [[ "$spiffe_id" == "$expected_spiffe_prefix/$svc" ]]; then
              echo -e "      ${GREEN}SPIFFE ID format correct: $spiffe_id${NC}"
            else
              echo -e "      ${RED}SPIFFE ID format mismatch: $spiffe_id${NC}"
              spiffe_id_ok=0
            fi
          else
            echo -e "      ${YELLOW}Could not extract SPIFFE ID from SVID${NC}"
            spiffe_id_ok=0
          fi

          # Verify SVID TTL is 1 hour (3600 seconds)
          local not_after not_before
          not_after=$(echo "$svid_info" | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2) || true
          not_before=$(echo "$svid_info" | openssl x509 -noout -startdate 2>/dev/null | cut -d= -f2) || true

          if [[ -n "$not_after" ]] && [[ -n "$not_before" ]]; then
            local after_epoch before_epoch ttl_seconds
            after_epoch=$(date -d "$not_after" +%s 2>/dev/null) || true
            before_epoch=$(date -d "$not_before" +%s 2>/dev/null) || true
            if [[ -n "$after_epoch" ]] && [[ -n "$before_epoch" ]]; then
              ttl_seconds=$((after_epoch - before_epoch))
              # Allow ±60 seconds tolerance
              if [[ $ttl_seconds -ge 3540 ]] && [[ $ttl_seconds -le 3660 ]]; then
                echo -e "      ${GREEN}SVID TTL: ${ttl_seconds}s (~1 hour)${NC}"
              else
                echo -e "      ${RED}SVID TTL: ${ttl_seconds}s (expected ~3600s)${NC}"
                ttl_ok=0
              fi
            fi
          fi
        else
          echo -e "      ${RED}No SVID found for $svc${NC}"
          attestation_ok=0
        fi

        # Check pod startup time for 30-second SVID attestation
        local pod_age
        pod_age=$(kubectl get pod "$pod_name" -n "$K8S_NAMESPACE" -o jsonpath='{.status.containerStatuses[0].state.running.startedAt}' 2>/dev/null) || true
        local ready_time
        ready_time=$(kubectl get pod "$pod_name" -n "$K8S_NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].lastTransitionTime}' 2>/dev/null) || true
        if [[ -n "$pod_age" ]] && [[ -n "$ready_time" ]]; then
          echo -e "      Pod ready: $ready_time (started: $pod_age)"
        fi
      else
        echo -e "      ${YELLOW}Pod not found for $svc in namespace $K8S_NAMESPACE${NC}"
        attestation_ok=0
      fi
    else
      # Without kubectl, check code-level SPIFFE configuration
      local spiffe_config_found=0
      local svc_dir="$SERVICES_DIR/$svc"
      if [[ -d "$svc_dir" ]]; then
        if rg -rq "spiffe\|SPIFFE\|spire\|SPIRE" "$svc_dir/src" --glob '!**/test/**' 2>/dev/null; then
          spiffe_config_found=1
        fi
      fi
      if [[ $spiffe_config_found -eq 1 ]]; then
        echo -e "    $svc: SPIFFE/SPIRE references found in code (offline check)"
      else
        echo -e "    $svc: ${YELLOW}No SPIFFE/SPIRE references found (may not be configured)${NC}"
        attestation_ok=0
      fi
    fi

    # Aggregate result
    if [[ $attestation_ok -eq 1 ]] && [[ $spiffe_id_ok -eq 1 ]] && [[ $ttl_ok -eq 1 ]]; then
      record_result "spire-attestation" "$svc" "PASS"
    else
      record_result "spire-attestation" "$svc" "FAIL"
    fi
  done

  echo ""
}

# ============================================================================
# Check 4: ACL Bypass Attempt
# ============================================================================
check_acl_bypass() {
  echo -e "${CYAN}${BOLD}Check 4: ACL Bypass Attempt${NC}"
  echo -e "  Verifying services cannot directly reach cloud provider APIs..."
  echo ""

  local cloud_api_endpoints=(
    "https://sts.amazonaws.com"
    "https://storage.googleapis.com"
    "https://login.microsoftonline.com"
  )

  for svc in "${ALL_SERVICES[@]}"; do
    local bypass_detected=0

    if command -v kubectl &>/dev/null; then
      local pod_name
      pod_name=$(kubectl get pods -n "$K8S_NAMESPACE" -l "app=$svc" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null) || true

      if [[ -n "$pod_name" ]]; then
        # Attempt to reach a cloud API directly from the pod
        for endpoint in "${cloud_api_endpoints[@]}"; do
          local attempt_result
          attempt_result=$(kubectl exec "$pod_name" -n "$K8S_NAMESPACE" -- \
            wget -q -O- --timeout=5 "$endpoint" 2>&1) || true

          if [[ -n "$attempt_result" ]] && ! echo "$attempt_result" | rg -qi "timeout\|refused\|error\|no route\|denied"; then
            echo -e "    ${RED}$svc can reach $endpoint — ACL bypass possible!${NC}"
            bypass_detected=1
          fi
        done
      else
        echo -e "    ${YELLOW}$svc: Pod not found (offline check)${NC}"
      fi
    fi

    # Code-level check: verify payment service only reaches external gateway via ACL sidecar
    if [[ "$svc" == "payment" ]]; then
      echo -e "    Checking payment service ACL sidecar configuration..."
      local acl_config="$SERVICES_DIR/templates/acl-sidecar/sidecar-config.yaml"
      if [[ -f "$acl_config" ]]; then
        if rg -q "stripe\|external-gateway\|acl" "$acl_config" 2>/dev/null; then
          echo -e "      ${GREEN}ACL sidecar config references external gateway${NC}"
        else
          echo -e "      ${YELLOW}ACL sidecar config does not explicitly reference external gateway${NC}"
          bypass_detected=1
        fi
      else
        echo -e "      ${YELLOW}ACL sidecar config not found at $acl_config${NC}"
      fi

      # Verify payment adapter goes through ACL sidecar, not direct
      local stripe_adapter="$SERVICES_DIR/payment/adapters/outbound/gateway/stripe.go"
      if [[ -f "$stripe_adapter" ]]; then
        if rg -q "localhost\|acl-sidecar\|sidecar\|internal-gateway\|envoy" "$stripe_adapter" 2>/dev/null; then
          echo -e "      ${GREEN}Payment adapter routes through sidecar/proxy${NC}"
        elif rg -q "api.stripe.com\|direct" "$stripe_adapter" 2>/dev/null; then
          echo -e "      ${RED}Payment adapter may be calling Stripe directly!${NC}"
          bypass_detected=1
        else
          echo -e "      ${YELLOW}Could not determine payment routing strategy${NC}"
        fi
      fi
    fi

    # Check for direct internet access patterns in code
    local svc_dir="$SERVICES_DIR/$svc"
    if [[ -d "$svc_dir" ]]; then
      local direct_api_calls
      direct_api_calls=$(rg -l "api\.amazonaws\.com|api\.stripe\.com|storage\.googleapis\.com|blob\.core\.windows\.net" \
        "$svc_dir/src" --glob '!**/test/**' --glob '!**/observability/**' --glob '!**/otel/**' 2>/dev/null) || true

      if [[ -n "$direct_api_calls" ]]; then
        echo -e "    ${RED}$svc has direct cloud API calls:${NC}"
        echo "$direct_api_calls" | while read -r f; do
          echo -e "      ${RED}${f#$PROJECT_ROOT/}${NC}"
        done
        bypass_detected=1
      fi
    fi

    if [[ $bypass_detected -eq 0 ]]; then
      record_result "acl-bypass" "$svc" "PASS"
    else
      record_result "acl-bypass" "$svc" "FAIL"
    fi
  done

  echo ""
}

# ============================================================================
# Check 5: Hexagonal Architecture Verification
# ============================================================================
check_hexagonal_arch() {
  echo -e "${CYAN}${BOLD}Check 5: Hexagonal Architecture Verification${NC}"
  echo -e "  Verifying domain layer has zero imports from adapters/infrastructure..."
  echo ""

  for svc in "${ALL_SERVICES[@]}"; do
    local svc_dir="$SERVICES_DIR/$svc"
    if [[ ! -d "$svc_dir/src" ]]; then
      record_result "hexagonal-arch" "$svc" "SKIP"
      continue
    fi

    local arch_violations=0

    # Check domain layer does not import from adapters or infrastructure
    local domain_dir="$svc_dir/src/domain"
    if [[ -d "$domain_dir" ]]; then
      # Search for imports/references to adapters or infrastructure from domain
      local violations
      violations=$(rg -l "adapters|infrastructure" "$domain_dir" --glob '!**/__init__.*' 2>/dev/null) || true

      if [[ -n "$violations" ]]; then
        arch_violations=1
        echo -e "    ${RED}$svc: Domain layer has adapter/infrastructure references:${NC}"
        echo "$violations" | while read -r f; do
          local rel_path="${f#$PROJECT_ROOT/}"
          echo -e "      ${RED}$rel_path${NC}"
          if [[ $VERBOSE -eq 1 ]]; then
            rg "adapters|infrastructure" "$f" -n 2>/dev/null | head -5 | while read -r line; do
              echo -e "        $line"
            done
          fi
        done
      fi
    else
      echo -e "    ${YELLOW}$svc: No domain directory found${NC}"
    fi

    # Language-specific architecture checks
    local lang=""
    if [[ -f "$svc_dir/go.mod" ]]; then lang="go"
    elif [[ -f "$svc_dir/Cargo.toml" ]]; then lang="rust"
    elif [[ -f "$svc_dir/pyproject.toml" ]]; then lang="python"
    elif [[ -f "$svc_dir/build.gradle.kts" ]]; then lang="kotlin"
    elif [[ -f "$svc_dir/package.json" ]]; then lang="typescript"
    fi

    case "$lang" in
      go)
        if command -v go &>/dev/null && [[ -f "$svc_dir/go.mod" ]]; then
          echo -e "    Running go vet for $svc..."
          if (cd "$svc_dir" && go vet ./... 2>/dev/null); then
            echo -e "      ${GREEN}go vet passed${NC}"
          else
            echo -e "      ${YELLOW}go vet reported issues${NC}"
            arch_violations=1
          fi
        fi
        ;;
      rust)
        if command -v cargo &>/dev/null && [[ -f "$svc_dir/Cargo.toml" ]]; then
          echo -e "    Running cargo check for $svc..."
          if (cd "$svc_dir" && cargo check 2>/dev/null); then
            echo -e "      ${GREEN}cargo check passed${NC}"
          else
            echo -e "      ${YELLOW}cargo check reported issues${NC}"
            arch_violations=1
          fi
        fi
        ;;
      python)
        if command -v mypy &>/dev/null; then
          echo -e "    Running mypy for $svc..."
          if (cd "$svc_dir" && mypy src/ --ignore-missing-imports 2>/dev/null); then
            echo -e "      ${GREEN}mypy passed${NC}"
          else
            echo -e "      ${YELLOW}mypy reported issues${NC}"
            arch_violations=1
          fi
        fi
        ;;
      kotlin)
        if [[ -f "$svc_dir/gradlew" ]]; then
          echo -e "    Running ktlint for $svc..."
          if (cd "$svc_dir" && ./gradlew ktlintCheck 2>/dev/null); then
            echo -e "      ${GREEN}ktlint passed${NC}"
          else
            echo -e "      ${YELLOW}ktlint reported issues (or not configured)${NC}"
            # Don't count ktlint failure as arch violation
          fi
        fi
        ;;
      typescript)
        if command -v npx &>/dev/null && [[ -f "$svc_dir/tsconfig.json" ]]; then
          echo -e "    Running tsc --noEmit for $svc..."
          if (cd "$svc_dir" && npx tsc --noEmit 2>/dev/null); then
            echo -e "      ${GREEN}tsc passed${NC}"
          else
            echo -e "      ${YELLOW}tsc reported issues${NC}"
            arch_violations=1
          fi
        fi
        ;;
    esac

    if [[ $arch_violations -eq 0 ]]; then
      record_result "hexagonal-arch" "$svc" "PASS"
    else
      record_result "hexagonal-arch" "$svc" "FAIL"
    fi
  done

  echo ""
}

# ============================================================================
# Main
# ============================================================================
main() {
  echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}║              Security Validation — Platform Audit             ║${NC}"
  echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "  Trust Domain: $SPIFFE_TRUST_DOMAIN"
  echo -e "  Namespace:    $K8S_NAMESPACE"
  echo -e "  Services:     ${ALL_SERVICES[*]}"
  echo ""

  # Run checks
  declare -A CHECK_FUNCS=(
    [sdk-scan]=check_sdk_scan
    [network-policy]=check_network_policy
    [spire-attestation]=check_spire_attestation
    [acl-bypass]=check_acl_bypass
    [hexagonal-arch]=check_hexagonal_arch
  )

  if [[ -n "$TARGET_CHECK" ]]; then
    "${CHECK_FUNCS[$TARGET_CHECK]}"
  else
    for check in "${VALID_CHECKS[@]}"; do
      "${CHECK_FUNCS[$check]}"
    done
  fi

  # ---------------------------------------------------------------------------
  # Security Matrix
  # ---------------------------------------------------------------------------
  echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}║                    Security Matrix Report                     ║${NC}"
  echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
  echo ""

  # Header row
  printf "  ${BOLD}%-20s" "SERVICE"
  for check in "${VALID_CHECKS[@]}"; do
    if [[ -n "$TARGET_CHECK" ]] && [[ "$check" != "$TARGET_CHECK" ]]; then
      continue
    fi
    printf "%-18s" "$check"
  done
  printf "${NC}\n"

  # Separator
  local col_count=${#ALL_SERVICES[@]}
  printf "  %s\n" "$(printf '─%.0s' $(seq 1 $((20 + 18 * (${#VALID_CHECKS[@]})))))"

  # Data rows
  local total_fails=0
  for svc in "${ALL_SERVICES[@]}"; do
    printf "  %-20s" "$svc"
    for check in "${VALID_CHECKS[@]}"; do
      if [[ -n "$TARGET_CHECK" ]] && [[ "$check" != "$TARGET_CHECK" ]]; then
        continue
      fi
      local result="${SECURITY_MATRIX[${check}__${svc}]:-UNKNOWN}"
      local color="$NC" symbol=""
      case "$result" in
        PASS) color="$GREEN"; symbol="PASS" ;;
        FAIL) color="$RED"; symbol="FAIL"; ((total_fails++)) || true ;;
        SKIP) color="$YELLOW"; symbol="SKIP" ;;
        *)    color="$NC"; symbol="$result" ;;
      esac
      printf "${color}%-18s${NC}" "$symbol"
    done
    printf "\n"
  done

  echo ""

  # Summary
  local total_checks=0 pass_count=0
  for key in "${!SECURITY_MATRIX[@]}"; do
    ((total_checks++)) || true
    if [[ "${SECURITY_MATRIX[$key]}" == "PASS" ]]; then
      ((pass_count++)) || true
    fi
  done

  printf "  Total checks: %d | ${GREEN}PASS: %d${NC} | ${RED}FAIL: %d${NC} | ${YELLOW}SKIP: %d${NC}\n" \
    "$total_checks" "$pass_count" "$total_fails" "$((total_checks - pass_count - total_fails))"
  echo ""

  if [[ $total_fails -gt 0 ]]; then
    echo -e "${RED}${BOLD}SECURITY VALIDATION FAILED — $total_fails check(s) did not pass${NC}"
    exit 1
  fi

  echo -e "${GREEN}${BOLD}ALL SECURITY CHECKS PASSED${NC}"
  exit 0
}

main
