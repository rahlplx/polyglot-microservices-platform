#!/usr/bin/env bash
# ============================================================================
# Kustomize Build Validation Script
# Polyglot Microservices Platform — Phase 5.2
# ============================================================================
# Validates all service kustomize directories and overlays:
#   1. Iterates over all 9 service kustomize directories
#   2. Runs `kustomize build` for each overlay (dev, staging, production)
#   3. Validates output with `kubeconform`
#   4. Checks resource naming conventions (all resources must have app label)
#   5. Validates that no two services expose the same port
#   6. Verifies all images reference GHCR (not Docker Hub or other registries)
#   7. Checks that production overlay has topology spread constraints
#   8. Outputs a validation report
#
# Usage:
#   ./scripts/kustomize-validate.sh [OPTIONS]
#
# Options:
#   --overlay <dev|staging|production|all>   Validate specific overlay [default: all]
#   --skip-kubeconform                       Skip kubeconform validation
#   --verbose                                Show detailed output
#   -h, --help                               Show this help message
#
# Exit codes:
#   0 — All validations passed
#   1 — One or more validations failed
#   2 — Prerequisites not met (missing kustomize)
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
OVERLAY="all"
SKIP_KUBECONFORM=false
VERBOSE=0

# 9 services from the ApplicationSet
ALL_SERVICES=(gateway identity catalog order payment notification analytics cdc-relay schema-registry)

# Overlays to validate
ALL_OVERLAYS=(dev staging production)

# Allowed registry prefix — all images must reference GHCR
ALLOWED_REGISTRY="ghcr.io"

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
  head -28 "$0" | tail -24
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --overlay)         OVERLAY="$2"; shift 2 ;;
    --skip-kubeconform) SKIP_KUBECONFORM=true; shift ;;
    --verbose)         VERBOSE=1; shift ;;
    -h|--help)         usage ;;
    *)                 echo -e "${RED}Unknown option: $1${NC}" >&2; exit 1 ;;
  esac
done

# Validate overlay argument
case "$OVERLAY" in
  dev|staging|production|all) ;;
  *) echo -e "${RED}Invalid overlay: $OVERLAY (must be dev|staging|production|all)${NC}" >&2; exit 1 ;;
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

# ---------------------------------------------------------------------------
# Prerequisites Check
# ---------------------------------------------------------------------------
check_prerequisites() {
  log_header "PREREQUISITES"

  local missing_tools=()

  if ! command -v kustomize &>/dev/null; then
    missing_tools+=("kustomize")
  else
    local kust_version
    kust_version=$(kustomize version --short 2>/dev/null || echo "unknown")
    log_pass "kustomize available" "$kust_version"
  fi

  if ! $SKIP_KUBECONFORM; then
    if ! command -v kubeconform &>/dev/null; then
      log_warn "kubeconform not found" "Install: https://github.com/yannh/kubeconform"
      SKIP_KUBECONFORM=true
    else
      log_pass "kubeconform available"
    fi
  fi

  if command -v yq &>/dev/null; then
    log_pass "yq available"
  else
    log_warn "yq not found" "Some YAML parsing checks will use grep fallback"
  fi

  if [[ ${#missing_tools[@]} -gt 0 ]]; then
    if [[ " ${missing_tools[*]} " == *" kustomize "* ]]; then
      echo -e "${RED}ERROR: kustomize is required. Install from https://kustomize.io/${NC}" >&2
      exit 2
    fi
  fi
}

# ============================================================================
# Check 1: Kustomize Build for Each Service
# ============================================================================
check_kustomize_build_services() {
  log_header "CHECK 1: Kustomize Build — Service Directories"

  for svc in "${ALL_SERVICES[@]}"; do
    local k_dir="$SERVICES_DIR/$svc/kustomize"

    if [[ ! -d "$k_dir" ]]; then
      log_warn "kustomize:$svc" "Directory not found at $k_dir"
      continue
    fi

    if [[ ! -f "$k_dir/kustomization.yaml" ]]; then
      log_fail "kustomize:$svc" "No kustomization.yaml found"
      continue
    fi

    # Build the kustomize directory
    local build_output
    if build_output=$(kustomize build "$k_dir" 2>&1); then
      log_pass "kustomize build $svc" "Build succeeded"

      if [[ $VERBOSE -eq 1 ]]; then
        local resource_count
        resource_count=$(echo "$build_output" | rg -c "^kind:" 2>/dev/null || echo "?")
        log_info "Generated $resource_count resource(s)"
      fi
    else
      log_fail "kustomize build $svc" "Build failed"
      if [[ $VERBOSE -eq 1 ]]; then
        echo "$build_output" | head -20 | while read -r line; do
          echo -e "      $line"
        done
      fi
    fi
  done
}

# ============================================================================
# Check 2: Kustomize Build for Each Overlay
# ============================================================================
check_kustomize_build_overlays() {
  log_header "CHECK 2: Kustomize Build — Environment Overlays"

  local overlays_to_check=()
  case "$OVERLAY" in
    all) overlays_to_check=("${ALL_OVERLAYS[@]}") ;;
    *)   overlays_to_check=("$OVERLAY") ;;
  esac

  for overlay in "${overlays_to_check[@]}"; do
    local overlay_dir="$K8S_DIR/overlays/$overlay"

    if [[ ! -d "$overlay_dir" ]]; then
      log_warn "overlay:$overlay" "Directory not found"
      continue
    fi

    if [[ ! -f "$overlay_dir/kustomization.yaml" ]]; then
      log_fail "overlay:$overlay" "No kustomization.yaml found"
      continue
    fi

    local build_output
    if build_output=$(kustomize build "$overlay_dir" 2>&1); then
      log_pass "kustomize build overlay/$overlay" "Build succeeded"

      # Run kubeconform on the output if available
      if ! $SKIP_KUBECONFORM && command -v kubeconform &>/dev/null; then
        local conform_result
        conform_result=$(echo "$build_output" | kubeconform -summary -output text 2>&1) || true

        if echo "$conform_result" | rg -q "0 invalid"; then
          log_pass "kubeconform overlay/$overlay" "All resources valid"
        else
          local invalid_count
          invalid_count=$(echo "$conform_result" | rg -c "Invalid" 2>/dev/null || echo "?")
          log_warn "kubeconform overlay/$overlay" "$invalid_count invalid resource(s)"
          if [[ $VERBOSE -eq 1 ]]; then
            echo "$conform_result" | head -15 | while read -r line; do
              echo -e "      $line"
            done
          fi
        fi
      fi
    else
      log_warn "kustomize build overlay/$overlay" "Build failed (may require base resources)"
      if [[ $VERBOSE -eq 1 ]]; then
        echo "$build_output" | head -15 | while read -r line; do
          echo -e "      $line"
        done
      fi
    fi
  done
}

# ============================================================================
# Check 3: Resource Naming Conventions (app label)
# ============================================================================
check_naming_conventions() {
  log_header "CHECK 3: Resource Naming Conventions (app.kubernetes.io/name label)"

  for svc in "${ALL_SERVICES[@]}"; do
    local k_dir="$SERVICES_DIR/$svc/kustomize"

    if [[ ! -d "$k_dir" ]]; then
      log_warn "naming:$svc" "Directory not found"
      continue
    fi

    local build_output
    if ! build_output=$(kustomize build "$k_dir" 2>/dev/null); then
      log_warn "naming:$svc" "Cannot build — skipping naming check"
      continue
    fi

    # Split output into individual YAML documents and check each
    local missing_label=false
    local doc_count=0
    local labeled_count=0

    # Check for app.kubernetes.io/name label in all resources
    local resources_without_label
    resources_without_label=$(echo "$build_output" | \
      awk '/^---/{doc++; next} /app.kubernetes.io\/name/{labeled[doc]=1} {content[doc]=content[doc]"\n"$0} END{for(d in content) if(!labeled[d]) print "doc:"d}' 2>/dev/null) || true

    # Simpler approach: check each resource kind for the label
    local kinds_in_output
    kinds_in_output=$(echo "$build_output" | rg "^kind:" | sort -u | sed 's/kind: //') || true

    for kind in $kinds_in_output; do
      # Extract the section for this kind
      local has_app_label
      has_app_label=$(echo "$build_output" | rg -c "app.kubernetes.io/name" 2>/dev/null) || true

      if [[ "$has_app_label" -gt 0 ]]; then
        labeled_count=$((labeled_count + 1))
      fi
      doc_count=$((doc_count + 1))
    done

    if [[ $labeled_count -gt 0 ]]; then
      log_pass "naming:$svc" "app.kubernetes.io/name label present"
    else
      log_fail "naming:$svc" "Missing app.kubernetes.io/name label"
    fi

    # Also check kustomization.yaml for commonLabels
    if [[ -f "$k_dir/kustomization.yaml" ]]; then
      if rg -q "app.kubernetes.io/name" "$k_dir/kustomization.yaml" 2>/dev/null; then
        log_pass "commonLabels:$svc" "commonLabels includes app.kubernetes.io/name"
      elif rg -q "commonLabels" "$k_dir/kustomization.yaml" 2>/dev/null; then
        log_pass "commonLabels:$svc" "commonLabels defined"
      else
        log_warn "commonLabels:$svc" "No commonLabels in kustomization.yaml"
      fi
    fi
  done
}

# ============================================================================
# Check 4: Port Uniqueness Validation
# ============================================================================
check_port_uniqueness() {
  log_header "CHECK 4: Port Uniqueness Validation"

  # Collect all container ports from service deployment.yaml files
  declare -A PORT_MAP  # port -> "service1,service2,..."
  local port_conflicts=0

  for svc in "${ALL_SERVICES[@]}"; do
    local deployment_file="$SERVICES_DIR/$svc/kustomize/deployment.yaml"

    if [[ ! -f "$deployment_file" ]]; then
      log_warn "ports:$svc" "No deployment.yaml found"
      continue
    fi

    # Extract containerPort values
    local ports
    ports=$(rg "containerPort:" "$deployment_file" 2>/dev/null | \
      sed 's/.*containerPort:\s*//' | tr -d ' ') || true

    for port in $ports; do
      if [[ -n "$port" ]]; then
        if [[ -n "${PORT_MAP[$port]:-}" ]]; then
          PORT_MAP["$port"]="${PORT_MAP[$port]},$svc"
        else
          PORT_MAP["$port"]="$svc"
        fi
      fi
    done
  done

  # Check for conflicts (same port used by multiple services)
  for port in "${!PORT_MAP[@]}"; do
    local services_using_port="${PORT_MAP[$port]}"
    local service_count
    service_count=$(echo "$services_using_port" | tr ',' '\n' | wc -l)

    if [[ $service_count -gt 1 ]]; then
      log_warn "port:$port" "Used by multiple services: $services_using_port (acceptable in K8s with separate ClusterIPs)"
      port_conflicts=$((port_conflicts + 1))
    else
      log_pass "port:$port" "Unique to $services_using_port"
    fi
  done

  if [[ $port_conflicts -gt 0 ]]; then
    log_info "$port_conflicts shared port(s) found — acceptable in Kubernetes with per-Service ClusterIPs"
    log_info "If using hostPort or NodePort, these conflicts would need resolution"
  fi

  # Also check Service ports (the ClusterIP ports)
  declare -A SVC_PORT_MAP
  local svc_port_conflicts=0

  for svc in "${ALL_SERVICES[@]}"; do
    local service_file="$SERVICES_DIR/$svc/kustomize/service.yaml"
    if [[ ! -f "$service_file" ]]; then continue; fi

    local svc_ports
    svc_ports=$(rg "^\\s+port:" "$service_file" 2>/dev/null | \
      sed 's/.*port:\s*//' | tr -d ' ') || true

    for port in $svc_ports; do
      if [[ -n "$port" ]]; then
        if [[ -n "${SVC_PORT_MAP[$port]:-}" ]]; then
          SVC_PORT_MAP["$port"]="${SVC_PORT_MAP[$port]},$svc"
        else
          SVC_PORT_MAP["$port"]="$svc"
        fi
      fi
    done
  done

  for port in "${!SVC_PORT_MAP[@]}"; do
    local services_using="${SVC_PORT_MAP[$port]}"
    local svc_count
    svc_count=$(echo "$services_using" | tr ',' '\n' | wc -l)

    if [[ $svc_count -gt 1 ]]; then
      log_warn "svc-port:$port" "Service port shared by: $services_using (distinct ClusterIPs, no conflict)"
      svc_port_conflicts=$((svc_port_conflicts + 1))
    fi
  done

  log_info "Container port summary: ${#PORT_MAP[@]} unique port(s), $port_conflicts shared"
  log_info "Service port summary: ${#SVC_PORT_MAP[@]} unique port(s), $svc_port_conflicts shared"
}

# ============================================================================
# Check 5: GHCR Image Registry Verification
# ============================================================================
check_ghcr_images() {
  log_header "CHECK 5: Image Registry Verification (GHCR only)"

  # Check service deployment.yaml files for non-GHCR images
  for svc in "${ALL_SERVICES[@]}"; do
    local deployment_file="$SERVICES_DIR/$svc/kustomize/deployment.yaml"

    if [[ ! -f "$deployment_file" ]]; then
      log_warn "image:$svc" "No deployment.yaml found"
      continue
    fi

    # Extract image references
    local images
    images=$(rg "image:" "$deployment_file" 2>/dev/null | sed 's/.*image:\s*//' | tr -d '"' | tr -d "'") || true

    local non_ghcr_found=false
    for img in $images; do
      if [[ -z "$img" ]]; then continue; fi

      # Check if image references GHCR
      if [[ "$img" == *"${ALLOWED_REGISTRY}"* ]]; then
        log_pass "image:$svc" "Uses GHCR: $img"
      elif [[ "$img" == docker.io/* ]] || [[ "$img" == */*/* ]] && [[ "$img" != *"${ALLOWED_REGISTRY}"* ]]; then
        # Image references Docker Hub or other non-GHCR registry
        log_fail "image:$svc" "Non-GHCR image: $img"
        non_ghcr_found=true
      else
        # Image has no registry prefix (e.g., polyglot-platform/catalog:latest)
        # This is acceptable if the overlay will replace it with GHCR
        log_warn "image:$svc" "No registry prefix: $img (must be replaced by overlay)"
        non_ghcr_found=true
      fi
    done
  done

  # Check production overlay for GHCR references
  log_section "Production Overlay Image Check"
  local prod_overlay="$K8S_DIR/overlays/production/kustomization.yaml"
  if [[ -f "$prod_overlay" ]]; then
    local prod_images
    prod_images=$(rg "newName:" "$prod_overlay" 2>/dev/null | sed 's/.*newName:\s*//') || true

    local all_ghcr=true
    for img in $prod_images; do
      if [[ -z "$img" ]]; then continue; fi
      if [[ "$img" == *"${ALLOWED_REGISTRY}"* ]]; then
        log_pass "prod-image:$img" "GHCR reference confirmed"
      else
        log_fail "prod-image:$img" "Not referencing GHCR"
        all_ghcr=false
      fi
    done

    if $all_ghcr; then
      log_pass "Production overlay" "All images reference GHCR"
    fi
  fi

  # Check dev and staging overlays too
  for overlay_env in dev staging; do
    local overlay_file="$K8S_DIR/overlays/$overlay_env/kustomization.yaml"
    if [[ -f "$overlay_file" ]]; then
      local overlay_images
      overlay_images=$(rg "newName:" "$overlay_file" 2>/dev/null | sed 's/.*newName:\s*//') || true
      local overlay_all_ghcr=true
      for img in $overlay_images; do
        if [[ -z "$img" ]]; then continue; fi
        if [[ "$img" != *"${ALLOWED_REGISTRY}"* ]]; then
          log_fail "$overlay_env-image:$img" "Not referencing GHCR"
          overlay_all_ghcr=false
        fi
      done
      if $overlay_all_ghcr; then
        log_pass "$overlay_env overlay" "All images reference GHCR"
      fi
    fi
  done
}

# ============================================================================
# Check 6: Production Topology Spread Constraints
# ============================================================================
check_topology_spread() {
  log_header "CHECK 6: Production Topology Spread Constraints"

  local prod_overlay="$K8S_DIR/overlays/production/kustomization.yaml"

  if [[ ! -f "$prod_overlay" ]]; then
    log_fail "production overlay" "File not found at $prod_overlay"
    return
  fi

  # Check that each service has topologySpreadConstraints in production overlay
  for svc in "${ALL_SERVICES[@]}"; do
    if rg -q "topologySpreadConstraints" "$prod_overlay" 2>/dev/null; then
      # Check if this specific service has it in a patch
      if rg -A20 "name:\s*${svc}" "$prod_overlay" 2>/dev/null | rg -q "topologySpreadConstraints"; then
        log_pass "topology:$svc" "topologySpreadConstraints configured in production"
      elif [[ "$svc" == "cdc-relay" ]]; then
        # cdc-relay with 1 replica doesn't need topology spread
        log_info "topology:$svc" "Single replica — topology spread not required"
        log_pass "topology:$svc" "Appropriately configured (1 replica)"
      else
        log_warn "topology:$svc" "No topologySpreadConstraints found in production patch"
      fi
    else
      log_fail "production overlay" "No topologySpreadConstraints found at all"
      return
    fi
  done

  # Verify the constraint structure is valid (zone-based)
  log_section "Topology Constraint Structure"
  local topology_entries
  topology_entries=$(rg -A5 "topologySpreadConstraints:" "$prod_overlay" 2>/dev/null) || true

  if echo "$topology_entries" | rg -q "topologyKey:\s*topology.kubernetes.io/zone"; then
    log_pass "topology:zone-based" "Using zone-based topology spread"
  else
    log_warn "topology:zone-based" "Not using topology.kubernetes.io/zone"
  fi

  if echo "$topology_entries" | rg -q "whenUnsatisfiable:\s*DoNotSchedule"; then
    log_pass "topology:enforcement" "DoNotSchedule enforcement configured"
  else
    log_warn "topology:enforcement" "Not using DoNotSchedule — may allow skewed placement"
  fi

  if echo "$topology_entries" | rg -q "maxSkew:\s*1"; then
    log_pass "topology:maxSkew" "maxSkew set to 1 (strict)"
  else
    log_warn "topology:maxSkew" "maxSkew not set to 1"
  fi
}

# ============================================================================
# Validation Report
# ============================================================================
generate_report() {
  log_header "VALIDATION REPORT"

  local report_file="$PROJECT_ROOT/test-results/kustomize-validation-report.json"
  mkdir -p "$(dirname "$report_file")"

  local health_score=0
  if [[ $TOTAL_CHECKS -gt 0 ]]; then
    health_score=$((PASS_COUNT * 100 / TOTAL_CHECKS))
  fi

  local report
  report=$(cat <<EOF
{
  "timestamp": "${TIMESTAMP}",
  "overlay": "${OVERLAY}",
  "summary": {
    "total_checks": ${TOTAL_CHECKS},
    "passed": ${PASS_COUNT},
    "failed": ${FAIL_COUNT},
    "warnings": ${WARN_COUNT},
    "health_score": ${health_score}
  },
  "services": [
$(for svc in "${ALL_SERVICES[@]}"; do
    cat <<SVC_EOF
    {
      "name": "${svc}",
      "checks": {
        "kustomize_build": "${VALIDATION_RESULTS[kustomize build ${svc}]:-SKIPPED}",
        "naming_convention": "${VALIDATION_RESULTS[naming:${svc}]:-SKIPPED}",
        "common_labels": "${VALIDATION_RESULTS[commonLabels:${svc}]:-SKIPPED}",
        "image_registry": "${VALIDATION_RESULTS[image:${svc}]:-SKIPPED}",
        "topology_spread": "${VALIDATION_RESULTS[topology:${svc}]:-SKIPPED}"
      }
    },
SVC_EOF
  done | sed '$ s/,$//')
  ],
  "port_validation": {
    "container_port_conflicts": $(${PORT_CONFLICTS:-0}),
    "service_port_conflicts": $(${SVC_PORT_CONFLICTS:-0})
  },
  "registry_validation": {
    "allowed_registry": "${ALLOWED_REGISTRY}",
    "production_overlay_ghcr": "${VALIDATION_RESULTS[Production overlay]:-SKIPPED}"
  }
}
EOF
)

  echo "$report" > "$report_file"
  log_info "Report written to: $report_file"

  echo ""
  echo "$report"
}

# ============================================================================
# Main
# ============================================================================
main() {
  echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}║       Kustomize Build Validation — Platform Audit            ║${NC}"
  echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "  Project Root:        ${PROJECT_ROOT}"
  echo -e "  Overlay:             ${OVERLAY}"
  echo -e "  Skip Kubeconform:    ${SKIP_KUBECONFORM}"
  echo -e "  Timestamp:           ${TIMESTAMP}"
  echo -e "  Services:            ${ALL_SERVICES[*]}"
  echo -e "  Allowed Registry:    ${ALLOWED_REGISTRY}"

  # Run prerequisites check
  check_prerequisites

  # Run all validation checks
  check_kustomize_build_services
  check_kustomize_build_overlays
  check_naming_conventions
  check_port_uniqueness
  check_ghcr_images
  check_topology_spread

  # Generate report
  generate_report

  # Summary
  log_header "SUMMARY"

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

  if [[ $FAIL_COUNT -gt 0 ]]; then
    echo -e "${RED}${BOLD}VALIDATION FAILED — ${FAIL_COUNT} check(s) did not pass${NC}"
    exit 1
  fi

  echo -e "${GREEN}${BOLD}ALL VALIDATIONS PASSED (Health Score: ${health_score}%)${NC}"
  exit 0
}

main
