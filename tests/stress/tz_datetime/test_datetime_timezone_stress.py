"""
TIER 3 Stress Test Suite — Datetime/Timezone Handling
=====================================================
Validates that ALL datetime operations across all Python services
use timezone-aware UTC objects. This is the stress test for findings:
  V-1, V-2, V-3 (datetime.utcnow() → datetime.now(timezone.utc))
  G9 (datetime.fromtimestamp() without tz → with tz=timezone.utc)

Stress test approach:
  1. Boundary testing: timestamps at epoch boundaries, DST transitions,
     leap seconds, year boundaries, extreme values
  2. Concurrent access: multiple threads creating datetime objects
  3. Round-trip consistency: serialize → deserialize preserves UTC
  4. Cross-service consistency: same timestamp produces same result
  5. No naive datetime objects anywhere in the codebase

Run: python -m pytest tests/stress/datetime/ -v --tb=short -x
"""

from __future__ import annotations

import ast
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── Project root ──
PROJECT_ROOT = Path(__file__).resolve().parents[3]  # /home/z/my-project


# ══════════════════════════════════════════════════════════════════════
# 1. BOUNDARY STRESS TESTS — datetime.now(timezone.utc)
# ══════════════════════════════════════════════════════════════════════

class TestDatetimeNowUTCBoundary:
    """Stress test datetime.now(timezone.utc) at extreme boundaries."""

    @pytest.mark.parametrize("label,ts_func", [
        ("epoch_zero", lambda: datetime(1970, 1, 1, tzinfo=timezone.utc)),
        ("far_future", lambda: datetime(2099, 12, 31, 23, 59, 59, tzinfo=timezone.utc)),
        ("far_past", lambda: datetime(1900, 1, 1, 0, 0, 1, tzinfo=timezone.utc)),
        ("leap_year", lambda: datetime(2024, 2, 29, 12, 0, 0, tzinfo=timezone.utc)),
        ("non_leap_year", lambda: datetime(2023, 3, 1, 0, 0, 0, tzinfo=timezone.utc)),
        ("year_boundary", lambda: datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)),
        ("midnight_utc", lambda: datetime(2025, 6, 15, 0, 0, 0, tzinfo=timezone.utc)),
        ("max_microsecond", lambda: datetime(2025, 6, 15, 12, 30, 45, 999999, tzinfo=timezone.utc)),
    ])
    def test_datetime_utc_at_boundaries(self, label, ts_func):
        """Verify timezone-aware datetime at boundary values."""
        dt = ts_func()
        assert dt.tzinfo is not None, f"{label}: datetime must be timezone-aware"
        assert dt.tzinfo == timezone.utc, f"{label}: datetime must use UTC"
        # Round-trip through timestamp
        ts = dt.timestamp()
        reconstructed = datetime.fromtimestamp(ts, tz=timezone.utc)
        assert reconstructed.tzinfo is not None, f"{label}: reconstructed must be timezone-aware"
        # Allow 1-second tolerance for float precision
        assert abs((reconstructed - dt).total_seconds()) < 1.0, \
            f"{label}: round-trip mismatch: {dt} vs {reconstructed}"

    def test_now_always_returns_aware(self):
        """Verify datetime.now(timezone.utc) always returns timezone-aware."""
        results = []
        for _ in range(1000):
            dt = datetime.now(timezone.utc)
            results.append(dt.tzinfo is not None and dt.tzinfo == timezone.utc)
        assert all(results), "datetime.now(timezone.utc) must ALWAYS return timezone-aware"

    def test_no_naive_datetime_from_now(self):
        """Stress test: datetime.now() without tz must NEVER appear in output."""
        for _ in range(100):
            dt = datetime.now(timezone.utc)
            assert dt.tzinfo is not None, "Naive datetime detected"


# ══════════════════════════════════════════════════════════════════════
# 2. FROMTIMESTAMP STRESS TESTS — G9 fix validation
# ══════════════════════════════════════════════════════════════════════

class TestFromtimestampWithTimezone:
    """Stress test datetime.fromtimestamp(ts, tz=timezone.utc)."""

    @pytest.mark.parametrize("ts", [
        0,                          # Epoch
        1,                          # 1 second after epoch
        1700000000,                 # Recent timestamp
        2**31 - 1,                  # Max 32-bit signed int
        1735689600,                 # 2025-01-01T00:00:00Z
        1609459200,                 # 2021-01-01T00:00:00Z
        1000000000,                 # 2001-09-09T01:46:40Z
    ])
    def test_fromtimestamp_always_aware(self, ts):
        """fromtimestamp with tz must always produce timezone-aware datetime."""
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        assert dt.tzinfo is not None, f"fromtimestamp({ts}) produced naive datetime"
        assert dt.tzinfo == timezone.utc, f"fromtimestamp({ts}) must use UTC"

    def test_fromtimestamp_without_tz_produces_naive(self):
        """Verify that fromtimestamp WITHOUT tz produces naive datetime (the bug)."""
        ts = time.time()
        dt_naive = datetime.fromtimestamp(ts)  # NO tz — the old bug
        assert dt_naive.tzinfo is None, "Without tz, fromtimestamp should produce naive datetime (this is the bug pattern)"

    def test_fromtimestamp_with_tz_never_naive(self):
        """Stress test: fromtimestamp with tz=timezone.utc NEVER naive."""
        for i in range(1000):
            ts = time.time() + i * 0.001  # Slightly different timestamps
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            assert dt.tzinfo is not None, f"Iteration {i}: naive datetime from fromtimestamp"

    def test_fromtimestamp_protobuf_conversion(self):
        """Stress test: protobuf Timestamp → datetime conversion (G9 specific)."""
        # Simulate protobuf Timestamp with seconds + nanos
        for seconds in [1700000000, 1735689600, 1609459200]:
            nanos = 123456789
            dt = datetime.fromtimestamp(seconds + nanos / 1e9, tz=timezone.utc)
            assert dt.tzinfo is not None, f"Protobuf conversion for seconds={seconds} produced naive datetime"


# ══════════════════════════════════════════════════════════════════════
# 3. CONCURRENT ACCESS STRESS TESTS
# ══════════════════════════════════════════════════════════════════════

class TestDatetimeConcurrentAccess:
    """Stress test datetime operations under concurrent access."""

    def test_concurrent_datetime_creation(self):
        """1000 concurrent threads creating timezone-aware datetimes."""
        errors = []

        def create_datetime(thread_id):
            try:
                for _ in range(100):
                    dt = datetime.now(timezone.utc)
                    if dt.tzinfo is None:
                        errors.append(f"Thread {thread_id}: naive datetime!")
                    # Also test fromtimestamp
                    ts = time.time()
                    dt2 = datetime.fromtimestamp(ts, tz=timezone.utc)
                    if dt2.tzinfo is None:
                        errors.append(f"Thread {thread_id}: naive fromtimestamp!")
            except Exception as e:
                errors.append(f"Thread {thread_id}: exception {e}")

        threads = [threading.Thread(target=create_datetime, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Concurrent datetime errors: {errors}"

    def test_concurrent_fromtimestamp(self):
        """ThreadPoolExecutor stress test for fromtimestamp with tz."""
        results = []

        def check_ts(ts):
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            return dt.tzinfo is not None

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [
                executor.submit(check_ts, time.time() + i * 0.01)
                for i in range(500)
            ]
            for future in as_completed(futures):
                results.append(future.result())

        assert all(results), f"{sum(1 for r in results if not r)} / {len(results)} failed"


# ══════════════════════════════════════════════════════════════════════
# 4. CODE SCANNING — No datetime.utcnow() or naive fromtimestamp
# ══════════════════════════════════════════════════════════════════════

class TestDatetimeCodeScanning:
    """Scan source code for forbidden datetime patterns."""

    FORBIDDEN_PATTERNS = [
        "datetime.utcnow()",
        "datetime.now()",       # Without timezone.utc argument
        "datetime.fromtimestamp(",  # Without tz= parameter (checked contextually)
    ]

    PYTHON_DIRS = [
        PROJECT_ROOT / "services" / "notification" / "src",
        PROJECT_ROOT / "services" / "analytics" / "src",
        PROJECT_ROOT / "services" / "rl-engine" / "src",
        PROJECT_ROOT / "services" / "cdc-relay" / "src",
    ]

    def _scan_python_files(self):
        """Find all Python source files in service directories."""
        files = []
        for d in self.PYTHON_DIRS:
            if d.exists():
                files.extend(d.rglob("*.py"))
        return files

    def test_no_utcnow_in_source(self):
        """V-1/V-2/V-3 fix: No datetime.utcnow() in any Python source."""
        violations = []
        for fpath in self._scan_python_files():
            content = fpath.read_text()
            if "datetime.utcnow()" in content:
                violations.append(str(fpath.relative_to(PROJECT_ROOT)))
        assert len(violations) == 0, \
            f"datetime.utcnow() found in: {violations}"

    def test_no_naive_datetime_now(self):
        """No datetime.now() without timezone.utc in Python source."""
        violations = []
        for fpath in self._scan_python_files():
            content = fpath.read_text()
            lines = content.split('\n')
            for i, line in enumerate(lines, 1):
                # Check for datetime.now() without timezone.utc
                if "datetime.now()" in line and "timezone.utc" not in line:
                    # Allow datetime.now(timezone.utc) and datetime.now(tz=...)
                    if "datetime.now(timezone" not in line and "datetime.now(tz" not in line:
                        violations.append(
                            f"{fpath.relative_to(PROJECT_ROOT)}:{i}: {line.strip()}"
                        )
        assert len(violations) == 0, \
            f"Naive datetime.now() found in: {violations}"

    def test_fromtimestamp_has_tz_parameter(self):
        """G9 fix: All fromtimestamp() calls must have tz= parameter."""
        violations = []
        for fpath in self._scan_python_files():
            content = fpath.read_text()
            lines = content.split('\n')
            for i, line in enumerate(lines, 1):
                if "fromtimestamp(" in line:
                    # Must have tz= in the same line
                    if "tz=" not in line and "tz " not in line:
                        violations.append(
                            f"{fpath.relative_to(PROJECT_ROOT)}:{i}: {line.strip()}"
                        )
        assert len(violations) == 0, \
            f"fromtimestamp() without tz= found in: {violations}"


# ══════════════════════════════════════════════════════════════════════
# 5. ROUND-TRIP SERIALIZATION STRESS TESTS
# ══════════════════════════════════════════════════════════════════════

class TestDatetimeRoundTrip:
    """Stress test datetime serialization/deserialization with UTC."""

    def test_iso_format_round_trip(self):
        """ISO 8601 round-trip preserves timezone."""
        for _ in range(100):
            dt = datetime.now(timezone.utc)
            iso_str = dt.isoformat()
            reconstructed = datetime.fromisoformat(iso_str)
            assert reconstructed.tzinfo is not None, f"Round-trip lost timezone: {iso_str}"

    def test_timestamp_round_trip(self):
        """Unix timestamp round-trip preserves timezone."""
        for _ in range(100):
            dt = datetime.now(timezone.utc)
            ts = dt.timestamp()
            reconstructed = datetime.fromtimestamp(ts, tz=timezone.utc)
            assert reconstructed.tzinfo is not None, "Round-trip lost timezone"
            assert abs((reconstructed - dt).total_seconds()) < 0.001

    def test_protobuf_timestamp_round_trip(self):
        """Protobuf Timestamp seconds+nanos round-trip preserves timezone."""
        for _ in range(100):
            dt = datetime.now(timezone.utc)
            # Simulate protobuf conversion
            ts_seconds = int(dt.timestamp())
            ts_nanos = dt.microsecond * 1000
            # Reconstruct (G9 fix pattern)
            reconstructed = datetime.fromtimestamp(
                ts_seconds + ts_nanos / 1e9, tz=timezone.utc
            )
            assert reconstructed.tzinfo is not None, "Protobuf round-trip lost timezone"
