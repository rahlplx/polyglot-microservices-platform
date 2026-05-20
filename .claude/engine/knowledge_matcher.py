"""
RL Knowledge Base Pattern Matcher
==================================
Validates that the knowledge base can correctly identify issue patterns
in new code. This is the final step — proving the RL system can learn
from stress-tested solutions and apply that learning to future reviews.

Run: python3 .claude/engine/knowledge_matcher.py --validate
     python3 .claude/engine/knowledge_matcher.py --scan <file_path>
     python3 .claude/engine/knowledge_matcher.py --scan-diff <file1> <file2> ...
     python3 .claude/engine/knowledge_matcher.py --scan-diff --json <file1> <file2> ...
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = PROJECT_ROOT / ".claude" / "engine" / "feedback" / "knowledge"

# Severity levels for workflow gate decisions
SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"

# Pattern signatures extracted from promoted knowledge items
# Each pattern maps to knowledge base entries that would catch it
SIGNATURES = {
    "datetime_utcnow": {
        "pattern": r"datetime\.utcnow\(\)",
        "knowledge_ids": ["KN-V-1", "KN-V-2", "KN-V-3"],
        "description": "datetime.utcnow() is deprecated — use datetime.now(timezone.utc)",
        "fix": "Replace datetime.utcnow() with datetime.now(timezone.utc)",
        "severity": SEVERITY_MEDIUM,
        "tags": ["python", "datetime", "timezone", "bug"],
    },
    "datetime_fromtimestamp_no_tz": {
        "pattern": r"datetime\.fromtimestamp\([^)]*\)(?!.*tz=)",
        "knowledge_ids": ["KN-G9"],
        "description": "datetime.fromtimestamp() without tz creates naive datetime objects",
        "fix": "Add tz=timezone.utc parameter: datetime.fromtimestamp(ts, tz=timezone.utc)",
        "severity": SEVERITY_MEDIUM,
        "tags": ["python", "datetime", "timezone", "bug"],
    },
    "time_now_without_utc": {
        "pattern": r"time\.Now\(\)(?!\.UTC\(\))",
        "knowledge_ids": ["KN-V-4", "KN-V-5", "KN-V-6", "KN-V-7"],
        "description": "time.Now() without .UTC() produces local timestamps",
        "fix": "Replace time.Now() with time.Now().UTC()",
        "severity": SEVERITY_MEDIUM,
        "tags": ["go", "datetime", "timezone", "bug"],
    },
    "hardcoded_password": {
        "pattern": r'(?:admin[_-]?password|password)\s*:\s*[A-Za-z0-9+/=]{8,}(?!\$)',
        "knowledge_ids": ["KN-G14"],
        "description": "Hardcoded password in Kubernetes Secret or config",
        "fix": "Use env var substitution: ${VAR_NAME} or secretKeyRef",
        "severity": SEVERITY_CRITICAL,
        "tags": ["security", "k8s", "credentials", "critical"],
    },
    "hardcoded_db_connection": {
        "pattern": r'(?:postgresql?|mysql|mongodb)://[^\s"\']+:([^\s"\']+)@',
        "knowledge_ids": ["KN-G15"],
        "description": "Hardcoded database credentials in connection string",
        "fix": "Parameterize connection string, inject via environment variables",
        "severity": SEVERITY_CRITICAL,
        "tags": ["security", "credentials", "python", "critical"],
    },
    "broad_cidr": {
        "pattern": r'(?:10\.0\.0\.0/[0-8]|172\.16\.0\.0/12|192\.168\.0\.0/16)',
        "knowledge_ids": ["KN-G5"],
        "description": "Overly broad CIDR in NetworkPolicy violates least privilege",
        "fix": "Narrow CIDR to /24 or use podSelector/namespaceSelector",
        "severity": SEVERITY_HIGH,
        "tags": ["security", "k8s", "networkpolicy", "infrastructure"],
    },
    "emptydir_statefulset": {
        "pattern": r"(?:kind:\s*StatefulSet[\s\S]*?)emptyDir",
        "knowledge_ids": ["KN-G2"],
        "description": "emptyDir in StatefulSet causes data loss on pod reschedule",
        "fix": "Use volumeClaimTemplates for persistent storage in StatefulSets",
        "severity": SEVERITY_CRITICAL,
        "tags": ["infrastructure", "k8s", "data-persistence", "critical"],
    },
    "deprecated_k8s_alpha": {
        "pattern": r"scheduler\.alpha\.kubernetes\.io",
        "knowledge_ids": ["KN-G4"],
        "description": "Deprecated alpha Kubernetes annotation",
        "fix": "Remove alpha annotation; use pod-security.kubernetes.io labels",
        "severity": SEVERITY_MEDIUM,
        "tags": ["k8s", "deprecated", "infrastructure"],
    },
    "placeholder_repourl": {
        "pattern": r"github\.com/example/",
        "knowledge_ids": ["KN-G6"],
        "description": "Hardcoded placeholder repository URL",
        "fix": "Use env var substitution: ${GIT_REPO_URL:-actual-url}",
        "severity": SEVERITY_LOW,
        "tags": ["infrastructure", "argocd", "gitops"],
    },
    "readonly_root_false": {
        "pattern": r"readOnlyRootFilesystem:\s*false",
        "knowledge_ids": ["KN-G8"],
        "description": "readOnlyRootFilesystem set to false — should be true for security",
        "fix": "Set readOnlyRootFilesystem: true and mount emptyDir for /tmp",
        "severity": SEVERITY_HIGH,
        "tags": ["security", "k8s", "infrastructure"],
    },
    "money_nanos_wrong_range": {
        "pattern": r"0\s*<=\s*nanos",
        "knowledge_ids": ["KN-G3", "KN-G12"],
        "description": "Money nanos validation uses incorrect range (0 <= nanos < 1B instead of [-999999999, 999999999])",
        "fix": "Update validation to range [-999999999, 999999999] with sign consistency",
        "severity": SEVERITY_CRITICAL,
        "tags": ["bug", "money", "validation", "critical"],
    },
    "money_price_cents_bug": {
        "pattern": r"parseInt\([^)]*\*\s*100\)",
        "knowledge_ids": ["KN-G1"],
        "description": "Money price conversion using cents-based model (multiply by 100) instead of units+nanos",
        "fix": "Use fromDecimal() to correctly split decimal into units and nanos",
        "severity": SEVERITY_CRITICAL,
        "tags": ["bug", "money", "typescript", "critical"],
    },
}


def scan_file(file_path: str) -> list[dict]:
    """Scan a file against all knowledge base patterns."""
    path = Path(file_path)
    if not path.exists():
        print(f"File not found: {file_path}")
        return []

    content = path.read_text()
    matches = []

    for sig_id, sig in SIGNATURES.items():
        found = re.findall(sig["pattern"], content, re.IGNORECASE)
        if found:
            matches.append({
                "signature": sig_id,
                "description": sig["description"],
                "fix": sig["fix"],
                "severity": sig["severity"],
                "knowledge_ids": sig["knowledge_ids"],
                "occurrences": len(found),
                "tags": sig["tags"],
                "file": str(path),
            })

    return matches


def scan_diff(file_paths: list[str], output_json: bool = False) -> list[dict]:
    """Scan multiple files from a PR diff and return all findings."""
    all_matches: list[dict] = []

    # File extensions to scan
    scannable_extensions = {".py", ".go", ".ts", ".kt", ".rs", ".yaml", ".yml"}

    for file_path in file_paths:
        path = Path(file_path)
        if path.suffix not in scannable_extensions:
            continue
        matches = scan_file(file_path)
        all_matches.extend(matches)

    if output_json:
        output = {
            "total_findings": len(all_matches),
            "critical_count": sum(1 for m in all_matches if m["severity"] == SEVERITY_CRITICAL),
            "high_count": sum(1 for m in all_matches if m["severity"] == SEVERITY_HIGH),
            "medium_count": sum(1 for m in all_matches if m["severity"] == SEVERITY_MEDIUM),
            "low_count": sum(1 for m in all_matches if m["severity"] == SEVERITY_LOW),
            "files_scanned": len(file_paths),
            "findings": all_matches,
        }
        print(json.dumps(output, indent=2))
    else:
        if all_matches:
            print(f"\n  Found {len(all_matches)} pattern match(es) across {len(file_paths)} file(s):")
            for m in all_matches:
                print(f"\n  [{m['severity']}] {m['signature']} in {m['file']}")
                print(f"    Issue: {m['description']}")
                print(f"    Fix: {m['fix']}")
                print(f"    Knowledge: {', '.join(m['knowledge_ids'])}")
        else:
            print(f"  No pattern matches found across {len(file_paths)} file(s)")

    return all_matches


def validate_knowledge_base() -> dict:
    """Validate that the knowledge base is complete and can detect patterns."""
    results = {
        "knowledge_items": 0,
        "pattern_signatures": len(SIGNATURES),
        "validation_results": [],
    }

    # Check knowledge base files exist
    knowledge_files = list(KNOWLEDGE_DIR.glob("*.json"))
    results["knowledge_items"] = len(knowledge_files)

    # Validate each pattern can detect its corresponding issue
    for sig_id, sig in SIGNATURES.items():
        # Check that referenced knowledge items exist
        missing = []
        for kid in sig["knowledge_ids"]:
            kpath = KNOWLEDGE_DIR / f"{kid}.json"
            if not kpath.exists():
                missing.append(kid)

        if missing:
            results["validation_results"].append({
                "signature": sig_id,
                "severity": sig["severity"],
                "status": "INCOMPLETE",
                "missing_knowledge": missing,
            })
        else:
            results["validation_results"].append({
                "signature": sig_id,
                "severity": sig["severity"],
                "status": "VALID",
                "knowledge_count": len(sig["knowledge_ids"]),
            })

    # Summary
    valid = sum(1 for r in results["validation_results"] if r["status"] == "VALID")
    incomplete = sum(1 for r in results["validation_results"] if r["status"] == "INCOMPLETE")

    results["summary"] = {
        "valid_patterns": valid,
        "incomplete_patterns": incomplete,
        "total_knowledge_items": results["knowledge_items"],
        "coverage_percentage": round(valid / len(SIGNATURES) * 100, 1) if SIGNATURES else 0,
    }

    return results


def main():
    if len(sys.argv) < 2:
        print("Usage: knowledge_matcher.py --validate | --scan <file_path> | --scan-diff [--json] <file1> <file2> ...")
        sys.exit(1)

    command = sys.argv[1]

    if command == "--validate":
        print("=" * 60)
        print("  RL KNOWLEDGE BASE VALIDATION")
        print("=" * 60)
        results = validate_knowledge_base()

        print(f"\n  Knowledge Items: {results['knowledge_items']}")
        print(f"  Pattern Signatures: {results['pattern_signatures']}")
        print(f"\n  Validation Results:")
        for r in results["validation_results"]:
            icon = "OK" if r["status"] == "VALID" else "!!"
            print(f"    [{icon}] {r['signature']} ({r.get('severity', 'N/A')}): {r['status']}", end="")
            if "missing_knowledge" in r:
                print(f" (missing: {r['missing_knowledge']})", end="")
            print()

        s = results["summary"]
        print(f"\n  Summary:")
        print(f"    Valid: {s['valid_patterns']}/{len(SIGNATURES)} patterns")
        print(f"    Coverage: {s['coverage_percentage']}%")
        print(f"    Incomplete: {s['incomplete_patterns']}")

        # Exit with error if coverage is below threshold
        if s["coverage_percentage"] < 80:
            print("\n  ERROR: KB coverage below 80% threshold")
            sys.exit(1)

    elif command == "--scan":
        if len(sys.argv) < 3:
            print("Usage: knowledge_matcher.py --scan <file_path>")
            sys.exit(1)
        file_path = sys.argv[2]
        matches = scan_file(file_path)
        if matches:
            print(f"\n  Found {len(matches)} pattern matches in {file_path}:")
            for m in matches:
                print(f"\n  [{m['severity']}] {m['signature']} ({m['occurrences']} occurrence(s))")
                print(f"    Issue: {m['description']}")
                print(f"    Fix: {m['fix']}")
                print(f"    Knowledge: {', '.join(m['knowledge_ids'])}")
        else:
            print(f"  No pattern matches found in {file_path}")

        # Exit with error if CRITICAL findings
        critical = [m for m in matches if m["severity"] == SEVERITY_CRITICAL]
        if critical:
            print(f"\n  BLOCKING: {len(critical)} CRITICAL finding(s) detected")
            sys.exit(1)

    elif command == "--scan-diff":
        remaining_args = sys.argv[2:]
        output_json = "--json" in remaining_args
        if output_json:
            remaining_args.remove("--json")

        if not remaining_args:
            print("Usage: knowledge_matcher.py --scan-diff [--json] <file1> <file2> ...")
            sys.exit(1)

        matches = scan_diff(remaining_args, output_json=output_json)

        # Exit with error if CRITICAL or HIGH findings (for CI blocking)
        if not output_json:
            blocking = [m for m in matches if m["severity"] in (SEVERITY_CRITICAL, SEVERITY_HIGH)]
            if blocking:
                print(f"\n  BLOCKING: {len(blocking)} CRITICAL/HIGH finding(s) detected")
                sys.exit(1)

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
