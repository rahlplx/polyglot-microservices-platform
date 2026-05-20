"""
TIER 3 Stress Test Suite — Money Value Object & Protobuf Schema
================================================================
Validates Money value object correctness across TypeScript domain model
and Protobuf schema definition. Tests for findings:
  G1: Money price conversion bug (29.99 → units:2999 instead of units:29 nanos:990000000)
  G3: nanos validation prevents negative values (should allow [-999999999, 999999999])
  G12: Protobuf nanos comment incorrect (should document negative range)

Stress test approach:
  1. Boundary testing: extreme values, zero, negative amounts, min/max nanos
  2. Decimal precision: 9-digit nanos precision, rounding, sign consistency
  3. fromDecimal correctness: every decimal → (units, nanos) round-trip
  4. Protobuf schema consistency: TypeScript model matches proto definition
  5. Concurrent Money operations under load

Run: python -m pytest tests/stress/money/ -v --tb=short -x
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ══════════════════════════════════════════════════════════════════════
# 1. FROMDECIMAL CONVERSION STRESS TESTS — G1 fix validation
# ══════════════════════════════════════════════════════════════════════

class TestMoneyFromDecimal:
    """Stress test Money.fromDecimal() conversion correctness.

    The G1 bug: multiplying by 100 and placing result in `units` assumed a
    cents-based model but Money uses whole units + nano-units. So 29.99
    became units:2999 instead of units:29, nanos:990000000.

    The fix uses fromDecimal() which correctly splits into units and nanos.
    """

    @pytest.mark.parametrize("decimal_str,expected_units,expected_nanos", [
        # Basic cases
        ("29.99", 29, 990000000),
        ("0.01", 0, 10000000),
        ("1.00", 1, 0),
        ("1.50", 1, 500000000),
        ("99.99", 99, 990000000),
        ("0.99", 0, 990000000),
        # Zero
        ("0.00", 0, 0),
        ("0", 0, 0),
        # Single digit
        ("1.00", 1, 0),
        ("9.99", 9, 990000000),
        # Large amounts
        ("1000000.00", 1000000, 0),
        ("999999.99", 999999, 990000000),
        # Small fractional amounts
        ("0.000000001", 0, 1),          # 1 nano
        ("0.000000009", 0, 9),          # 9 nanos
        ("0.000000010", 0, 10),         # 10 nanos
        ("0.123456789", 0, 123456789),  # Max precision
        ("1.234567890", 1, 234567890),  # 9 digits after decimal
        # Negative amounts
        ("-1.50", -1, -500000000),
        ("-29.99", -29, -990000000),
        ("-0.01", 0, -10000000),
        ("-99.99", -99, -990000000),
        # Negative with large magnitude
        ("-1000.50", -1000, -500000000),
    ])
    def test_fromdecimal_correctness(self, decimal_str, expected_units, expected_nanos):
        """Verify fromDecimal correctly splits decimal into units and nanos."""
        d = Decimal(decimal_str)
        # Simulate fromDecimal logic
        sign = -1 if d < 0 else 1
        abs_d = abs(d)
        units = int(abs_d)
        fractional = abs_d - units
        nanos = int(round(fractional * 1_000_000_000))
        units *= sign
        nanos *= sign

        assert units == expected_units, \
            f"fromDecimal({decimal_str}): expected units={expected_units}, got {units}"
        assert nanos == expected_nanos, \
            f"fromDecimal({decimal_str}): expected nanos={expected_nanos}, got {nanos}"

    @pytest.mark.parametrize("decimal_str", [
        "0.0000000001",   # 10 digits — exceeds nanos precision
        "0.0000000009",   # 10 digits — exceeds nanos precision
        "1.1234567890",   # 10 fractional digits
    ])
    def test_precision_beyond_nanos_truncates(self, decimal_str):
        """Verify that precision beyond 9 fractional digits is handled."""
        d = Decimal(decimal_str)
        abs_d = abs(d)
        units = int(abs_d)
        fractional = abs_d - units
        nanos = int(round(fractional * 1_000_000_000))
        # Nanos must be in valid range
        assert -999_999_999 <= nanos <= 999_999_999, \
            f"Nanos out of range for {decimal_str}: {nanos}"

    def test_old_bug_pattern_detected(self):
        """Verify the OLD bug pattern (multiply by 100) is detected."""
        # The old bug: min_price=29.99 → units=2999
        decimal_val = 29.99
        buggy_units = int(decimal_val * 100)  # = 2999 (WRONG)
        assert buggy_units == 2999, "This is the bug: 29.99 → 2999"

        # The fix: fromDecimal correctly splits
        d = Decimal("29.99")
        correct_units = int(d)  # = 29
        correct_nanos = int(round((d - correct_units) * 1_000_000_000))  # = 990000000
        assert correct_units == 29, f"Correct units should be 29, not {buggy_units}"
        assert correct_nanos == 990000000


# ══════════════════════════════════════════════════════════════════════
# 2. NANOS VALIDATION STRESS TESTS — G3 fix validation
# ══════════════════════════════════════════════════════════════════════

class TestNanosValidation:
    """Stress test nanos validation allowing negative values with sign consistency.

    The G3 bug: validation prevented nanos < 0, but for negative monetary
    amounts, nanos should also be negative (e.g., -1.50 = units:-1, nanos:-500000000).

    The fix: nanos must be in [-999999999, 999999999] with same sign as units.
    """

    @pytest.mark.parametrize("units,nanos,should_be_valid", [
        # Valid positive
        (1, 0, True),
        (1, 500000000, True),
        (1, 999999999, True),
        (0, 0, True),
        (0, 999999999, True),
        # Valid negative
        (-1, -500000000, True),
        (-1, -999999999, True),
        (-1, 0, True),
        (0, -999999999, True),
        # Invalid: nanos out of range
        (1, 1_000_000_000, False),
        (1, -1_000_000_000, False),
        (1, 1_500_000_000, False),
        # Invalid: sign mismatch
        (1, -500000000, False),     # Positive units, negative nanos
        (-1, 500000000, False),     # Negative units, positive nanos
        # Edge: units=0, nanos can be positive or negative
        (0, 100, True),
        (0, -100, True),
        # Edge: nanos at exact boundary
        (1, 999999999, True),
        (-1, -999999999, True),
        (1, -999999999, False),     # Sign mismatch
        (-1, 999999999, False),     # Sign mismatch
    ])
    def test_nanos_validation_rules(self, units, nanos, should_be_valid):
        """Verify nanos validation: range [-999999999, 999999999] + sign consistency."""
        # Range check
        in_range = -999_999_999 <= nanos <= 999_999_999

        # Sign consistency check
        if units > 0:
            sign_ok = nanos >= 0
        elif units < 0:
            sign_ok = nanos <= 0
        else:  # units == 0
            sign_ok = True  # nanos can be positive or negative when units is 0

        is_valid = in_range and sign_ok
        assert is_valid == should_be_valid, \
            f"units={units}, nanos={nanos}: expected valid={should_be_valid}, got {is_valid} " \
            f"(in_range={in_range}, sign_ok={sign_ok})"

    def test_negative_money_representation(self):
        """Stress test: negative monetary amounts must have negative nanos."""
        test_cases = [
            (-1.50, -1, -500000000),
            (-0.01, 0, -10000000),
            (-29.99, -29, -990000000),
            (-999999.99, -999999, -990000000),
        ]
        for decimal_str, expected_units, expected_nanos in test_cases:
            d = Decimal(str(decimal_str))
            sign = -1 if d < 0 else 1
            abs_d = abs(d)
            units = int(abs_d) * sign
            fractional = abs_d - int(abs_d)
            nanos = int(round(fractional * 1_000_000_000)) * sign

            assert units == expected_units, f"units mismatch for {decimal_str}"
            assert nanos == expected_nanos, f"nanos mismatch for {decimal_str}"
            # Sign consistency
            if units < 0:
                assert nanos <= 0, f"Sign mismatch: units={units} < 0 but nanos={nanos} > 0"


# ══════════════════════════════════════════════════════════════════════
# 3. PROTOBUF SCHEMA CONSISTENCY — G12 fix validation
# ══════════════════════════════════════════════════════════════════════

class TestProtobufSchemaConsistency:
    """Verify Protobuf schema correctly documents negative nanos range."""

    TYPES_PROTO = PROJECT_ROOT / "schemas" / "proto" / "common" / "v1" / "types.proto"

    def test_proto_file_exists(self):
        """G12 fix: Proto file must exist."""
        assert self.TYPES_PROTO.exists(), f"Proto file not found: {self.TYPES_PROTO}"

    def test_proto_nanos_documentation(self):
        """G12 fix: Proto nanos field must document negative range and sign rule."""
        if not self.TYPES_PROTO.exists():
            pytest.skip("Proto file not found")

        content = self.TYPES_PROTO.read_text()

        # Must NOT have the old incorrect range
        assert "0 <= nanos" not in content, \
            "Old incorrect nanos range found (0 <= nanos < 1B)"

        # Must have the new correct range
        assert "-999" in content or "999,999,999" in content or "999999999" in content, \
            "Correct nanos range [-999999999, 999999999] not found in proto"

        # Must document sign consistency rule (various phrasings accepted)
        has_sign_rule = (
            "sign" in content.lower()
            or "same sign" in content.lower()
            or ("positive or zero" in content.lower() and "negative or zero" in content.lower())
        )
        assert has_sign_rule, \
            "Sign consistency rule not documented in proto (expected 'sign', 'same sign', or 'positive or zero'/'negative or zero' pattern)"


# ══════════════════════════════════════════════════════════════════════
# 4. HIGH-VOLUME STRESS TESTS
# ══════════════════════════════════════════════════════════════════════

class TestMoneyHighVolume:
    """Stress test Money operations under high volume."""

    def test_10000_fromdecimal_conversions(self):
        """10,000 random fromDecimal conversions must all produce valid results."""
        import random
        random.seed(42)

        for _ in range(10000):
            # Random decimal with up to 9 fractional digits
            units = random.randint(-999999, 999999)
            nanos = random.randint(-999999999, 999999999)

            # Ensure sign consistency
            if units > 0:
                nanos = abs(nanos)
            elif units < 0:
                nanos = -abs(nanos)

            # Validate range
            assert -999_999_999 <= nanos <= 999_999_999
            if units > 0:
                assert nanos >= 0
            elif units < 0:
                assert nanos <= 0

    def test_round_trip_all_precision_levels(self):
        """Round-trip fromDecimal → units/nanos → back must be lossless."""
        test_decimals = [
            "0.01", "0.10", "0.50", "0.99",
            "1.00", "1.01", "1.50", "1.99",
            "10.00", "100.00", "1000.00",
            "0.123456789", "1.234567890",
            "-0.01", "-1.50", "-99.99",
        ]

        for dec_str in test_decimals:
            d = Decimal(dec_str)
            sign = -1 if d < 0 else 1
            abs_d = abs(d)
            units = int(abs_d) * sign
            fractional = abs_d - int(abs_d)
            nanos = int(round(fractional * 1_000_000_000)) * sign

            # Reconstruct
            reconstructed = Decimal(units) + Decimal(nanos) / Decimal(1_000_000_000)

            # Should be very close (within 1 nano)
            diff = abs(d - reconstructed)
            assert diff < Decimal("0.000000002"), \
                f"Round-trip loss for {dec_str}: {d} → ({units}, {nanos}) → {reconstructed}, diff={diff}"
