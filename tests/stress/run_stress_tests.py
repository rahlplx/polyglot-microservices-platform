"""
TIER 3 Stress Test Runner
=========================
Runs all stress test suites and records results for the RL feedback loop.

Usage:
  python -m pytest tests/stress/ -v --tb=short -x --json-report --json-report-file=tests/stress/results.json
  python run_stress_tests.py                    # Run all and record to RL feedback loop
  python run_stress_tests.py --category datetime # Run only datetime stress tests
  python run_stress_tests.py --promote           # Run + promote passing findings
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RL_ENGINE = PROJECT_ROOT / ".claude" / "engine" / "rl-feedback-loop.py"

# Mapping: test file → findings it validates
TEST_FINDING_MAP = {
    "tests/stress/tz_datetime/test_datetime_timezone_stress.py": [
        "V-1", "V-2", "V-3", "G9",
    ],
    "tests/stress/money/test_money_value_stress.py": [
        "G1", "G3", "G12",
    ],
    "tests/stress/security/test_credentials_security_stress.py": [
        "G14", "G15", "G5", "G8", "G2",
    ],
    "tests/stress/infra/test_infra_config_stress.py": [
        "G16", "G6", "G4", "G7", "G10", "G17", "G18", "G2",
    ],
    "tests/stress/config/test_config_correctness_stress.py": [
        "G11", "G13", "G12", "V-1", "V-2", "V-3", "V-4", "V-5", "V-6", "V-7",
    ],
}


def run_stress_tests(category: str | None = None) -> dict:
    """Run stress tests and return results."""
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tier": 3,
        "categories": {},
        "findings": {},
        "summary": {
            "total_tests": 0,
            "passed": 0,
            "failed": 0,
            "errors": 0,
        },
    }

    for test_file, findings in TEST_FINDING_MAP.items():
        if category and category not in test_file:
            continue

        test_path = PROJECT_ROOT / test_file
        if not test_path.exists():
            print(f"  SKIP: {test_file} (not found)")
            for fid in findings:
                results["findings"][fid] = {
                    "status": "skipped",
                    "reason": f"Test file not found: {test_file}",
                    "tier": 0,
                }
            continue

        print(f"\n  Running: {test_file}")
        start = time.time()

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_path), "-v", "--tb=short", "-x"],
                capture_output=True, text=True, timeout=120,
                cwd=str(PROJECT_ROOT),
            )
            elapsed = time.time() - start
            exit_code = proc.returncode
            output = proc.stdout + proc.stderr

            # Parse pytest output for pass/fail counts
            passed = output.count(" PASSED")
            failed = output.count(" FAILED")
            errors = output.count(" ERROR")

            results["summary"]["total_tests"] += passed + failed + errors
            results["summary"]["passed"] += passed
            results["summary"]["failed"] += failed
            results["summary"]["errors"] += errors

            # Record result for each finding
            all_passed = exit_code == 0
            for fid in findings:
                results["findings"][fid] = {
                    "status": "pass" if all_passed else "fail",
                    "tier": 3 if all_passed else 0,
                    "test_file": test_file,
                    "passed_tests": passed,
                    "failed_tests": failed,
                    "error_tests": errors,
                    "elapsed_seconds": round(elapsed, 2),
                    "exit_code": exit_code,
                }

            status_icon = "✓" if all_passed else "✗"
            print(f"    {status_icon} {passed} passed, {failed} failed, {errors} errors ({elapsed:.1f}s)")

        except subprocess.TimeoutExpired:
            elapsed = time.time() - start
            for fid in findings:
                results["findings"][fid] = {
                    "status": "timeout",
                    "tier": 0,
                    "test_file": test_file,
                    "elapsed_seconds": round(elapsed, 2),
                }
            print(f"    TIMEOUT after {elapsed:.1f}s")

        except Exception as e:
            for fid in findings:
                results["findings"][fid] = {
                    "status": "error",
                    "tier": 0,
                    "test_file": test_file,
                    "error": str(e),
                }
            print(f"    ERROR: {e}")

    return results


def record_results_to_rl(results: dict) -> None:
    """Record stress test results to the RL feedback loop."""
    for fid, result in results["findings"].items():
        if result["status"] == "pass":
            tier = 3
            record = "pass"
        else:
            tier = 0
            record = "fail"

        evidence = (
            f"Stress test: {result.get('test_file', 'unknown')} — "
            f"passed={result.get('passed_tests', 0)}, "
            f"failed={result.get('failed_tests', 0)}, "
            f"errors={result.get('error_tests', 0)}, "
            f"elapsed={result.get('elapsed_seconds', 0)}s"
        )

        try:
            subprocess.run(
                [
                    sys.executable, str(RL_ENGINE), "verify",
                    # We use the Python API directly instead
                ],
                capture_output=True, text=True, timeout=10,
                cwd=str(PROJECT_ROOT),
            )
        except Exception:
            pass

        # Use the Python API directly
        sys.path.insert(0, str(PROJECT_ROOT / ".claude" / "engine"))
        # Import inline to avoid module name issues
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "rl_feedback_loop", str(RL_ENGINE)
        )
        rl = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rl)

        rl.verify_finding(
            finding_id=fid,
            tier=tier,
            result=record,
            evidence=evidence,
            tester="stress-test-runner",
        )


def promote_passing_findings() -> int:
    """Promote all TIER 3 passing findings to the knowledge base."""
    sys.path.insert(0, str(PROJECT_ROOT / ".claude" / "engine"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "rl_feedback_loop", str(RL_ENGINE)
    )
    rl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rl)

    promoted = 0
    findings_dir = PROJECT_ROOT / ".claude" / "engine" / "feedback" / "findings"
    for fpath in findings_dir.glob("*.json"):
        with open(fpath) as f:
            finding = json.load(f)
        if finding.get("verification_tier", 0) >= 3 and finding.get("status") == "stress_tested":
            result = rl.promote_to_knowledge(finding["finding_id"])
            if result:
                promoted += 1
                print(f"  Promoted: {finding['finding_id']} → KN-{finding['finding_id']}")

    return promoted


def main():
    category = None
    do_promote = False

    for arg in sys.argv[1:]:
        if arg.startswith("--category="):
            category = arg.split("=")[1]
        elif arg == "--category" and sys.argv.index(arg) + 1 < len(sys.argv):
            category = sys.argv[sys.argv.index(arg) + 1]
        elif arg == "--promote":
            do_promote = True

    print("=" * 60)
    print("  TIER 3 STRESS TEST RUNNER")
    print("  RL Feedback Loop — Stress-Test-Gated Knowledge Base")
    print("=" * 60)
    if category:
        print(f"  Category filter: {category}")
    print()

    # Run stress tests
    results = run_stress_tests(category)

    # Print summary
    print("\n" + "=" * 60)
    print("  STRESS TEST SUMMARY")
    print("=" * 60)
    print(f"  Total tests: {results['summary']['total_tests']}")
    print(f"  Passed:      {results['summary']['passed']}")
    print(f"  Failed:      {results['summary']['failed']}")
    print(f"  Errors:      {results['summary']['errors']}")

    passing_findings = [f for f, r in results["findings"].items() if r["status"] == "pass"]
    failing_findings = [f for f, r in results["findings"].items() if r["status"] != "pass"]

    print(f"\n  Findings passing TIER 3: {len(passing_findings)}")
    for fid in passing_findings:
        print(f"    ✓ {fid}")

    if failing_findings:
        print(f"\n  Findings NOT passing TIER 3: {len(failing_findings)}")
        for fid in failing_findings:
            r = results["findings"][fid]
            print(f"    ✗ {fid}: {r['status']}")

    # Record results
    print("\n  Recording results to RL feedback loop...")
    record_results_to_rl(results)

    # Promote if requested
    if do_promote:
        print("\n  Promoting TIER 3 passing findings to knowledge base...")
        count = promote_passing_findings()
        print(f"  Promoted {count} findings to knowledge base.")

    # Save results
    results_path = PROJECT_ROOT / "tests" / "stress" / "stress_test_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to: {results_path}")

    return 0 if results["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
