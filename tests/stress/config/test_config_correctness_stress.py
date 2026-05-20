"""
TIER 3 Stress Test Suite — Configuration Correctness
=====================================================
Validates code-level configuration patterns for correctness.
Tests for findings:
  G11: Docstring says nearest-rank but code uses linear interpolation
  G13: protoPath identical in all env branches (dead conditional)

Stress test approach:
  1. Docstring-implementation consistency
  2. Dead code detection
  3. Configuration deduplication

Run: python -m pytest tests/stress/config/ -v --tb=short -x
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ══════════════════════════════════════════════════════════════════════
# 1. DOCSTRING-IMPLEMENTATION CONSISTENCY — G11 fix validation
# ══════════════════════════════════════════════════════════════════════

class TestDocstringImplementationConsistency:
    """Stress test docstrings match their implementations."""

    AGGREGATION_SERVICE = (
        PROJECT_ROOT / "services" / "analytics" / "src" /
        "domain" / "services" / "aggregation_service.py"
    )

    def test_percentile_docstring_matches_implementation(self):
        """G11 fix: _percentile docstring must correctly describe the interpolation method."""
        if not self.AGGREGATION_SERVICE.exists():
            pytest.skip("aggregation_service.py not found")

        content = self.AGGREGATION_SERVICE.read_text()

        # Must mention linear interpolation as the primary method
        assert 'linear interpolation' in content.lower(), \
            "_percentile docstring must describe linear interpolation method"

        # If nearest-rank is mentioned, it must be in a comparative context
        # (e.g., "more accurate than the nearest-rank method" is acceptable)
        # NOT as the claimed method of the function itself
        lines = content.split('\n')
        for i, line in enumerate(lines):
            stripped = line.strip()
            if 'nearest-rank' in stripped.lower() and stripped.startswith('"""'):
                # In a docstring — check it's a comparison, not a claim
                assert 'than the nearest-rank' in stripped.lower() or 'than nearest-rank' in stripped.lower() or 'more accurate' in stripped.lower(), \
                    f"Line {i+1}: nearest-rank mentioned without comparison context: {stripped}"


# ══════════════════════════════════════════════════════════════════════
# 2. DEAD CODE DETECTION — G13 fix validation
# ══════════════════════════════════════════════════════════════════════

class TestDeadCodeDetection:
    """Stress test for dead conditional branches with identical outcomes."""

    CONTAINER_FILE = (
        PROJECT_ROOT / "services" / "catalog" / "src" /
        "infrastructure" / "di" / "container.ts"
    )

    def test_no_identical_conditional_branches(self):
        """G13 fix: No conditional branches where all paths produce the same value."""
        if not self.CONTAINER_FILE.exists():
            pytest.skip("container.ts not found")

        content = self.CONTAINER_FILE.read_text()

        # The old bug: protoPath was assigned the same value in all branches
        # The fix: simplified to a single assignment

        # Look for protoPath assignment
        proto_path_matches = re.findall(r'protoPath\s*[=:]\s*[\'"]([^\'"]+)[\'"]', content)

        if len(proto_path_matches) > 1:
            # If there are multiple assignments, they should have different values
            unique_values = set(proto_path_matches)
            assert len(unique_values) > 1 or len(proto_path_matches) == 1, \
                f"G13: protoPath has {len(proto_path_matches)} assignments with same value: {proto_path_matches}"


# ══════════════════════════════════════════════════════════════════════
# 3. PROTO SCHEMA VALIDATION — G12 fix validation
# ══════════════════════════════════════════════════════════════════════

class TestProtoSchemaValidation:
    """Stress test protobuf schema documentation correctness."""

    TYPES_PROTO = PROJECT_ROOT / "schemas" / "proto" / "common" / "v1" / "types.proto"

    def test_money_nanos_documentation_correct(self):
        """G12 fix: Money.nanos must document negative range and sign consistency."""
        if not self.TYPES_PROTO.exists():
            pytest.skip("types.proto not found")

        content = self.TYPES_PROTO.read_text()

        # Must document the full range
        has_negative_range = '-999' in content or '-999,999,999' in content or '-999999999' in content
        assert has_negative_range, \
            "Money.nanos must document the negative range [-999999999, 999999999]"

        # Must document sign consistency (various phrasings accepted)
        has_sign_rule = (
            'sign' in content.lower()
            or 'same sign' in content.lower()
            or ('positive or zero' in content.lower() and 'negative or zero' in content.lower())
        )
        assert has_sign_rule, \
            "Money.nanos must document sign consistency rule with units"

        # Must NOT have the old incorrect range
        has_old_range = '0 <= nanos' in content
        assert not has_old_range, \
            "Old incorrect nanos range (0 <= nanos < 1B) still present"


# ══════════════════════════════════════════════════════════════════════
# 4. CROSS-SERVICE CONFIGURATION CONSISTENCY
# ══════════════════════════════════════════════════════════════════════

class TestCrossServiceConfigConsistency:
    """Stress test configuration consistency across services."""

    def test_all_go_services_use_utc_timestamps(self):
        """V-4/V-5/V-6/V-7 fix: All Go services must use time.Now().UTC()."""
        go_service_dirs = [
            PROJECT_ROOT / "services" / "payment" / "src",
            PROJECT_ROOT / "services" / "gateway" / "src",
            PROJECT_ROOT / "services" / "schema-registry" / "src",
        ]

        violations = []
        for svc_dir in go_service_dirs:
            if not svc_dir.exists():
                continue
            for go_file in svc_dir.rglob("*.go"):
                content = go_file.read_text()
                lines = content.split('\n')
                for i, line in enumerate(lines, 1):
                    # Look for time.Now() without .UTC()
                    if 'time.Now()' in line and '.UTC()' not in line:
                        # Skip if it's in a comment
                        stripped = line.strip()
                        if stripped.startswith('//') or stripped.startswith('/*'):
                            continue
                        violations.append(
                            f"{go_file.relative_to(PROJECT_ROOT)}:{i}: {stripped}"
                        )

        assert len(violations) == 0, \
            f"time.Now() without .UTC() found in Go services: {violations[:10]}"

    def test_all_python_services_use_timezone_aware_datetime(self):
        """V-1/V-2/V-3 fix: No datetime.utcnow() in Python services."""
        python_dirs = [
            PROJECT_ROOT / "services" / "notification" / "src",
            PROJECT_ROOT / "services" / "analytics" / "src",
            PROJECT_ROOT / "services" / "rl-engine" / "src",
        ]

        violations = []
        for d in python_dirs:
            if not d.exists():
                continue
            for py_file in d.rglob("*.py"):
                content = py_file.read_text()
                if 'datetime.utcnow()' in content:
                    violations.append(str(py_file.relative_to(PROJECT_ROOT)))

        assert len(violations) == 0, \
            f"datetime.utcnow() still found in: {violations}"
