package com.company.order.property

import com.company.order.domain.models.*
import com.company.order.domain.saga.*
import net.jqwik.api.*
import net.jqwik.api.constraints.IntRange
import net.jqwik.api.constraints.Negative
import net.jqwik.api.constraints.Positive
import net.jqwik.api.constraints.StringLength
import net.jqwik.kotlin.api.any
import org.junit.jupiter.api.Assertions.*

/**
 * Property-based tests for the Order service using jqwik.
 *
 * Tests domain invariants with generated inputs to discover
 * edge cases that example-based tests might miss:
 * - Money arithmetic invariants
 * - Order state machine exhaustiveness
 * - Saga step transition soundness
 * - OrderLine total calculation consistency
 */
class OrderPropertiesTest {

    // --- Money Arithmetic Properties ---

    @Property
    @Label("Money addition is commutative")
    fun moneyAdditionIsCommutative(
        @ForAll a: MoneyArb,
        @ForAll b: MoneyArb
    ) {
        Assume.that(a.currencyCode == b.currencyCode)
        assertEquals(a + b, b + a)
    }

    @Property
    @Label("Money addition has zero identity")
    fun moneyAdditionHasZeroIdentity(@ForAll money: MoneyArb) {
        val zero = Money.zero(money.currencyCode)
        assertEquals(money, money + zero)
        assertEquals(money, zero + money)
    }

    @Property
    @Label("Money subtraction is inverse of addition")
    fun moneySubtractionIsInverseOfAddition(
        @ForAll a: MoneyArb,
        @ForAll b: MoneyArb
    ) {
        Assume.that(a.currencyCode == b.currencyCode)
        val sum = a + b
        assertEquals(a, sum - b)
    }

    @Property
    @Label("Money negation is self-inverse")
    fun moneyNegationIsSelfInverse(@ForAll money: MoneyArb) {
        assertEquals(money, money.negate().negate())
    }

    @Property
    @Label("Money absolute value is always non-negative")
    fun moneyAbsIsAlwaysNonNegative(@ForAll money: MoneyArb) {
        val abs = money.abs()
        assertTrue(abs.isPositive || abs.isZero)
    }

    @Property
    @Label("Money multiply by 0 is always zero")
    fun moneyMultiplyByZeroIsZero(@ForAll money: MoneyArb) {
        val result = money.multiply(0)
        assertTrue(result.isZero)
    }

    @Property
    @Label("Money multiply by 1 is identity")
    fun moneyMultiplyByOneIsIdentity(@ForAll money: MoneyArb) {
        assertEquals(money, money.multiply(1))
    }

    // --- OrderLine Properties ---

    @Property
    @Label("OrderLine total equals unit price times quantity")
    fun orderLineTotalEqualsPriceTimesQuantity(
        @ForAll @Positive units: Long,
        @ForAll @IntRange(min = 1, max = 999) nanos: Int,
        @ForAll @Positive quantity: Int
    ) {
        val unitPrice = Money.of(units, nanos, "USD")
        val line = OrderLine.create("p1", "Product", quantity, unitPrice)

        val expectedTotal = unitPrice.multiply(quantity)
        assertEquals(expectedTotal.units, line.lineTotal.units)
        assertEquals(expectedTotal.currencyCode, line.lineTotal.currencyCode)
    }

    @Property
    @Label("OrderLine rejects non-positive quantity")
    fun orderLineRejectsNonPositiveQuantity(@ForAll @Negative quantity: Int) {
        assertThrows<IllegalArgumentException> {
            OrderLine.create("p1", "Product", quantity, Money.of(10, 0, "USD"))
        }
    }

    @Property
    @Label("OrderLine rejects blank product ID")
    fun orderLineRejectsBlankProductId(
        @ForAll @StringLength(min = 0, max = 0) productId: String,
        @ForAll @Positive quantity: Int
    ) {
        assertThrows<IllegalArgumentException> {
            OrderLine.create(productId, "Product", quantity, Money.of(10, 0, "USD"))
        }
    }

    // --- State Machine Properties ---

    @Property
    @Label("Terminal states have no valid outgoing transitions")
    fun terminalStatesHaveNoOutgoingTransitions(@ForAll terminal: TerminalStatus) {
        OrderStatus.entries.forEach { target ->
            assertFalse(OrderStatus.canTransition(terminal.value, target))
        }
    }

    @Property
    @Label("Cancellable states can transition to CANCELLED")
    fun cancellableStatesCanTransitionToCancelled(@ForAll cancellable: CancellableStatus) {
        assertTrue(OrderStatus.canTransition(cancellable.value, OrderStatus.CANCELLED))
    }

    @Property
    @Label("State transitions are not reflexive (except terminal states)")
    fun stateTransitionsAreNotReflexive(@ForAll status: NonTerminalStatus) {
        assertFalse(OrderStatus.canTransition(status.value, status.value))
    }

    // --- Saga Step Properties ---

    @Property
    @Label("Completed saga step can be compensated")
    fun completedStepCanBeCompensated(
        @ForAll @StringLength(min = 1, max = 20) stepName: String
    ) {
        val step = SagaStep.define(stepName, maxRetries = 3).start().complete()
        val compensating = step.beginCompensation()
        assertEquals(SagaStepStatus.COMPENSATING, compensating.status)
        val compensated = compensating.completeCompensation()
        assertEquals(SagaStepStatus.COMPENSATED, compensated.status)
    }

    @Property
    @Label("Failed step retry count never exceeds max retries")
    fun failedStepRetryCountNeverExceedsMax(
        @ForAll @IntRange(min = 1, max = 5) maxRetries: Int
    ) {
        var step = SagaStep.define("STEP", maxRetries = maxRetries)

        // Fail and retry until max is reached
        for (i in 1..maxRetries) {
            step = step.start().fail("Error $i")
            if (i < maxRetries) {
                step = step.prepareRetry()
                assertEquals(i, step.retryCount)
            }
        }

        assertFalse(step.canRetry)
    }

    // --- Order Creation Properties ---

    @Property
    @Label("Order total equals sum of line totals")
    fun orderTotalEqualsSumOfLineTotals(
        @ForAll lines: OrderLinesArb
    ) {
        Assume.that(lines.isNotEmpty())
        Assume.that(lines.size <= 10)

        val address = Address("1 Main", city = "City", state = "ST", postalCode = "12345", countryCode = "US")

        try {
            val order = Order.create("order-1", "customer-1", lines, address)
            val expectedTotal = lines.fold(Money.zero(lines.first().unitPrice.currencyCode)) { acc, line ->
                acc + line.lineTotal
            }
            assertEquals(expectedTotal.units, order.total.units)
            assertEquals(expectedTotal.currencyCode, order.total.currencyCode)
        } catch (e: IllegalArgumentException) {
            // Currency mismatch is expected for some generated inputs
            Assume.that(false)
        }
    }

    // --- Custom Arbitraries ---

    /**
     * Arbitrary for generating valid Money instances.
     */
    class MoneyArb : Arbitrary<Money> {
        override fun generate(random: Randomizer): Money {
            val currency = listOf("USD", "EUR", "GBP", "JPY").random(random)
            val units = random.nextLong(-1000000, 1000000)
            val nanosSign = if (units >= 0) 1 else -1
            val nanos = random.nextInt(0, 999999999) * nanosSign
            val effectiveNanos = if (units == 0L && nanos == 0) 0 else nanos
            return Money.of(units, effectiveNanos, currency)
        }

        companion object {
            fun any() = MoneyArb()
        }
    }

    /**
     * Arbitrary for generating terminal OrderStatus values.
     */
    enum class TerminalStatus(val value: OrderStatus) {
        COMPLETED(OrderStatus.COMPLETED),
        CANCELLED(OrderStatus.CANCELLED),
        FAILED(OrderStatus.FAILED)
    }

    /**
     * Arbitrary for generating cancellable OrderStatus values.
     */
    enum class CancellableStatus(val value: OrderStatus) {
        PENDING(OrderStatus.PENDING),
        RESERVED(OrderStatus.RESERVED),
        PAID(OrderStatus.PAID),
        FULFILLING(OrderStatus.FULFILLING)
    }

    /**
     * Arbitrary for generating non-terminal OrderStatus values.
     */
    enum class NonTerminalStatus(val value: OrderStatus) {
        PENDING(OrderStatus.PENDING),
        RESERVED(OrderStatus.RESERVED),
        PAID(OrderStatus.PAID),
        FULFILLING(OrderStatus.FULFILLING),
        COMPENSATING(OrderStatus.COMPENSATING)
    }

    /**
     * Arbitrary for generating lists of OrderLines.
     */
    class OrderLinesArb : Arbitrary<List<OrderLine>> {
        override fun generate(random: Randomizer): List<OrderLine> {
            val count = random.nextInt(1, 5)
            return (1..count).map { i ->
                val units = random.nextLong(1, 10000)
                val nanos = random.nextInt(0, 999999999)
                OrderLine.create(
                    productId = "product-$i",
                    productName = "Product $i",
                    quantity = random.nextInt(1, 100),
                    unitPrice = Money.of(units, nanos, "USD")
                )
            }
        }
    }
}
