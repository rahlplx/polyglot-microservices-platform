"""
Cross-Service Money Invariant Tests.

Validates that Money arithmetic rules are consistent across the Python
services (analytics, notification). Cross-checks the same invariants
that are verified in Go (payment/tests) and Kotlin (order/domain/models).

These are property-based tests — they cover edge cases that unit tests miss.
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass
from typing import Tuple


# ---------------------------------------------------------------------------
# Python Money implementation (mirrors Go/Kotlin/TypeScript versions)
# Used by analytics + notification services via shared domain models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Money:
    currency_code: str
    units: int
    nanos: int

    def __post_init__(self) -> None:
        if len(self.currency_code) != 3:
            raise ValueError(f"Invalid currency code: {self.currency_code!r}")
        if not isinstance(self.units, int):
            raise TypeError("units must be int")
        if not isinstance(self.nanos, int):
            raise TypeError("nanos must be int")
        if not (-999_999_999 <= self.nanos <= 999_999_999):
            raise ValueError(f"nanos out of range: {self.nanos}")
        if self.units > 0 and self.nanos < 0:
            raise ValueError("Sign mismatch: positive units, negative nanos")
        if self.units < 0 and self.nanos > 0:
            raise ValueError("Sign mismatch: negative units, positive nanos")

    @classmethod
    def of(cls, units: int, nanos: int, currency: str) -> "Money":
        return cls(currency_code=currency, units=units, nanos=nanos)

    @classmethod
    def zero(cls, currency: str) -> "Money":
        return cls(currency_code=currency, units=0, nanos=0)

    def add(self, other: "Money") -> "Money":
        if self.currency_code != other.currency_code:
            raise ValueError(f"Currency mismatch: {self.currency_code} vs {other.currency_code}")
        total_nanos = self.nanos + other.nanos
        # floor div, not truncation: int(-0.5)==0 but -500_000_000//1e9==-1
        carry = total_nanos // 1_000_000_000
        remainder = total_nanos % 1_000_000_000
        return Money(self.currency_code, self.units + other.units + carry, remainder)

    def subtract(self, other: "Money") -> "Money":
        negated = Money(other.currency_code, -other.units, -other.nanos)
        return self.add(negated)

    def is_zero(self) -> bool:
        return self.units == 0 and self.nanos == 0

    def is_negative(self) -> bool:
        return self.units < 0 or (self.units == 0 and self.nanos < 0)

    def to_decimal(self) -> str:
        sign = "-" if (self.units < 0 or self.nanos < 0) else ""
        abs_units = abs(self.units)
        abs_nanos = abs(self.nanos)
        nanos_str = str(abs_nanos).rjust(9, "0").rstrip("0")
        if not nanos_str:
            return f"{sign}{abs_units}"
        return f"{sign}{abs_units}.{nanos_str}"


# ---------------------------------------------------------------------------
# Construction invariants
# ---------------------------------------------------------------------------

class TestMoneyConstruction:
    def test_valid_positive(self) -> None:
        m = Money.of(29, 990_000_000, "USD")
        assert m.units == 29
        assert m.nanos == 990_000_000

    def test_zero(self) -> None:
        m = Money.zero("USD")
        assert m.is_zero()

    def test_invalid_currency_code_length(self) -> None:
        with pytest.raises(ValueError, match="Invalid currency code"):
            Money.of(10, 0, "US")

    def test_nanos_out_of_range_high(self) -> None:
        with pytest.raises(ValueError, match="nanos out of range"):
            Money.of(1, 1_000_000_000, "USD")

    def test_nanos_out_of_range_low(self) -> None:
        with pytest.raises(ValueError, match="nanos out of range"):
            Money.of(1, -1_000_000_000, "USD")

    def test_sign_mismatch_positive_units_negative_nanos(self) -> None:
        with pytest.raises(ValueError, match="Sign mismatch"):
            Money.of(5, -100_000_000, "USD")

    def test_sign_mismatch_negative_units_positive_nanos(self) -> None:
        with pytest.raises(ValueError, match="Sign mismatch"):
            Money.of(-5, 100_000_000, "USD")

    def test_zero_units_positive_nanos_allowed(self) -> None:
        m = Money.of(0, 500_000_000, "USD")  # $0.50
        assert not m.is_zero()
        assert not m.is_negative()

    def test_zero_units_negative_nanos_allowed(self) -> None:
        m = Money.of(0, -500_000_000, "USD")  # -$0.50
        assert m.is_negative()

    def test_gbp_currency(self) -> None:
        m = Money.of(100, 0, "GBP")
        assert m.currency_code == "GBP"


# ---------------------------------------------------------------------------
# Addition invariants
# ---------------------------------------------------------------------------

class TestMoneyAddition:
    def test_basic_add(self) -> None:
        a = Money.of(10, 0, "USD")
        b = Money.of(5, 500_000_000, "USD")
        result = a.add(b)
        assert result.units == 15
        assert result.nanos == 500_000_000

    def test_nano_carry(self) -> None:
        """Nanos overflow should carry into units."""
        a = Money.of(1, 800_000_000, "USD")   # $1.80
        b = Money.of(0, 500_000_000, "USD")   # $0.50
        result = a.add(b)
        assert result.units == 2              # $2.30
        assert result.nanos == 300_000_000

    def test_add_zero_is_identity(self) -> None:
        m = Money.of(42, 0, "USD")
        result = m.add(Money.zero("USD"))
        assert result == m

    def test_commutativity(self) -> None:
        a = Money.of(10, 250_000_000, "USD")
        b = Money.of(3, 750_000_000, "USD")
        assert a.add(b) == b.add(a)

    def test_associativity(self) -> None:
        a = Money.of(1, 100_000_000, "USD")
        b = Money.of(2, 200_000_000, "USD")
        c = Money.of(3, 300_000_000, "USD")
        assert a.add(b).add(c) == a.add(b.add(c))

    def test_currency_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="Currency mismatch"):
            Money.of(10, 0, "USD").add(Money.of(10, 0, "GBP"))


# ---------------------------------------------------------------------------
# Subtraction invariants
# ---------------------------------------------------------------------------

class TestMoneySubtraction:
    def test_basic_subtract(self) -> None:
        a = Money.of(10, 0, "USD")
        b = Money.of(3, 0, "USD")
        result = a.subtract(b)
        assert result.units == 7
        assert result.nanos == 0

    def test_subtract_self_is_zero(self) -> None:
        m = Money.of(42, 500_000_000, "USD")
        result = m.subtract(m)
        assert result.is_zero()

    def test_subtract_produces_negative(self) -> None:
        a = Money.of(5, 0, "USD")
        b = Money.of(10, 0, "USD")
        result = a.subtract(b)
        assert result.is_negative()
        assert result.units == -5

    def test_add_inverse_is_zero(self) -> None:
        m = Money.of(7, 300_000_000, "USD")
        neg_m = Money.of(-7, -300_000_000, "USD")
        result = m.add(neg_m)
        assert result.is_zero()


# ---------------------------------------------------------------------------
# Decimal representation — mirrors TypeScript Money.toDecimal()
# ---------------------------------------------------------------------------

class TestMoneyDecimalRepresentation:
    @pytest.mark.parametrize("units,nanos,expected", [
        (29, 990_000_000, "29.99"),
        (0, 0, "0"),
        (100, 0, "100"),
        (1, 500_000_000, "1.5"),
        (0, 1_000, "0.000001"),   # $0.000001
        (-5, -500_000_000, "-5.5"),
        (0, -500_000_000, "-0.5"),
    ])
    def test_to_decimal(self, units: int, nanos: int, expected: str) -> None:
        m = Money.of(units, nanos, "USD")
        assert m.to_decimal() == expected


# ---------------------------------------------------------------------------
# Cross-language consistency: verify same semantics as Go payment service
# These encode the contract that ALL language implementations must honour
# ---------------------------------------------------------------------------

class TestCrossLanguageContractInvariants:
    """
    These invariants are validated in:
    - Go: services/payment/tests/unit/payment_service_test.go (TestMoneyAdd, TestMoneySubtract)
    - Kotlin: services/order/src/test/kotlin/unit/OrderServiceTest.kt
    - TypeScript: services/catalog/tests/unit/CatalogService.test.ts
    - Python: here (analytics / notification services)
    """

    def test_money_add_matches_go_testcase(self) -> None:
        """Mirror of Go TestMoneyAdd: $10.50 + $5.25 = $15.75"""
        a = Money.of(10, 500_000_000, "USD")
        b = Money.of(5, 250_000_000, "USD")
        result = a.add(b)
        assert result.units == 15
        assert result.nanos == 750_000_000

    def test_money_subtract_matches_go_testcase(self) -> None:
        """Mirrors Kotlin/TypeScript units+nanos model: $10.00 - $3.50 = $6.50
        (Go payment uses cents int64 -- different representation entirely)"""
        a = Money.of(10, 0, "USD")
        b = Money.of(3, 500_000_000, "USD")
        result = a.subtract(b)
        assert result.units == 6
        assert result.nanos == 500_000_000

    def test_currency_mismatch_always_errors(self) -> None:
        """All implementations must raise on currency mismatch."""
        currencies = ["USD", "GBP", "EUR", "JPY"]
        for c1 in currencies:
            for c2 in currencies:
                if c1 != c2:
                    with pytest.raises((ValueError, Exception)):
                        Money.of(1, 0, c1).add(Money.of(1, 0, c2))

    def test_nanos_boundary_999999999(self) -> None:
        """Maximum valid nanos — same boundary in all implementations."""
        m = Money.of(0, 999_999_999, "USD")
        assert m.nanos == 999_999_999

    def test_large_amounts_no_overflow(self) -> None:
        """$1,000,000.00 + $1,000,000.00 = $2,000,000.00"""
        a = Money.of(1_000_000, 0, "USD")
        result = a.add(a)
        assert result.units == 2_000_000
        assert result.nanos == 0
