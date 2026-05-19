package com.company.order.domain.models

/**
 * Value object representing a monetary amount with currency.
 * Follows ISO 4217 currency codes and provides precision-safe arithmetic.
 * Immutable by design — all operations return new instances.
 *
 * Domain core has ZERO external dependencies.
 */
data class Money(
    val units: Long,
    val nanos: Int,
    val currencyCode: String
) {
    companion object {
        /** The maximum absolute value for nanos (999,999,999) */
        private const val NANOS_PER_UNIT = 1_000_000_000L

        /** Create Money from a decimal representation: e.g. fromDecimal(29.99, "USD") */
        fun fromDecimal(amount: Double, currencyCode: String): Money {
            require(amount.isFinite()) { "Amount must be finite" }
            val sign = if (amount < 0) -1 else 1
            val absAmount = kotlin.math.abs(amount)
            val units = (absAmount.toLong()) * sign
            val nanos = ((absAmount - absAmount.toLong()) * NANOS_PER_UNIT).toInt() * sign
            return Money(units, nanos, currencyCode.uppercase())
        }

        /** Create Money from units and nanos with normalization */
        fun of(units: Long, nanos: Int, currencyCode: String): Money {
            val normalized = normalize(units, nanos)
            return Money(normalized.first, normalized.second, currencyCode.uppercase())
        }

        /** Zero amount in the given currency */
        fun zero(currencyCode: String): Money = Money(0, 0, currencyCode.uppercase())

        private fun normalize(units: Long, nanos: Int): Pair<Long, Int> {
            var u = units
            var n = nanos
            // Carry overflow from nanos to units
            if (n >= NANOS_PER_UNIT) {
                u += n / NANOS_PER_UNIT
                n = (n % NANOS_PER_UNIT).toInt()
            }
            // Ensure nanos and units have the same sign (or nanos is zero)
            if (u > 0 && n < 0) {
                u -= 1
                n = (n + NANOS_PER_UNIT).toInt()
            } else if (u < 0 && n > 0) {
                u += 1
                n = (n - NANOS_PER_UNIT).toInt()
            }
            return Pair(u, n)
        }
    }

    init {
        require(currencyCode.isNotBlank()) { "Currency code must not be blank" }
        require(currencyCode.length == 3) { "Currency code must be 3 characters (ISO 4217)" }
        require(kotlin.math.abs(nanos) < NANOS_PER_UNIT) {
            "Nanos absolute value must be < $NANOS_PER_UNIT, got $nanos"
        }
        require((units == 0L && nanos == 0) || (units > 0 && nanos >= 0) || (units < 0 && nanos <= 0)) {
            "Units and nanos must have the same sign (or one must be zero). units=$units, nanos=$nanos"
        }
    }

    val isNegative: Boolean get() = units < 0 || (units == 0L && nanos < 0)
    val isZero: Boolean get() = units == 0L && nanos == 0
    val isPositive: Boolean get() = units > 0 || (units == 0L && nanos > 0)

    /** Add two Money values. Must have the same currency. */
    operator fun plus(other: Money): Money {
        requireSameCurrency(other)
        return of(this.units + other.units, this.nanos + other.nanos, currencyCode)
    }

    /** Subtract two Money values. Must have the same currency. */
    operator fun minus(other: Money): Money {
        requireSameCurrency(other)
        return of(this.units - other.units, this.nanos - other.nanos, currencyCode)
    }

    /** Multiply by a scalar factor */
    fun multiply(factor: Int): Money = of(units * factor, nanos * factor, currencyCode)

    /** Negate the amount */
    fun negate(): Money = of(-units, -nanos, currencyCode)

    /** Absolute value */
    fun abs(): Money = if (isNegative) negate() else this

    private fun requireSameCurrency(other: Money) {
        require(currencyCode == other.currencyCode) {
            "Cannot operate on Money with different currencies: $currencyCode vs ${other.currencyCode}"
        }
    }

    override fun toString(): String = "${if (isNegative) "-" else ""}${kotlin.math.abs(units)}.${
        kotlin.math.abs(nanos).toString().padStart(9, '0').trimEnd('0')
    } $currencyCode"
}
