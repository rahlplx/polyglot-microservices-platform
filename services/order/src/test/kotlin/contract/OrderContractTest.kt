package com.company.order.contract

import com.company.order.domain.models.*
import com.company.order.domain.saga.*
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.DisplayName
import org.junit.jupiter.api.Test

/**
 * Contract tests for the Order service.
 *
 * Verifies that domain contracts and invariants are maintained:
 * - State machine transitions
 * - Money arithmetic precision
 * - Order invariants
 * - Saga step constraints
 * - Domain event type constants
 */
class OrderContractTest {

    // --- State Machine Contract ---

    @Test
    @DisplayName("State machine must enforce all valid transitions from proto enum")
    fun stateMachineMustEnforceProtoTransitions() {
        // The proto defines: PENDING(1) → RESERVED(2) → PAID(3) → FULFILLING(4) → COMPLETED(5)
        // with CANCELLED(6), FAILED(7), COMPENSATING(8) branches

        // Happy path
        assertTrue(OrderStatus.canTransition(OrderStatus.PENDING, OrderStatus.RESERVED))
        assertTrue(OrderStatus.canTransition(OrderStatus.RESERVED, OrderStatus.PAID))
        assertTrue(OrderStatus.canTransition(OrderStatus.PAID, OrderStatus.FULFILLING))
        assertTrue(OrderStatus.canTransition(OrderStatus.FULFILLING, OrderStatus.COMPLETED))

        // Failure branches
        assertTrue(OrderStatus.canTransition(OrderStatus.PENDING, OrderStatus.FAILED))
        assertTrue(OrderStatus.canTransition(OrderStatus.PENDING, OrderStatus.CANCELLED))

        // Compensation paths
        assertTrue(OrderStatus.canTransition(OrderStatus.RESERVED, OrderStatus.COMPENSATING))
        assertTrue(OrderStatus.canTransition(OrderStatus.PAID, OrderStatus.COMPENSATING))
        assertTrue(OrderStatus.canTransition(OrderStatus.FULFILLING, OrderStatus.COMPENSATING))
        assertTrue(OrderStatus.canTransition(OrderStatus.COMPENSATING, OrderStatus.CANCELLED))
        assertTrue(OrderStatus.canTransition(OrderStatus.COMPENSATING, OrderStatus.FAILED))

        // Terminal states are immutable
        OrderStatus.TERMINAL_STATES.forEach { terminal ->
            OrderStatus.entries.forEach { target ->
                assertFalse(OrderStatus.canTransition(terminal, target),
                    "Terminal state $terminal should not transition to $target")
            }
        }
    }

    // --- Money Contract ---

    @Test
    @DisplayName("Money must reject mismatched currency operations")
    fun moneyMustRejectMismatchedCurrencies() {
        val usd = Money.of(10, 0, "USD")
        val eur = Money.of(10, 0, "EUR")

        assertThrows<IllegalArgumentException> { usd + eur }
        assertThrows<IllegalArgumentException> { usd - eur }
    }

    @Test
    @DisplayName("Money must maintain nanos sign consistency with units")
    fun moneyMustMaintainNanosSignConsistency() {
        assertThrows<IllegalArgumentException> {
            Money(units = 10L, nanos = -500000000, currencyCode = "USD")
        }
        assertThrows<IllegalArgumentException> {
            Money(units = -10L, nanos = 500000000, currencyCode = "USD")
        }
    }

    @Test
    @DisplayName("Money must reject invalid currency codes")
    fun moneyMustRejectInvalidCurrencyCodes() {
        assertThrows<IllegalArgumentException> { Money.of(10, 0, "") }
        assertThrows<IllegalArgumentException> { Money.of(10, 0, "US") }
        assertThrows<IllegalArgumentException> { Money.of(10, 0, "DOLLAR") }
    }

    @Test
    @DisplayName("Money arithmetic must be precise with nanos")
    fun moneyArithmeticMustBePrecise() {
        val a = Money.of(1, 500000000, "USD")  // 1.50
        val b = Money.of(0, 500000000, "USD")  // 0.50
        val sum = a + b
        assertEquals(2L, sum.units)
        assertEquals(0, sum.nanos)
        assertEquals("USD", sum.currencyCode)

        val diff = a - b
        assertEquals(1L, diff.units)
        assertEquals(0, diff.nanos)
    }

    // --- Order Contract ---

    @Test
    @DisplayName("Order must require at least one line item")
    fun orderMustRequireAtLeastOneLineItem() {
        assertThrows<IllegalArgumentException> {
            Order.create(
                orderId = "order-1",
                customerId = "customer-1",
                lines = emptyList(),
                shippingAddress = Address("1 Main", city = "City", state = "ST", postalCode = "12345", countryCode = "US")
            )
        }
    }

    @Test
    @DisplayName("Order must reject blank orderId and customerId")
    fun orderMustRejectBlankIds() {
        val address = Address("1 Main", city = "City", state = "ST", postalCode = "12345", countryCode = "US")
        val line = OrderLine.create("p1", "Product", 1, Money.of(10, 0, "USD"))

        assertThrows<IllegalArgumentException> {
            Order.create("", "customer-1", listOf(line), address)
        }
        assertThrows<IllegalArgumentException> {
            Order.create("order-1", "", listOf(line), address)
        }
    }

    @Test
    @DisplayName("Order state transitions must respect state machine")
    fun orderStateTransitionsMustRespectStateMachine() {
        val address = Address("1 Main", city = "City", state = "ST", postalCode = "12345", countryCode = "US")
        val line = OrderLine.create("p1", "Product", 1, Money.of(10, 0, "USD"))
        val order = Order.create("order-1", "customer-1", listOf(line), address)

        // Can't skip to COMPLETED from PENDING
        assertThrows<IllegalArgumentException> { order.complete() }

        // Can't reserve without reservation IDs
        assertThrows<IllegalArgumentException> { order.reserve(emptyList()) }

        // Happy path
        val reserved = order.reserve(listOf("res-1"))
        assertEquals(OrderStatus.RESERVED, reserved.status)

        val paid = reserved.authorizePayment("pay-1")
        assertEquals(OrderStatus.PAID, paid.status)

        val fulfilling = paid.beginFulfillment()
        assertEquals(OrderStatus.FULFILLING, fulfilling.status)

        val completed = fulfilling.complete()
        assertEquals(OrderStatus.COMPLETED, completed.status)
    }

    // --- Saga Contract ---

    @Test
    @DisplayName("Saga must define exactly 3 creation steps")
    fun sagaMustDefineThreeCreationSteps() {
        val steps = SagaDefinition.orderCreationSaga("order-1")
        assertEquals(3, steps.size)
        assertEquals("RESERVE_INVENTORY", steps[0].stepName)
        assertEquals("AUTHORIZE_PAYMENT", steps[1].stepName)
        assertEquals("CONFIRM_ORDER", steps[2].stepName)
    }

    @Test
    @DisplayName("Saga creation steps must all have compensation actions")
    fun creationStepsMustHaveCompensationActions() {
        val steps = SagaDefinition.orderCreationSaga("order-1")
        steps.forEach { step ->
            assertNotNull(step.compensationAction, "Step ${step.stepName} must have a compensation action")
        }
    }

    @Test
    @DisplayName("Cancellation saga must be adaptive based on completed steps")
    fun cancellationSagaMustBeAdaptive() {
        // No completed steps → minimal cancellation
        val minimal = SagaDefinition.orderCancellationSaga("o1", emptyList(), null, emptyList(), false)
        assertEquals(1, minimal.size) // Just notification
        assertEquals("NOTIFY_CANCELLATION", minimal[0].stepName)

        // All steps completed → full cancellation
        val full = SagaDefinition.orderCancellationSaga(
            "o1",
            listOf("RESERVE_INVENTORY", "AUTHORIZE_PAYMENT", "CONFIRM_ORDER"),
            "pay-1",
            listOf("res-1"),
            true
        )
        assertTrue(full.size >= 3) // Release + Refund + Notify
    }

    // --- Domain Event Contract ---

    @Test
    @DisplayName("Domain events must follow naming convention")
    fun domainEventsMustFollowNamingConvention() {
        val prefix = "com.company.order."
        assertTrue(DomainEvent.ORDER_CREATED.startsWith(prefix))
        assertTrue(DomainEvent.ORDER_COMPLETED.startsWith(prefix))
        assertTrue(DomainEvent.ORDER_CANCELLED.startsWith(prefix))
        assertTrue(DomainEvent.ORDER_FAILED.startsWith(prefix))
        assertTrue(DomainEvent.SAGA_STEP_COMPLETED.startsWith(prefix))
    }

    // --- OutboxEntry Contract ---

    @Test
    @DisplayName("OutboxEntry equality must be based on eventId")
    fun outboxEntryEqualityMustBeBasedOnEventId() {
        val entry1 = com.company.order.domain.ports.outbound.OutboxEntry(
            eventId = "evt-1",
            aggregateId = "agg-1",
            aggregateType = "Order",
            eventType = "created",
            payload = "data".toByteArray()
        )
        val entry2 = entry1.copy(payload = "different".toByteArray())

        assertEquals(entry1, entry2) // Same eventId, different payload
        assertEquals(entry1.hashCode(), entry2.hashCode())
    }
}
