#!/usr/bin/env bash
# ============================================================================
# Contract Test Runner — Polyglot Microservices Platform
# Runs contract tests across all 9 services with language-appropriate commands.
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICES_DIR="$PROJECT_ROOT/services"

# ---------------------------------------------------------------------------
# Service definitions: name -> language:test_command
# ---------------------------------------------------------------------------
declare -A SERVICE_LANG=(
  [gateway]="go"
  [payment]="go"
  [schema-registry]="go"
  [identity]="rust"
  [analytics]="python"
  [notification]="python"
  [rl-engine]="python"
  [order]="kotlin"
  [catalog]="typescript"
)

declare -A SERVICE_TEST_CMD=(
  [gateway]="go test ./tests/contract/... -v"
  [payment]="go test ./tests/contract/... -v"
  [schema-registry]="go test ./tests/contract/... -v"
  [identity]="cargo test --test contract"
  [analytics]="pytest tests/contract/ -v"
  [notification]="pytest tests/contract/ -v"
  [rl-engine]="pytest tests/contract/ -v"
  [order]="./gradlew contractTest"
  [catalog]="npm run test:contract"
)

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
  cat <<EOF
${BOLD}Contract Test Runner${NC}

Usage: $(basename "$0") [OPTIONS]

Options:
  --service <name>   Run contract tests for a single service only
  --verbose          Show full test output (not just summary)
  -h, --help         Show this help message

Supported services:
  go         : gateway, payment, schema-registry
  rust       : identity
  python     : analytics, notification, rl-engine
  kotlin     : order
  typescript : catalog

Examples:
  $(basename "$0")                        # Run all contract tests
  $(basename "$0") --service gateway      # Run only gateway contract tests
  $(basename "$0") --verbose              # Run with full output
EOF
  exit 0
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
VERBOSE=0
TARGET_SERVICE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service)
      TARGET_SERVICE="$2"
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
      usage >&2
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Validate --service argument
# ---------------------------------------------------------------------------
if [[ -n "$TARGET_SERVICE" ]]; then
  if [[ -z "${SERVICE_LANG[$TARGET_SERVICE]+x}" ]]; then
    echo -e "${RED}ERROR: Unknown service '$TARGET_SERVICE'${NC}" >&2
    echo -e "${YELLOW}Valid services: ${!SERVICE_LANG[*]}${NC}" >&2
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------
declare -A RESULTS
PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

# ---------------------------------------------------------------------------
# Run contract tests for a single service
# ---------------------------------------------------------------------------
run_contract_tests() {
  local service="$1"
  local lang="${SERVICE_LANG[$service]}"
  local cmd="${SERVICE_TEST_CMD[$service]}"
  local svc_dir="$SERVICES_DIR/$service"

  echo -e "${CYAN}━━━ ${BOLD}$service${NC} ${CYAN}($lang) ━━━${NC}"

  # Verify the service directory exists
  if [[ ! -d "$svc_dir" ]]; then
    echo -e "${YELLOW}  SKIP: Service directory not found at $svc_dir${NC}"
    RESULTS[$service]="SKIP"
    ((SKIP_COUNT++)) || true
    return 0
  fi

  # Language-specific prerequisite checks
  case "$lang" in
    go)
      if ! command -v go &>/dev/null; then
        echo -e "${YELLOW}  SKIP: 'go' not found on PATH${NC}"
        RESULTS[$service]="SKIP"
        ((SKIP_COUNT++)) || true
        return 0
      fi
      if [[ ! -f "$svc_dir/go.mod" ]]; then
        echo -e "${YELLOW}  SKIP: go.mod not found${NC}"
        RESULTS[$service]="SKIP"
        ((SKIP_COUNT++)) || true
        return 0
      fi
      ;;
    rust)
      if ! command -v cargo &>/dev/null; then
        echo -e "${YELLOW}  SKIP: 'cargo' not found on PATH${NC}"
        RESULTS[$service]="SKIP"
        ((SKIP_COUNT++)) || true
        return 0
      fi
      if [[ ! -f "$svc_dir/Cargo.toml" ]]; then
        echo -e "${YELLOW}  SKIP: Cargo.toml not found${NC}"
        RESULTS[$service]="SKIP"
        ((SKIP_COUNT++)) || true
        return 0
      fi
      ;;
    python)
      if ! command -v pytest &>/dev/null; then
        echo -e "${YELLOW}  SKIP: 'pytest' not found on PATH${NC}"
        RESULTS[$service]="SKIP"
        ((SKIP_COUNT++)) || true
        return 0
      fi
      ;;
    kotlin)
      if [[ ! -f "$svc_dir/gradlew" ]] && [[ ! -f "$svc_dir/gradlew.bat" ]]; then
        echo -e "${YELLOW}  SKIP: gradlew not found${NC}"
        RESULTS[$service]="SKIP"
        ((SKIP_COUNT++)) || true
        return 0
      fi
      ;;
    typescript)
      if ! command -v npm &>/dev/null; then
        echo -e "${YELLOW}  SKIP: 'npm' not found on PATH${NC}"
        RESULTS[$service]="SKIP"
        ((SKIP_COUNT++)) || true
        return 0
      fi
      if [[ ! -f "$svc_dir/package.json" ]]; then
        echo -e "${YELLOW}  SKIP: package.json not found${NC}"
        RESULTS[$service]="SKIP"
        ((SKIP_COUNT++)) || true
        return 0
      fi
      ;;
  esac

  # Run the tests
  local start_time end_time elapsed
  start_time=$(date +%s)

  local output_file
  output_file=$(mktemp /tmp/contract-test-${service}-XXXXXX.log)

  echo -e "  Running: ${cmd}"
  echo -e "  CWD:     ${svc_dir}"

  local exit_code=0
  if [[ $VERBOSE -eq 1 ]]; then
    (cd "$svc_dir" && eval "$cmd" 2>&1 | tee "$output_file") || exit_code=$?
  else
    (cd "$svc_dir" && eval "$cmd" > "$output_file" 2>&1) || exit_code=$?
  fi

  end_time=$(date +%s)
  elapsed=$((end_time - start_time))

  if [[ $exit_code -eq 0 ]]; then
    echo -e "  ${GREEN}PASS${NC} (${elapsed}s)"
    RESULTS[$service]="PASS"
    ((PASS_COUNT++)) || true
  else
    echo -e "  ${RED}FAIL${NC} (${elapsed}s)"
    if [[ $VERBOSE -eq 0 ]]; then
      echo -e "  ${YELLOW}--- Output (last 30 lines) ---${NC}"
      tail -30 "$output_file" | sed 's/^/  /'
      echo -e "  ${YELLOW}--- End output ---${NC}"
    fi
    RESULTS[$service]="FAIL"
    ((FAIL_COUNT++)) || true
  fi

  rm -f "$output_file"
  return $exit_code
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
  echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}║          Contract Test Runner — All Services            ║${NC}"
  echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
  echo ""

  # Determine which services to run
  local -a services=()
  if [[ -n "$TARGET_SERVICE" ]]; then
    services=("$TARGET_SERVICE")
  else
    # Ordered by language group for readability
    services=(gateway payment schema-registry identity analytics notification rl-engine order catalog)
  fi

  local overall_start overall_end overall_elapsed
  overall_start=$(date +%s)
  local any_failure=0

  for svc in "${services[@]}"; do
    run_contract_tests "$svc" || any_failure=1
    echo ""
  done

  overall_end=$(date +%s)
  overall_elapsed=$((overall_end - overall_start))

  # ---------------------------------------------------------------------------
  # Summary table
  # ---------------------------------------------------------------------------
  echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}║                    Summary Report                       ║${NC}"
  echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
  echo ""
  printf "  ${BOLD}%-20s %-12s %-10s${NC}\n" "SERVICE" "LANGUAGE" "RESULT"
  printf "  %s\n" "$(printf '─%.0s' {1..42})"

  for svc in "${services[@]}"; do
    local lang="${SERVICE_LANG[$svc]}"
    local result="${RESULTS[$svc]:-UNKNOWN}"
    local color="$NC"
    case "$result" in
      PASS) color="$GREEN" ;;
      FAIL) color="$RED" ;;
      SKIP) color="$YELLOW" ;;
    esac
    printf "  %-20s %-12s ${color}%-10s${NC}\n" "$svc" "$lang" "$result"
  done

  echo ""
  printf "  Total: %d | ${GREEN}PASS: %d${NC} | ${RED}FAIL: %d${NC} | ${YELLOW}SKIP: %d${NC} | Time: %ds\n" \
    "${#services[@]}" "$PASS_COUNT" "$FAIL_COUNT" "$SKIP_COUNT" "$overall_elapsed"
  echo ""

  if [[ $FAIL_COUNT -gt 0 ]]; then
    echo -e "${RED}${BOLD}CONTRACT TESTS FAILED${NC}"
    exit 1
  fi

  echo -e "${GREEN}${BOLD}ALL CONTRACT TESTS PASSED${NC}"
  exit 0
}

main
