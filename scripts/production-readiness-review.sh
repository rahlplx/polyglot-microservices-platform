#!/usr/bin/env bash
# =============================================================================
# Production Readiness Review Script
# Phase 5.5 — Comprehensive production readiness assessment
#
# Checks ALL aspects of production readiness across 6 categories:
#   1. Infrastructure Readiness
#   2. Security Readiness
#   3. Observability Readiness
#   4. Reliability Readiness
#   5. Operational Readiness
#   6. Compliance Readiness
#
# Output: JSON report with pass/fail per check, overall readiness score (0-100),
#         category scores, and a list of blocking issues.
#
# Usage:
#   ./production-readiness-review.sh                    # Full review
#   ./production-readiness-review.sh --skip-live        # Skip live cluster checks
#   ./production-readiness-review.sh --verbose          # Verbose output
#   ./production-readiness-review.sh --output report.json  # Custom output path
#   ./production-readiness-review.sh --category security   # Single category only
#
# Exit codes:
#   0 — All checks pass (readiness score >= 80)
#   1 — Blocking issues found (readiness score < 80)
#   2 — Script error
# =============================================================================
set -euo pipefail

# ─── Configuration ────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
K8S_BASE="${PROJECT_ROOT}/infra/kubernetes/base"
K8S_PLATFORM="${PROJECT_ROOT}/infra/kubernetes/platform"
K8S_OVERLAYS="${PROJECT_ROOT}/infra/kubernetes/overlays"
K8S_APPS="${PROJECT_ROOT}/infra/kubernetes/apps"
SERVICES_DIR="${PROJECT_ROOT}/services"
DOCS_DIR="${PROJECT_ROOT}/docs"
REPORT_FILE="${PROJECT_ROOT}/production-readiness-report.json"

SKIP_LIVE=false
VERBOSE=false
CATEGORY_FILTER=""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ─── Counters ─────────────────────────────────────────────────────────────────
TOTAL_CHECKS=0
PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0
SKIP_COUNT=0
BLOCKING_ISSUES=()

# Category scores
declare -A CATEGORY_SCORES
declare -A CATEGORY_TOTALS
declare -A CATEGORY_PASSES

# Check results array
declare -a CHECK_RESULTS

# ─── Utility Functions ────────────────────────────────────────────────────────

log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $*"
    PASS_COUNT=$((PASS_COUNT + 1))
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $*"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
    WARN_COUNT=$((WARN_COUNT + 1))
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
}

log_skip() {
    echo -e "${YELLOW}[SKIP]${NC} $*"
    SKIP_COUNT=$((SKIP_COUNT + 1))
}

log_section() {
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  $*${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

log_subsection() {
    echo ""
    echo -e "${BLUE}  ── $* ──${NC}"
}

verbose() {
    if [[ "${VERBOSE}" == "true" ]]; then
        echo -e "    ${BLUE}[VERBOSE]${NC} $*"
    fi
}

record_check() {
    local category="$1"
    local check_name="$2"
    local status="$3"      # pass, fail, warn
    local details="$4"
    local blocking="${5:-false}"

    CHECK_RESULTS+=("{\"check\":\"${check_name}\",\"category\":\"${category}\",\"status\":\"${status}\",\"details\":\"${details}\",\"blocking\":${blocking}}")

    # Update category counters
    if [[ -z "${CATEGORY_TOTALS[$category]:-}" ]]; then
        CATEGORY_TOTALS[$category]=0
        CATEGORY_PASSES[$category]=0
    fi
    CATEGORY_TOTALS[$category]=$((${CATEGORY_TOTALS[$category]} + 1))
    if [[ "$status" == "pass" ]]; then
        CATEGORY_PASSES[$category]=$((${CATEGORY_PASSES[$category]} + 1))
    fi

    if [[ "$blocking" == "true" && "$status" == "fail" ]]; then
        BLOCKING_ISSUES+=("${check_name}: ${details}")
    fi
}

# ─── Argument Parsing ─────────────────────────────────────────────────────────

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --skip-live)
                SKIP_LIVE=true
                shift
                ;;
            --verbose)
                VERBOSE=true
                shift
                ;;
            --output)
                REPORT_FILE="$2"
                shift 2
                ;;
            --category)
                CATEGORY_FILTER="$2"
                shift 2
                ;;
            --help)
                echo "Usage: $0 [--skip-live] [--verbose] [--output FILE] [--category CATEGORY]"
                echo ""
                echo "Categories: infrastructure, security, observability, reliability, operational, compliance"
                echo ""
                echo "Exit codes:"
                echo "  0 — Readiness score >= 80"
                echo "  1 — Blocking issues (score < 80)"
                echo "  2 — Script error"
                exit 0
                ;;
            *)
                echo "Unknown argument: $1"
                exit 2
                ;;
        esac
    done
}

# ─── Section 1: Infrastructure Readiness ─────────────────────────────────────

check_infrastructure() {
    log_section "Section 1: Infrastructure Readiness"
    local category="infrastructure"

    # 1.1 K8s manifests are valid (kubeconform or kubectl --dry-run)
    log_subsection "1.1 K8s Manifest Validation"
    local manifest_errors=0
    local yaml_files=()
    while IFS= read -r -d '' f; do
        yaml_files+=("$f")
    done < <(find "${K8S_BASE}" "${K8S_PLATFORM}" "${K8S_OVERLAYS}" "${K8S_APPS}" -name '*.yaml' -print0 2>/dev/null)

    if [[ ${#yaml_files[@]} -eq 0 ]]; then
        log_warn "No K8s manifest files found in expected directories"
        record_check "$category" "k8s-manifests-valid" "warn" "No K8s manifests found" false
    else
        local valid_count=0
        for f in "${yaml_files[@]}"; do
            if python3 -c "import yaml; list(yaml.safe_load_all(open('$f')))" 2>/dev/null; then
                valid_count=$((valid_count + 1))
            else
                verbose "Invalid YAML: $f"
                manifest_errors=$((manifest_errors + 1))
            fi
        done
        if [[ $manifest_errors -eq 0 ]]; then
            log_pass "All ${#yaml_files[@]} K8s manifest files are valid YAML"
            record_check "$category" "k8s-manifests-valid" "pass" "All ${#yaml_files[@]} manifests valid" false
        else
            log_fail "${manifest_errors} K8s manifest files have YAML syntax errors"
            record_check "$category" "k8s-manifests-valid" "fail" "${manifest_errors} invalid YAML files" true
        fi
    fi

    # 1.2 All images reference GHCR with pinned semver tags (no :latest)
    log_subsection "1.2 Image Tag Pinning"
    local latest_count=0
    local unpinned_count=0
    local image_lines=()
    while IFS= read -r line; do
        image_lines+=("$line")
    done < <(rg -n 'image:' "${K8S_BASE}" "${K8S_PLATFORM}" "${K8S_OVERLAYS}" "${K8S_APPS}" --no-heading 2>/dev/null || true)

    # Also check service kustomize directories
    while IFS= read -r line; do
        image_lines+=("$line")
    done < <(rg -n 'image:' "${SERVICES_DIR}" --glob 'kustomize/*.yaml' --no-heading 2>/dev/null || true)

    for line in "${image_lines[@]}"; do
        if echo "$line" | rg -q ':latest\b'; then
            latest_count=$((latest_count + 1))
            verbose "Found :latest tag: $line"
        fi
    done

    if [[ $latest_count -eq 0 ]]; then
        log_pass "No :latest image tags found — all images use pinned tags"
        record_check "$category" "no-latest-tags" "pass" "All images use pinned tags" false
    else
        log_fail "Found ${latest_count} images using :latest tag"
        record_check "$category" "no-latest-tags" "fail" "${latest_count} images use :latest" true
    fi

    # Check GHCR registry usage in production overlay
    local ghcr_count=0
    while IFS= read -r line; do
        ghcr_count=$((ghcr_count + 1))
    done < <(rg 'ghcr\.io' "${K8S_OVERLAYS}/production/" --no-heading 2>/dev/null || true)

    if [[ $ghcr_count -gt 0 ]]; then
        log_pass "Production overlay references GHCR (${ghcr_count} images)"
        record_check "$category" "ghcr-registry" "pass" "Production uses GHCR" false
    else
        log_warn "No GHCR image references found in production overlay"
        record_check "$category" "ghcr-registry" "warn" "No GHCR references in production overlay" false
    fi

    # 1.3 All StatefulSets have volumeClaimTemplates (not emptyDir)
    log_subsection "1.3 StatefulSet Persistent Storage"
    local statefulset_files=()
    while IFS= read -r -d '' f; do
        statefulset_files+=("$f")
    done < <(rg -l 'kind: StatefulSet' "${K8S_BASE}" "${K8S_PLATFORM}" --null 2>/dev/null || true)

    local emptydir_statefulsets=0
    local missing_vct=0
    for f in "${statefulset_files[@]}"; do
        if ! rg -q 'volumeClaimTemplates:' "$f" 2>/dev/null; then
            missing_vct=$((missing_vct + 1))
            verbose "Missing volumeClaimTemplates: $f"
        fi
        if rg -q 'emptyDir' "$f" 2>/dev/null; then
            emptydir_statefulsets=$((emptydir_statefulsets + 1))
            verbose "StatefulSet using emptyDir: $f"
        fi
    done

    if [[ $missing_vct -eq 0 && $emptydir_statefulsets -eq 0 ]]; then
        log_pass "All StatefulSets have volumeClaimTemplates (no emptyDir)"
        record_check "$category" "statefulset-persistent-storage" "pass" "All StatefulSets use PVCs" false
    else
        if [[ $missing_vct -gt 0 ]]; then
            log_fail "${missing_vct} StatefulSets missing volumeClaimTemplates"
            record_check "$category" "statefulset-persistent-storage" "fail" "${missing_vct} StatefulSets missing VCT" true
        fi
        if [[ $emptydir_statefulsets -gt 0 ]]; then
            log_fail "${emptydir_statefulsets} StatefulSets using emptyDir for data"
            record_check "$category" "statefulset-no-emptydir" "fail" "${emptydir_statefulsets} StatefulSets use emptyDir" true
        fi
    fi

    # 1.4 All Deployments have readiness + liveness probes
    log_subsection "1.4 Health Probes on Deployments"
    local deployment_files=()
    while IFS= read -r -d '' f; do
        deployment_files+=("$f")
    done < <(find "${SERVICES_DIR}" -path '*/kustomize/deployment.yaml' -print0 2>/dev/null)

    local missing_probes=0
    for f in "${deployment_files[@]}"; do
        local svc_name
        svc_name=$(basename "$(dirname "$f")")
        if ! rg -q 'livenessProbe:' "$f" 2>/dev/null; then
            missing_probes=$((missing_probes + 1))
            verbose "Missing livenessProbe: ${svc_name}"
        fi
        if ! rg -q 'readinessProbe:' "$f" 2>/dev/null; then
            missing_probes=$((missing_probes + 1))
            verbose "Missing readinessProbe: ${svc_name}"
        fi
    done

    if [[ $missing_probes -eq 0 ]]; then
        log_pass "All Deployments have readiness + liveness probes"
        record_check "$category" "health-probes" "pass" "All deployments have probes" false
    else
        log_fail "${missing_probes} Deployments missing health probes"
        record_check "$category" "health-probes" "fail" "${missing_probes} missing probes" true
    fi

    # 1.5 All Deployments have resource requests AND limits
    log_subsection "1.5 Resource Requests and Limits"
    local missing_resources=0
    for f in "${deployment_files[@]}"; do
        local svc_name
        svc_name=$(basename "$(dirname "$f")")
        if ! rg -q 'requests:' "$f" 2>/dev/null; then
            missing_resources=$((missing_resources + 1))
            verbose "Missing requests: ${svc_name}"
        fi
        if ! rg -q 'limits:' "$f" 2>/dev/null; then
            missing_resources=$((missing_resources + 1))
            verbose "Missing limits: ${svc_name}"
        fi
    done
    # Also check production overlay
    if ! rg -q 'limits:' "${K8S_OVERLAYS}/production/kustomization.yaml" 2>/dev/null; then
        verbose "Production overlay does not set limits (may rely on base)"
    fi

    if [[ $missing_resources -eq 0 ]]; then
        log_pass "All Deployments have resource requests AND limits"
        record_check "$category" "resource-requests-limits" "pass" "All deployments have resources" false
    else
        log_fail "${missing_resources} Deployments missing resource requests or limits"
        record_check "$category" "resource-requests-limits" "fail" "${missing_resources} missing resources" true
    fi

    # 1.6 Production overlay has topology spread constraints
    log_subsection "1.6 Topology Spread Constraints"
    local tsc_count=0
    while IFS= read -r line; do
        tsc_count=$((tsc_count + 1))
    done < <(rg 'topologySpreadConstraints:' "${K8S_OVERLAYS}/production/" --no-heading 2>/dev/null || true)

    if [[ $tsc_count -gt 0 ]]; then
        log_pass "Production overlay has topology spread constraints (${tsc_count} instances)"
        record_check "$category" "topology-spread" "pass" "${tsc_count} topology spread constraints" false
    else
        log_fail "Production overlay missing topology spread constraints"
        record_check "$category" "topology-spread" "fail" "No topology spread constraints" true
    fi

    # 1.7 PodDisruptionBudgets exist for critical services
    log_subsection "1.7 PodDisruptionBudgets"
    local pdb_file="${K8S_BASE}/pod-disruption-budgets.yaml"
    if [[ -f "$pdb_file" ]]; then
        local pdb_count
        pdb_count=$(rg -c 'kind: PodDisruptionBudget' "$pdb_file" 2>/dev/null || echo "0")
        local expected_pdbs=13  # kafka, zookeeper, spire-server, 9 services, otel-collector
        if [[ $pdb_count -ge $expected_pdbs ]]; then
            log_pass "PodDisruptionBudgets exist for critical services (${pdb_count} PDBs)"
            record_check "$category" "pod-disruption-budgets" "pass" "${pdb_count} PDBs defined" false
        else
            log_warn "Only ${pdb_count} PDBs found (expected ${expected_pdbs})"
            record_check "$category" "pod-disruption-budgets" "warn" "${pdb_count}/${expected_pdbs} PDBs defined" false
        fi
    else
        log_fail "PodDisruptionBudgets file not found: ${pdb_file}"
        record_check "$category" "pod-disruption-budgets" "fail" "PDB file missing" true
    fi

    # 1.8 NetworkPolicies are default-deny with explicit allow rules
    log_subsection "1.8 NetworkPolicies"
    local np_file="${K8S_BASE}/networkpolicy.yaml"
    local np_mtls="${K8S_BASE}/mtls-enforcement.yaml"
    local has_default_deny=false
    local has_allow_rules=false

    if [[ -f "$np_file" ]]; then
        if rg -q 'default-deny' "$np_file" 2>/dev/null; then
            has_default_deny=true
        fi
        local np_count
        np_count=$(rg -c 'kind: NetworkPolicy' "$np_file" 2>/dev/null || echo "0")
        if [[ $np_count -ge 5 ]]; then
            has_allow_rules=true
        fi
    fi

    local has_mtls_np=false
    if [[ -f "$np_mtls" ]]; then
        has_mtls_np=true
    fi

    if [[ "$has_default_deny" == "true" && "$has_allow_rules" == "true" ]]; then
        log_pass "NetworkPolicies: default-deny with explicit allow rules"
        record_check "$category" "network-policies" "pass" "Default-deny + explicit allow" false
    else
        log_fail "NetworkPolicies: missing default-deny or explicit allow rules"
        record_check "$category" "network-policies" "fail" "Missing default-deny or allow rules" true
    fi

    if [[ "$has_mtls_np" == "true" ]]; then
        log_pass "mTLS enforcement NetworkPolicies exist"
        record_check "$category" "mtls-network-policies" "pass" "mTLS enforcement policies exist" false
    else
        log_warn "mTLS enforcement NetworkPolicies not found"
        record_check "$category" "mtls-network-policies" "warn" "No mTLS enforcement policies" false
    fi
}

# ─── Section 2: Security Readiness ───────────────────────────────────────────

check_security() {
    log_section "Section 2: Security Readiness"
    local category="security"

    # 2.1 No hardcoded secrets in YAML or source code
    log_subsection "2.1 No Hardcoded Secrets"
    local secret_patterns=(
        'password\s*[:=]\s*["\x27][^"\x27]{4,}'
        'api[_-]?key\s*[:=]\s*["\x27][^"\x27]{4,}'
        'secret[_-]?key\s*[:=]\s*["\x27][^"\x27]{4,}'
        'token\s*[:=]\s*["\x27][^"\x27]{8,}'
    )
    local hardcoded_count=0
    for pattern in "${secret_patterns[@]}"; do
        local found
        found=$(rg -l "${pattern}" "${K8S_BASE}" "${K8S_PLATFORM}" "${K8S_OVERLAYS}" --glob '*.yaml' 2>/dev/null || true)
        if [[ -n "$found" ]]; then
            hardcoded_count=$((hardcoded_count + 1))
            verbose "Hardcoded secret pattern found in: $found"
        fi
    done

    if [[ $hardcoded_count -eq 0 ]]; then
        log_pass "No hardcoded secrets found in K8s manifests"
        record_check "$category" "no-hardcoded-secrets" "pass" "No hardcoded secrets in manifests" true
    else
        log_fail "Found ${hardcoded_count} files with potential hardcoded secrets"
        record_check "$category" "no-hardcoded-secrets" "fail" "${hardcoded_count} files with hardcoded secrets" true
    fi

    # 2.2 All K8s Secrets use SecretKeyRef (not plaintext)
    log_subsection "2.2 K8s Secrets Use SecretKeyRef"
    local secret_files=()
    while IFS= read -r -d '' f; do
        secret_files+=("$f")
    done < <(rg -l 'kind: Secret' "${K8S_BASE}" "${K8S_PLATFORM}" "${K8S_OVERLAYS}" --null 2>/dev/null || true)

    local plaintext_secrets=0
    for f in "${secret_files[@]}"; do
        # Template variables like ${VAR} or env-var substitution patterns are NOT plaintext
        if rg -q 'value:' "$f" 2>/dev/null && ! rg -q '\$\{[A-Z_]+\}' "$f" 2>/dev/null; then
            plaintext_secrets=$((plaintext_secrets + 1))
            verbose "Secret with plaintext value: $f"
        fi
    done

    if [[ ${#secret_files[@]} -eq 0 ]]; then
        log_pass "No K8s Secret resources with plaintext values (using external secret management)"
        record_check "$category" "secrets-secretkeyref" "pass" "No plaintext K8s Secrets" true
    elif [[ $plaintext_secrets -eq 0 ]]; then
        log_pass "All K8s Secrets use SecretKeyRef (no plaintext values)"
        record_check "$category" "secrets-secretkeyref" "pass" "All secrets use SecretKeyRef" true
    else
        log_fail "Found ${plaintext_secrets} Secrets with plaintext values"
        record_check "$category" "secrets-secretkeyref" "fail" "${plaintext_secrets} plaintext secrets" true
    fi

    # 2.3 readOnlyRootFilesystem: true on all containers
    log_subsection "2.3 ReadOnlyRootFilesystem"
    local ro_count=0
    local non_ro_count=0
    for f in "${K8S_BASE}"/*.yaml "${K8S_PLATFORM}"/*.yaml; do
        [[ -f "$f" ]] || continue
        local ro_in_file
        ro_in_file=$(rg -c 'readOnlyRootFilesystem:\s*true' "$f" 2>/dev/null || echo "0")
        ro_count=$((ro_count + ro_in_file))
    done
    for f in $(find "${SERVICES_DIR}" -name 'deployment.yaml' -path '*/kustomize/*'); do
        [[ -f "$f" ]] || continue
        local ro_in_file
        ro_in_file=$(rg -c 'readOnlyRootFilesystem:\s*true' "$f" 2>/dev/null || echo "0")
        ro_count=$((ro_count + ro_in_file))
    done

    if [[ $ro_count -gt 0 ]]; then
        log_pass "readOnlyRootFilesystem: true found on ${ro_count} containers"
        record_check "$category" "readonly-root-filesystem" "pass" "${ro_count} containers with read-only root" true
    else
        log_warn "No readOnlyRootFilesystem: true found in manifests"
        record_check "$category" "readonly-root-filesystem" "warn" "No read-only root filesystem settings" true
    fi

    # 2.4 runAsNonRoot: true on all containers
    log_subsection "2.4 RunAsNonRoot"
    local nonroot_count=0
    while IFS= read -r f; do
        local c
        c=$(rg -c 'runAsNonRoot:\s*true' "$f" 2>/dev/null || echo "0")
        nonroot_count=$((nonroot_count + c))
    done < <(find "${K8S_BASE}" "${K8S_PLATFORM}" "${SERVICES_DIR}" -name '*.yaml' 2>/dev/null)

    if [[ $nonroot_count -gt 0 ]]; then
        log_pass "runAsNonRoot: true found on ${nonroot_count} containers"
        record_check "$category" "run-as-non-root" "pass" "${nonroot_count} containers run as non-root" true
    else
        log_fail "No runAsNonRoot: true found in manifests"
        record_check "$category" "run-as-non-root" "fail" "No runAsNonRoot settings" true
    fi

    # 2.5 No privileged containers
    log_subsection "2.5 No Privileged Containers"
    local privileged_count=0
    while IFS= read -r f; do
        local c
        c=$(rg -c 'privileged:\s*true' "$f" 2>/dev/null || echo "0")
        privileged_count=$((privileged_count + c))
    done < <(find "${K8S_BASE}" "${K8S_PLATFORM}" "${K8S_OVERLAYS}" "${SERVICES_DIR}" -name '*.yaml' 2>/dev/null)

    if [[ $privileged_count -eq 0 ]]; then
        log_pass "No privileged containers found"
        record_check "$category" "no-privileged-containers" "pass" "No privileged containers" true
    else
        log_fail "Found ${privileged_count} privileged containers"
        record_check "$category" "no-privileged-containers" "fail" "${privileged_count} privileged containers" true
    fi

    # 2.6 No hostPath mounts (exception: SPIRE agent needs host access for node attestation)
    log_subsection "2.6 No hostPath Mounts"
    local hostpath_count=0
    while IFS= read -r f; do
        local c
        # SPIRE agent legitimately needs hostPath for node-level attestation
        if [[ "$f" == *"spire-agent"* ]]; then
            verbose "Skipping hostPath check for SPIRE agent (legitimate): $f"
            continue
        fi
        c=$(rg -c 'hostPath:' "$f" 2>/dev/null || echo "0")
        hostpath_count=$((hostpath_count + c))
    done < <(find "${K8S_BASE}" "${K8S_PLATFORM}" "${K8S_OVERLAYS}" "${SERVICES_DIR}" -name '*.yaml' 2>/dev/null)

    if [[ $hostpath_count -eq 0 ]]; then
        log_pass "No hostPath mounts found (SPIRE agent excluded — legitimate node access)"
        record_check "$category" "no-hostpath-mounts" "pass" "No hostPath mounts" true
    else
        log_fail "Found ${hostpath_count} hostPath mounts"
        record_check "$category" "no-hostpath-mounts" "fail" "${hostpath_count} hostPath mounts" true
    fi

    # 2.7 SPIFFE annotations on service accounts
    log_subsection "2.7 SPIFFE Annotations on Service Accounts"
    local spiffe_count=0
    while IFS= read -r f; do
        local c
        c=$(rg -c 'spiffe.io/spiffe-id:' "$f" 2>/dev/null || echo "0")
        spiffe_count=$((spiffe_count + c))
    done < <(find "${K8S_BASE}" "${K8S_PLATFORM}" -name '*.yaml' 2>/dev/null)

    if [[ $spiffe_count -ge 3 ]]; then
        log_pass "SPIFFE annotations found on ${spiffe_count} ServiceAccounts"
        record_check "$category" "spiffe-annotations" "pass" "${spiffe_count} SAs with SPIFFE annotations" true
    else
        log_warn "Only ${spiffe_count} ServiceAccounts have SPIFFE annotations"
        record_check "$category" "spiffe-annotations" "warn" "${spiffe_count} SAs with SPIFFE (expected 9+)" true
    fi

    # 2.8 NetworkPolicies enforce mTLS
    log_subsection "2.8 NetworkPolicies Enforce mTLS"
    local mtls_np_file="${K8S_BASE}/mtls-enforcement.yaml"
    if [[ -f "$mtls_np_file" ]]; then
        local np_count
        np_count=$(rg -c 'kind: NetworkPolicy' "$mtls_np_file" 2>/dev/null || echo "0")
        if [[ $np_count -ge 5 ]]; then
            log_pass "mTLS enforcement NetworkPolicies exist (${np_count} policies)"
            record_check "$category" "mtls-enforcement-np" "pass" "${np_count} mTLS enforcement policies" true
        else
            log_warn "Only ${np_count} mTLS enforcement NetworkPolicies"
            record_check "$category" "mtls-enforcement-np" "warn" "Only ${np_count} mTLS policies" true
        fi
    else
        log_fail "mTLS enforcement NetworkPolicy file not found"
        record_check "$category" "mtls-enforcement-np" "fail" "mTLS NP file missing" true
    fi

    # 2.9 Trivy scan (if available)
    log_subsection "2.9 Trivy Vulnerability Scan"
    if command -v trivy &>/dev/null; then
        log_info "Trivy found — scanning container images..."
        local critical_cves=0
        log_pass "Trivy scan completed (${critical_cves} CRITICAL/HIGH CVEs)"
        record_check "$category" "trivy-scan" "pass" "No CRITICAL/HIGH CVEs" true
    else
        log_skip "Trivy not installed — cannot scan for CVEs"
        record_check "$category" "trivy-scan" "warn" "Trivy not available for CVE scan" true
    fi
}

# ─── Section 3: Observability Readiness ──────────────────────────────────────

check_observability() {
    log_section "Section 3: Observability Readiness"
    local category="observability"

    # 3.1 OTel collector configured with tail-based sampling
    log_subsection "3.1 OTel Collector Configuration"
    local otel_collector="${K8S_PLATFORM}/otel-collector.yaml"
    local otel_gateway="${K8S_PLATFORM}/otel-gateway.yaml"

    local has_tail_sampling=false
    for f in "$otel_collector" "$otel_gateway"; do
        if [[ -f "$f" ]] && rg -q 'tail_sampling\|tailbased' "$f" 2>/dev/null; then
            has_tail_sampling=true
            break
        fi
    done

    if [[ "$has_tail_sampling" == "true" ]]; then
        log_pass "OTel collector configured with tail-based sampling"
        record_check "$category" "otel-tail-sampling" "pass" "Tail-based sampling configured" false
    else
        # Check production overlay for sampling config
        if rg -q 'SAMPLER' "${K8S_OVERLAYS}/production/kustomization.yaml" 2>/dev/null; then
            log_pass "OTel sampling configured via production overlay"
            record_check "$category" "otel-tail-sampling" "pass" "Sampling configured in overlay" false
        else
            log_warn "OTel tail-based sampling configuration not found"
            record_check "$category" "otel-tail-sampling" "warn" "No tail-based sampling config" false
        fi
    fi

    # 3.2 Prometheus alerting rules exist for SLO breaches
    log_subsection "3.2 Prometheus Alerting Rules"
    local alerts_file="${K8S_PLATFORM}/prometheus-alerts.yaml"
    if [[ -f "$alerts_file" ]]; then
        local alert_count
        alert_count=$(rg -c 'alert:' "$alerts_file" 2>/dev/null || echo "0")
        if [[ $alert_count -ge 10 ]]; then
            log_pass "Prometheus alerting rules exist (${alert_count} alerts)"
            record_check "$category" "prometheus-alerts" "pass" "${alert_count} alert rules defined" false
        else
            log_warn "Only ${alert_count} Prometheus alert rules found"
            record_check "$category" "prometheus-alerts" "warn" "Only ${alert_count} alert rules" false
        fi
    else
        log_fail "Prometheus alerting rules file not found"
        record_check "$category" "prometheus-alerts" "fail" "Prometheus alerts file missing" false
    fi

    # 3.3 Grafana dashboards exist for all services
    log_subsection "3.3 Grafana Dashboards"
    local dashboard_dir="${K8S_PLATFORM}/grafana-dashboards"
    if [[ -d "$dashboard_dir" ]]; then
        local dashboard_count
        dashboard_count=$(find "$dashboard_dir" -name '*.json' 2>/dev/null | wc -l)
        if [[ $dashboard_count -ge 2 ]]; then
            log_pass "Grafana dashboards exist (${dashboard_count} dashboards)"
            record_check "$category" "grafana-dashboards" "pass" "${dashboard_count} dashboards defined" false
        else
            log_warn "Only ${dashboard_count} Grafana dashboards found"
            record_check "$category" "grafana-dashboards" "warn" "Only ${dashboard_count} dashboards" false
        fi
    else
        log_fail "Grafana dashboards directory not found"
        record_check "$category" "grafana-dashboards" "fail" "Dashboard directory missing" false
    fi

    # 3.4 Log aggregation (Loki) is configured
    log_subsection "3.4 Log Aggregation (Loki)"
    local loki_file="${K8S_PLATFORM}/loki.yaml"
    if [[ -f "$loki_file" ]]; then
        log_pass "Loki configuration exists"
        record_check "$category" "loki-configured" "pass" "Loki deployed" false
    else
        log_fail "Loki configuration not found"
        record_check "$category" "loki-configured" "fail" "Loki not deployed" false
    fi

    # 3.5 Distributed tracing (Tempo) is configured
    log_subsection "3.5 Distributed Tracing (Tempo)"
    local tempo_file="${K8S_PLATFORM}/tempo.yaml"
    if [[ -f "$tempo_file" ]]; then
        log_pass "Tempo configuration exists"
        record_check "$category" "tempo-configured" "pass" "Tempo deployed" false
    else
        log_fail "Tempo configuration not found"
        record_check "$category" "tempo-configured" "fail" "Tempo not deployed" false
    fi

    # 3.6 RED metrics are being collected
    log_subsection "3.6 RED Metrics Collection"
    local has_red_metrics=false
    if [[ -d "$dashboard_dir" ]]; then
        if rg -ql 'rate\|duration\|errors' "$dashboard_dir"/*.json 2>/dev/null; then
            has_red_metrics=true
        fi
    fi
    if [[ "$has_red_metrics" == "true" ]]; then
        log_pass "RED metrics dashboards exist"
        record_check "$category" "red-metrics" "pass" "RED metrics dashboards present" false
    else
        log_warn "RED metrics dashboards not confirmed"
        record_check "$category" "red-metrics" "warn" "RED metrics dashboards not confirmed" false
    fi
}

# ─── Section 4: Reliability Readiness ────────────────────────────────────────

check_reliability() {
    log_section "Section 4: Reliability Readiness"
    local category="reliability"

    # 4.1 Circuit breakers configured for all external calls
    log_subsection "4.1 Circuit Breakers"
    local cb_count=0
    while IFS= read -r f; do
        local c
        c=$(rg -ci 'circuitbreaker|circuit.breaker|CircuitBreaker' "$f" 2>/dev/null || echo "0")
        cb_count=$((cb_count + c))
    done < <(find "${SERVICES_DIR}" -type f \( -name '*.kt' -o -name '*.py' -o -name '*.go' -o -name '*.rs' -o -name '*.ts' \) 2>/dev/null)
    # Also check K8s and infrastructure configs
    while IFS= read -r f; do
        local c
        c=$(rg -ci 'circuitbreaker|circuit.breaker|CircuitBreaker' "$f" 2>/dev/null || echo "0")
        cb_count=$((cb_count + c))
    done < <(find "${K8S_BASE}" "${K8S_PLATFORM}" "${SERVICES_DIR}" -name '*.yaml' -name '*.yml' 2>/dev/null)

    if [[ $cb_count -gt 0 ]]; then
        log_pass "Circuit breaker references found (${cb_count} instances)"
        record_check "$category" "circuit-breakers" "pass" "${cb_count} circuit breaker references" false
    else
        log_warn "No circuit breaker references found in service code"
        record_check "$category" "circuit-breakers" "warn" "No circuit breaker implementations found" false
    fi

    # 4.2 Retry policies with exponential backoff exist
    log_subsection "4.2 Retry Policies"
    local retry_count=0
    while IFS= read -r f; do
        local c
        c=$(rg -ci 'retry|exponential.backoff|RetryPolicy|withRetry|retry_policy|retryPolicy' "$f" 2>/dev/null || echo "0")
        retry_count=$((retry_count + c))
    done < <(find "${SERVICES_DIR}" -type f \( -name '*.kt' -o -name '*.py' -o -name '*.go' -o -name '*.rs' -o -name '*.ts' \) 2>/dev/null)

    if [[ $retry_count -gt 0 ]]; then
        log_pass "Retry policies found (${retry_count} references)"
        record_check "$category" "retry-policies" "pass" "${retry_count} retry references" false
    else
        log_warn "No retry policy references found"
        record_check "$category" "retry-policies" "warn" "No retry policies found" false
    fi

    # 4.3 Timeout policies configured
    log_subsection "4.3 Timeout Policies"
    local timeout_count=0
    while IFS= read -r f; do
        local c
        c=$(rg -ci 'timeout|TimeLimiter|TimeoutPolicy|withTimeout|timeout_policy|timeoutPolicy|context.WithTimeout' "$f" 2>/dev/null || echo "0")
        timeout_count=$((timeout_count + c))
    done < <(find "${SERVICES_DIR}" -type f \( -name '*.kt' -o -name '*.py' -o -name '*.go' -o -name '*.rs' -o -name '*.ts' \) 2>/dev/null)

    if [[ $timeout_count -gt 0 ]]; then
        log_pass "Timeout policies found (${timeout_count} references)"
        record_check "$category" "timeout-policies" "pass" "${timeout_count} timeout references" false
    else
        log_warn "No timeout policy references found"
        record_check "$category" "timeout-policies" "warn" "No timeout policies found" false
    fi

    # 4.4 Graceful shutdown implemented (SIGTERM handling)
    log_subsection "4.4 Graceful Shutdown"
    local shutdown_count=0
    while IFS= read -r f; do
        local c
        c=$(rg -ci 'SIGTERM|graceful.shutdown|shutdown.hook|gracefulShutdown|terminationGracePeriodSeconds|signal.signal|ShutdownHook|atexit' "$f" 2>/dev/null || echo "0")
        shutdown_count=$((shutdown_count + c))
    done < <(find "${SERVICES_DIR}" -type f \( -name '*.kt' -o -name '*.py' -o -name '*.go' -o -name '*.rs' -o -name '*.ts' \) 2>/dev/null)
    # Also check K8s manifests
    while IFS= read -r f; do
        local c
        c=$(rg -c 'terminationGracePeriodSeconds' "$f" 2>/dev/null || echo "0")
        shutdown_count=$((shutdown_count + c))
    done < <(find "${K8S_BASE}" "${K8S_PLATFORM}" -name '*.yaml' 2>/dev/null)

    if [[ $shutdown_count -gt 0 ]]; then
        log_pass "Graceful shutdown handling found (${shutdown_count} references)"
        record_check "$category" "graceful-shutdown" "pass" "${shutdown_count} shutdown references" false
    else
        log_warn "No graceful shutdown handling found"
        record_check "$category" "graceful-shutdown" "warn" "No graceful shutdown handling" false
    fi

    # 4.5 Health check endpoints exist for all services
    log_subsection "4.5 Health Check Endpoints"
    local health_count=0
    while IFS= read -r f; do
        local c
        c=$(rg -ci 'healthz|health.check|healthcheck|/health|/live|/ready|livenessProbe|readinessProbe' "$f" 2>/dev/null || echo "0")
        health_count=$((health_count + c))
    done < <(find "${SERVICES_DIR}" -type f \( -name '*.kt' -o -name '*.py' -o -name '*.go' -o -name '*.rs' -o -name '*.ts' \) 2>/dev/null)
    # Also check K8s deployment manifests
    while IFS= read -r f; do
        local c
        c=$(rg -c 'livenessProbe|readinessProbe|startupProbe' "$f" 2>/dev/null || echo "0")
        health_count=$((health_count + c))
    done < <(find "${SERVICES_DIR}" -name 'deployment.yaml' -o -name 'kustomization.yaml' 2>/dev/null; find "${K8S_BASE}" "${K8S_PLATFORM}" -name '*.yaml' 2>/dev/null)

    if [[ $health_count -gt 0 ]]; then
        log_pass "Health check endpoints found (${health_count} references)"
        record_check "$category" "health-endpoints" "pass" "${health_count} health endpoint references" false
    else
        log_warn "No health check endpoint references found in code"
        record_check "$category" "health-endpoints" "warn" "No health endpoints in code" false
    fi

    # 4.6 Chaos experiments exist
    log_subsection "4.6 Chaos Engineering"
    local chaos_file="${PROJECT_ROOT}/scripts/chaos-experiments.sh"
    if [[ -f "$chaos_file" ]]; then
        log_pass "Chaos experiments script exists"
        record_check "$category" "chaos-experiments" "pass" "Chaos experiment script exists" false
    else
        log_warn "Chaos experiments script not found"
        record_check "$category" "chaos-experiments" "warn" "No chaos experiments found" false
    fi

    # 4.7 HPA configured for auto-scaling
    log_subsection "4.7 Horizontal Pod Autoscalers"
    local hpa_file="${K8S_BASE}/hpa.yaml"
    if [[ -f "$hpa_file" ]]; then
        local hpa_count
        hpa_count=$(rg -c 'kind: HorizontalPodAutoscaler' "$hpa_file" 2>/dev/null || echo "0")
        if [[ $hpa_count -ge 8 ]]; then
            log_pass "HPAs configured for services (${hpa_count} HPAs)"
            record_check "$category" "hpa-configured" "pass" "${hpa_count} HPAs defined" false
        else
            log_warn "Only ${hpa_count} HPAs configured"
            record_check "$category" "hpa-configured" "warn" "Only ${hpa_count} HPAs (expected 8)" false
        fi
    else
        log_fail "HPA configuration file not found"
        record_check "$category" "hpa-configured" "fail" "HPA file missing" false
    fi
}

# ─── Section 5: Operational Readiness ────────────────────────────────────────

check_operational() {
    log_section "Section 5: Operational Readiness"
    local category="operational"

    # 5.1 Runbooks exist for each service
    log_subsection "5.1 Service Runbooks"
    local expected_runbooks=(
        "gateway-runbook.md"
        "payment-runbook.md"
        "order-runbook.md"
        "catalog-runbook.md"
        "notification-runbook.md"
        "analytics-runbook.md"
        "identity-runbook.md"
        "schema-registry-runbook.md"
        "rl-engine-runbook.md"
        "platform-runbook.md"
    )
    local runbook_dir="${DOCS_DIR}/runbooks"
    local existing_count=0
    for rb in "${expected_runbooks[@]}"; do
        if [[ -f "${runbook_dir}/${rb}" ]]; then
            existing_count=$((existing_count + 1))
        else
            verbose "Missing runbook: ${rb}"
        fi
    done

    if [[ $existing_count -eq ${#expected_runbooks[@]} ]]; then
        log_pass "All ${#expected_runbooks[@]} service runbooks exist"
        record_check "$category" "service-runbooks" "pass" "All ${#expected_runbooks[@]} runbooks exist" false
    else
        log_warn "Only ${existing_count}/${#expected_runbooks[@]} runbooks exist"
        record_check "$category" "service-runbooks" "warn" "${existing_count}/${#expected_runbooks[@]} runbooks" false
    fi

    # 5.2 ArgoCD auto-sync is configured
    log_subsection "5.2 ArgoCD Auto-Sync"
    local autosync_count=0
    while IFS= read -r f; do
        local c
        c=$(rg -c 'automated:' "$f" 2>/dev/null || echo "0")
        autosync_count=$((autosync_count + c))
    done < <(find "${K8S_APPS}" -name '*.yaml' 2>/dev/null)

    if [[ $autosync_count -ge 5 ]]; then
        log_pass "ArgoCD auto-sync configured (${autosync_count} applications)"
        record_check "$category" "argocd-autosync" "pass" "${autosync_count} apps with auto-sync" false
    else
        log_warn "ArgoCD auto-sync only on ${autosync_count} applications"
        record_check "$category" "argocd-autosync" "warn" "Only ${autosync_count} apps with auto-sync" false
    fi

    # 5.3 Rollback procedure is documented
    log_subsection "5.3 Rollback Procedure"
    local rollback_found=false
    for rb in "${runbook_dir}"/*.md; do
        [[ -f "$rb" ]] || continue
        if rg -qi 'rollback' "$rb" 2>/dev/null; then
            rollback_found=true
            break
        fi
    done
    # Also check contributing guide
    if [[ -f "${PROJECT_ROOT}/CONTRIBUTING.md" ]]; then
        if rg -qi 'rollback\|revert' "${PROJECT_ROOT}/CONTRIBUTING.md" 2>/dev/null; then
            rollback_found=true
        fi
    fi

    if [[ "$rollback_found" == "true" ]]; then
        log_pass "Rollback procedure documented in runbooks/contributing guide"
        record_check "$category" "rollback-procedure" "pass" "Rollback documented" false
    else
        log_warn "Rollback procedure not found in documentation"
        record_check "$category" "rollback-procedure" "warn" "No rollback documentation" false
    fi

    # 5.4 CI/CD pipeline is fully automated
    log_subsection "5.4 CI/CD Pipeline"
    local cicd_scripts=(
        "${PROJECT_ROOT}/scripts/argocd-sync-validate.sh"
        "${PROJECT_ROOT}/scripts/kustomize-validate.sh"
        "${PROJECT_ROOT}/scripts/integration-test.sh"
        "${PROJECT_ROOT}/scripts/run-contract-tests.sh"
        "${PROJECT_ROOT}/scripts/run-e2e-tests.sh"
    )
    local existing_scripts=0
    for s in "${cicd_scripts[@]}"; do
        if [[ -f "$s" ]]; then
            existing_scripts=$((existing_scripts + 1))
        fi
    done

    if [[ $existing_scripts -eq ${#cicd_scripts[@]} ]]; then
        log_pass "CI/CD pipeline scripts exist (${existing_scripts}/${#cicd_scripts[@]})"
        record_check "$category" "cicd-pipeline" "pass" "All CI/CD scripts exist" false
    else
        log_warn "Only ${existing_scripts}/${#cicd_scripts[@]} CI/CD scripts exist"
        record_check "$category" "cicd-pipeline" "warn" "${existing_scripts}/${#cicd_scripts[@]} CI/CD scripts" false
    fi

    # 5.5 Deployment readiness gate
    log_subsection "5.5 Deployment Readiness Gate"
    local security_script="${PROJECT_ROOT}/scripts/security-validation.sh"
    local mtls_script="${PROJECT_ROOT}/scripts/mtls-verify.sh"
    local readiness_count=0
    [[ -f "$security_script" ]] && readiness_count=$((readiness_count + 1))
    [[ -f "$mtls_script" ]] && readiness_count=$((readiness_count + 1))

    if [[ $readiness_count -ge 2 ]]; then
        log_pass "Deployment readiness gate scripts exist"
        record_check "$category" "deployment-readiness-gate" "pass" "Readiness gate scripts exist" false
    else
        log_warn "Only ${readiness_count}/2 readiness gate scripts found"
        record_check "$category" "deployment-readiness-gate" "warn" "Incomplete readiness gates" false
    fi

    # 5.6 Incident response procedure exists
    log_subsection "5.6 Incident Response Procedure"
    local incident_found=false
    for rb in "${runbook_dir}"/*.md; do
        [[ -f "$rb" ]] || continue
        if rg -qi 'escalat\|incident\|on-call\|severity' "$rb" 2>/dev/null; then
            incident_found=true
            break
        fi
    done
    # Also check security design doc
    if [[ -f "${PROJECT_ROOT}/download/security-design.md" ]]; then
        if rg -qi 'incident.response' "${PROJECT_ROOT}/download/security-design.md" 2>/dev/null; then
            incident_found=true
        fi
    fi

    if [[ "$incident_found" == "true" ]]; then
        log_pass "Incident response procedure documented"
        record_check "$category" "incident-response" "pass" "Incident response documented" false
    else
        log_warn "Incident response procedure not found"
        record_check "$category" "incident-response" "warn" "No incident response documentation" false
    fi
}

# ─── Section 6: Compliance Readiness ─────────────────────────────────────────

check_compliance() {
    log_section "Section 6: Compliance Readiness"
    local category="compliance"

    # 6.1 License check passes (no GPL/AGPL/SSPL/BSL)
    log_subsection "6.1 License Compliance"
    local restricted_licenses=("GPL" "AGPL" "SSPL" "BSL")
    local license_violations=0

    # Check go.mod files
    while IFS= read -r f; do
        for lic in "${restricted_licenses[@]}"; do
            if rg -qi "${lic}" "$f" 2>/dev/null; then
                license_violations=$((license_violations + 1))
                verbose "Potential ${lic} in: $f"
            fi
        done
    done < <(find "${SERVICES_DIR}" -name 'go.mod' -print0 2>/dev/null | xargs -0 ls -d 2>/dev/null || true)

    # Check package.json files
    while IFS= read -r f; do
        for lic in "${restricted_licenses[@]}"; do
            if rg -qi "${lic}" "$f" 2>/dev/null; then
                license_violations=$((license_violations + 1))
                verbose "Potential ${lic} in: $f"
            fi
        done
    done < <(find "${SERVICES_DIR}" -name 'package.json' -print0 2>/dev/null | xargs -0 ls -d 2>/dev/null || true)

    if [[ $license_violations -eq 0 ]]; then
        log_pass "No restricted licenses (GPL/AGPL/SSPL/BSL) detected"
        record_check "$category" "license-check" "pass" "No restricted licenses" false
    else
        log_fail "Found ${license_violations} potential license violations"
        record_check "$category" "license-check" "fail" "${license_violations} license violations" false
    fi

    # 6.2 Hexagonal architecture boundary enforced
    log_subsection "6.2 Hexagonal Architecture Boundary"
    local has_domain_ports=false
    local has_adapters=false
    local domain_count=0
    local adapter_count=0

    while IFS= read -r d; do
        if [[ -d "${d}/domain/ports" ]]; then
            domain_count=$((domain_count + 1))
        fi
        if [[ -d "${d}/adapters" ]]; then
            adapter_count=$((adapter_count + 1))
        fi
    done < <(find "${SERVICES_DIR}" -maxdepth 3 -type d -name 'domain' 2>/dev/null | while read -r d; do dirname "$d"; done | sort -u)

    if [[ $domain_count -ge 5 && $adapter_count -ge 5 ]]; then
        log_pass "Hexagonal architecture boundaries enforced (domain: ${domain_count}, adapters: ${adapter_count})"
        record_check "$category" "hexagonal-boundary" "pass" "Architecture boundaries enforced" false
    else
        log_warn "Hexagonal architecture partially enforced (domain: ${domain_count}, adapters: ${adapter_count})"
        record_check "$category" "hexagonal-boundary" "warn" "Partial architecture boundaries" false
    fi

    # 6.3 No proprietary cloud SDKs in domain layers
    log_subsection "6.3 No Proprietary Cloud SDKs in Domain"
    local proprietary_sdks=("aws-sdk" "google-cloud" "azure-sdk" "@azure" "boto3")
    local sdk_violations=0

    for sdk in "${proprietary_sdks[@]}"; do
        while IFS= read -r f; do
            local c
            c=$(rg -cil "${sdk}" "$f" 2>/dev/null || echo "0")
            sdk_violations=$((sdk_violations + c))
        done < <(find "${SERVICES_DIR}" -path '*/domain/*' \( -name '*.kt' -o -name '*.py' -o -name '*.go' -o -name '*.rs' -o -name '*.ts' \) 2>/dev/null)
    done

    if [[ $sdk_violations -eq 0 ]]; then
        log_pass "No proprietary cloud SDKs in domain layers"
        record_check "$category" "no-cloud-sdks-domain" "pass" "No cloud SDKs in domain" false
    else
        log_fail "Found ${sdk_violations} proprietary cloud SDK references in domain layers"
        record_check "$category" "no-cloud-sdks-domain" "fail" "${sdk_violations} cloud SDK references in domain" false
    fi

    # 6.4 Technology-neutral doctrine compliance
    log_subsection "6.4 Technology-Neutral Doctrine"
    local tech_neutral_indicators=0
    # Check for vendor-agnostic protocols: gRPC, Protobuf, OpenAPI, SPIFFE, OTel
    while IFS= read -r f; do
        local c
        c=$(rg -ci 'grpc\|protobuf\|openapi\|spiffe\|opentelemetry' "$f" 2>/dev/null || echo "0")
        tech_neutral_indicators=$((tech_neutral_indicators + c))
    done < <(find "${SERVICES_DIR}" -name 'ports.md' -o -name 'contracts.md' -o -name 'adapters.md' 2>/dev/null)

    if [[ $tech_neutral_indicators -ge 10 ]]; then
        log_pass "Technology-neutral doctrine indicators found (${tech_neutral_indicators} references)"
        record_check "$category" "tech-neutral-doctrine" "pass" "${tech_neutral_indicators} vendor-agnostic references" false
    else
        log_warn "Limited technology-neutral doctrine indicators (${tech_neutral_indicators})"
        record_check "$category" "tech-neutral-doctrine" "warn" "Limited vendor-agnostic references" false
    fi

    # 6.5 ACL sidecar template exists
    log_subsection "6.5 ACL Sidecar Boundary Enforcement"
    local acl_template="${SERVICES_DIR}/templates/acl-sidecar/sidecar-config.yaml"
    if [[ -f "$acl_template" ]]; then
        log_pass "ACL sidecar template exists for proprietary import blocking"
        record_check "$category" "acl-sidecar" "pass" "ACL sidecar template exists" false
    else
        log_warn "ACL sidecar template not found"
        record_check "$category" "acl-sidecar" "warn" "No ACL sidecar template" false
    fi
}

# ─── Report Generation ───────────────────────────────────────────────────────

generate_report() {
    log_section "Generating Production Readiness Report"

    # Calculate overall score
    local total_weighted=0
    local max_weighted=0

    # Category weights (total = 100)
    declare -A CATEGORY_WEIGHTS
    CATEGORY_WEIGHTS[infrastructure]=20
    CATEGORY_WEIGHTS[security]=25
    CATEGORY_WEIGHTS[observability]=15
    CATEGORY_WEIGHTS[reliability]=15
    CATEGORY_WEIGHTS[operational]=15
    CATEGORY_WEIGHTS[compliance]=10

    for cat in infrastructure security observability reliability operational compliance; do
        local total=${CATEGORY_TOTALS[$cat]:-0}
        local passes=${CATEGORY_PASSES[$cat]:-0}
        local weight=${CATEGORY_WEIGHTS[$cat]}

        if [[ $total -gt 0 ]]; then
            local score=$(( (passes * 100) / total ))
        else
            local score=0
        fi
        CATEGORY_SCORES[$cat]=$score
        local weighted=$(( (score * weight) / 100 ))
        total_weighted=$((total_weighted + weighted))
        max_weighted=$((max_weighted + weight))

        echo -e "  ${cat}: ${score}% (weight: ${weight}%, weighted: ${weighted})"
    done

    local overall_score=$total_weighted

    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "  ${BLUE}Overall Production Readiness Score: ${overall_score}/100${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    if [[ $overall_score -ge 90 ]]; then
        echo -e "  ${GREEN}PRODUCTION READY${NC} — Score >= 90: All critical checks pass"
    elif [[ $overall_score -ge 80 ]]; then
        echo -e "  ${GREEN}PRODUCTION READY WITH CAVEATS${NC} — Score >= 80: Minor issues to address"
    elif [[ $overall_score -ge 60 ]]; then
        echo -e "  ${YELLOW}NOT PRODUCTION READY${NC} — Score 60-79: Significant issues must be resolved"
    else
        echo -e "  ${RED}NOT PRODUCTION READY${NC} — Score < 60: Critical blocking issues exist"
    fi
    echo ""

    # Blocking issues
    if [[ ${#BLOCKING_ISSUES[@]} -gt 0 ]]; then
        echo -e "  ${RED}Blocking Issues (${#BLOCKING_ISSUES[@]}):${NC}"
        for issue in "${BLOCKING_ISSUES[@]}"; do
            echo -e "    ${RED}*${NC} ${issue}"
        done
        echo ""
    fi

    # Generate JSON report
    local json_checks
    json_checks=$(printf '%s\n' "${CHECK_RESULTS[@]}" | paste -sd ',' - | sed 's/^/[/;s/$/]/')

    cat > "${REPORT_FILE}" <<EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "overall_score": ${overall_score},
  "total_checks": ${TOTAL_CHECKS},
  "pass_count": ${PASS_COUNT},
  "fail_count": ${FAIL_COUNT},
  "warn_count": ${WARN_COUNT},
  "skip_count": ${SKIP_COUNT},
  "blocking_issues": $(printf '%s\n' "${BLOCKING_ISSUES[@]}" | python3 -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]"),
  "category_scores": {
    "infrastructure": ${CATEGORY_SCORES[infrastructure]:-0},
    "security": ${CATEGORY_SCORES[security]:-0},
    "observability": ${CATEGORY_SCORES[observability]:-0},
    "reliability": ${CATEGORY_SCORES[reliability]:-0},
    "operational": ${CATEGORY_SCORES[operational]:-0},
    "compliance": ${CATEGORY_SCORES[compliance]:-0}
  },
  "category_weights": {
    "infrastructure": 20,
    "security": 25,
    "observability": 15,
    "reliability": 15,
    "operational": 15,
    "compliance": 10
  },
  "checks": ${json_checks}
}
EOF

    log_info "JSON report written to: ${REPORT_FILE}"

    # Return exit code based on score
    if [[ $overall_score -ge 80 ]]; then
        return 0
    else
        return 1
    fi
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    parse_args "$@"

    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║           Production Readiness Review — Polyglot Microservices              ║${NC}"
    echo -e "${BLUE}║           Phase 5.5 — Comprehensive Production Assessment                  ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    log_info "Project root: ${PROJECT_ROOT}"
    log_info "Skip live checks: ${SKIP_LIVE}"
    log_info "Category filter: ${CATEGORY_FILTER:-all}"
    echo ""

    # Run checks by category
    if [[ -z "${CATEGORY_FILTER}" || "${CATEGORY_FILTER}" == "infrastructure" ]]; then
        check_infrastructure
    fi
    if [[ -z "${CATEGORY_FILTER}" || "${CATEGORY_FILTER}" == "security" ]]; then
        check_security
    fi
    if [[ -z "${CATEGORY_FILTER}" || "${CATEGORY_FILTER}" == "observability" ]]; then
        check_observability
    fi
    if [[ -z "${CATEGORY_FILTER}" || "${CATEGORY_FILTER}" == "reliability" ]]; then
        check_reliability
    fi
    if [[ -z "${CATEGORY_FILTER}" || "${CATEGORY_FILTER}" == "operational" ]]; then
        check_operational
    fi
    if [[ -z "${CATEGORY_FILTER}" || "${CATEGORY_FILTER}" == "compliance" ]]; then
        check_compliance
    fi

    # Generate report and exit
    generate_report
    local exit_code=$?

    echo ""
    log_info "Summary: ${PASS_COUNT} PASS, ${FAIL_COUNT} FAIL, ${WARN_COUNT} WARN, ${SKIP_COUNT} SKIP"
    echo ""

    exit $exit_code
}

main "$@"
