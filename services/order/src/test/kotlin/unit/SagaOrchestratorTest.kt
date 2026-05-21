package com.company.order.unit

import com.company.order.domain.models.*
import com.company.order.domain.ports.outbound.DomainEvent
import com.company.order.domain.ports.outbound.EventPublisherPort
import com.company.order.domain.ports.outbound.OutboxEntry
import com.company.order.domain.ports.outbound.OrderRepositoryPort
import com.company.order.domain.saga.*
import com.company.order.domain.services.*
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.DisplayName
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test
import java.time.Instant
import java.util.UUID

/**
 * Unit tests for SagaOrchestrator.
 *
 * Tests the saga orchestration logic including:
 * - Forward step execution (creation saga)
 * - Compensation on failure (cancellation saga)
 * - Saga recovery for stuck instances
 * - Step retry logic
 */
class SagaOrchestratorTest {

    private lateinit var orderRepository: OrderRepositoryPort
    private lateinit var eventPublisher: EventPublisherPort
    private lateinit var catalogClient: CatalogClientPort
    private lateinit var paymentClient: PaymentClientPort
    private lateinit var sagaOrchestrator: SagaOrchestrator

    @BeforeEach
    fun setUp() {
        orderRepository = mockk(relaxed = true)
        eventPublisher = mockk(relaxed = true)
        catalogClient = mockk(relaxed = true)
        paymentClient = mockk(relaxed = true)

        sagaOrchestrator = SagaOrchestrator(
            orderRepository = orderRepository,
            eventPublisher = eventPublisher,
            catalogClient = catalogClient,
            paymentClient = paymentClient
        )
    }

    private fun sampleAddress() = Address(
        line1 = "123 Main St",
        city = "Springfield",
        state = "IL",
        postalCode = "62701",
        countryCode = "US"
    )

    private fun sampleOrder(
        status: OrderStatus = OrderStatus.PENDING,
        paymentId: String? = null,
        reservationIds: List<String> = emptyList()
    ) = Order(
        orderId = UUID.randomUUID().toString(),
        customerId = "customer-1",
        lines = listOf(OrderLine.create("product-1", "Widget", 2, Money.of(29, 990000000, "USD"))),
        total = Money.of(59, 980000000, "USD"),
        status = status,
        shippingAddress = sampleAddress(),
        paymentId = paymentId,
        reservationIds = reservationIds,
        createdAt = Instant.now(),
        updatedAt = Instant.now()
    )

    private fun sampleCreationSaga(orderId: String) = SagaInstance.create(
        sagaId = UUID.randomUUID().toString(),
        orderId = orderId,
        sagaType = SagaType.ORDER_CREATION,
        steps = SagaDefinition.orderCreationSaga(orderId)
    )

    // --- Creation Saga Tests ---

    @Nested
    @DisplayName("Creation Saga")
    inner class CreationSagaTests {

        @Test
        @DisplayName("should execute all creation saga steps successfully")
        fun shouldExecuteAllCreationSteps() = runTest {
            // Given
            val order = sampleOrder()
            val saga = sampleCreationSaga(order.orderId)

            coEvery { orderRepository.findSagaByOrderId(order.orderId) } returns saga
            coEvery { orderRepository.inTransaction<Any>(any()) } coAnswers {
                val block = firstArg<suspend () -> Any>()
                block()
            }
            coEvery { orderRepository.save(any()) } answers { firstArg() }
            coEvery { orderRepository.saveSagaState(any()) } answers { firstArg() }
            coEvery { orderRepository.appendToOutbox(any()) } returns Unit

            coEvery { catalogClient.reserveInventory(any()) } returns ReservationResponse(
                reservationIds = listOf("res-1"),
                reservedItems = listOf(
                    ReservedItem("product-1", "Widget", Money.of(29, 990000000, "USD"), 2)
                )
            )

            coEvery { paymentClient.authorizePayment(any()) } returns PaymentAuthorizationResponse(
                paymentId = "pay-1",
                authorized = true,
                authorizationCode = "AUTH-123"
            )

            // When
            sagaOrchestrator.executeCreationSaga(order)

            // Then
            coVerify(atLeast = 3) { orderRepository.saveSagaState(any()) }
            coVerify { catalogClient.reserveInventory(any()) }
            coVerify { paymentClient.authorizePayment(any()) }
        }

        @Test
        @DisplayName("should compensate when inventory reservation fails")
        fun shouldCompensateOnReservationFailure() = runTest {
            // Given
            val order = sampleOrder()
            val saga = sampleCreationSaga(order.orderId)

            coEvery { orderRepository.findSagaByOrderId(order.orderId) } returns saga
            coEvery { orderRepository.inTransaction<Any>(any()) } coAnswers {
                val block = firstArg<suspend () -> Any>()
                block()
            }
            coEvery { orderRepository.save(any()) } answers { firstArg() }
            coEvery { orderRepository.saveSagaState(any()) } answers { firstArg() }
            coEvery { orderRepository.appendToOutbox(any()) } returns Unit

            coEvery { catalogClient.reserveInventory(any()) } throws RuntimeException("Inventory unavailable")

            // When
            sagaOrchestrator.executeCreationSaga(order)

            // Then - no compensation needed since RESERVE_INVENTORY is the first step
            // Order should transition to FAILED (PENDING → FAILED since no steps completed)
            coVerify { orderRepository.save(match { order -> order.status == OrderStatus.FAILED || order.status == OrderStatus.CANCELLED }) }
        }

        @Test
        @DisplayName("should compensate completed steps when payment authorization fails")
        fun shouldCompensateCompletedStepsOnPaymentFailure() = runTest {
            // Given
            val order = sampleOrder()
            val saga = sampleCreationSaga(order.orderId)

            coEvery { orderRepository.findSagaByOrderId(order.orderId) } returns saga
            coEvery { orderRepository.inTransaction<Any>(any()) } coAnswers {
                val block = firstArg<suspend () -> Any>()
                block()
            }
            coEvery { orderRepository.save(any()) } answers { firstArg() }
            coEvery { orderRepository.saveSagaState(any()) } answers { firstArg() }
            coEvery { orderRepository.appendToOutbox(any()) } returns Unit

            coEvery { catalogClient.reserveInventory(any()) } returns ReservationResponse(
                reservationIds = listOf("res-1"),
                reservedItems = listOf(ReservedItem("product-1", "Widget", Money.of(29, 990000000, "USD"), 2))
            )

            coEvery { paymentClient.authorizePayment(any()) } throws RuntimeException("Payment declined")

            coEvery { catalogClient.releaseInventory(any()) } returns ReleaseInventoryResponse(released = true)

            // When
            sagaOrchestrator.executeCreationSaga(order)

            // Then - inventory should be released as compensation
            coVerify { catalogClient.releaseInventory(any()) }
        }
    }

    // --- Cancellation Saga Tests ---

    @Nested
    @DisplayName("Cancellation Saga")
    inner class CancellationSagaTests {

        @Test
        @DisplayName("should release inventory and void payment for RESERVED order")
        fun shouldReleaseInventoryAndVoidPayment() = runTest {
            // Given
            val order = sampleOrder(
                status = OrderStatus.COMPENSATING,
                paymentId = "pay-1",
                reservationIds = listOf("res-1")
            )

            coEvery { orderRepository.findSagaByOrderId(order.orderId) } returns null
            coEvery { orderRepository.inTransaction<Any>(any()) } coAnswers {
                val block = firstArg<suspend () -> Any>()
                block()
            }
            coEvery { orderRepository.save(any()) } answers { firstArg() }
            coEvery { orderRepository.saveSagaState(any()) } answers { firstArg() }
            coEvery { orderRepository.appendToOutbox(any()) } returns Unit

            coEvery { catalogClient.releaseInventory(any()) } returns ReleaseInventoryResponse(released = true)
            coEvery { paymentClient.voidAuthorization(any()) } returns VoidAuthorizationResponse(voided = true)

            // When
            sagaOrchestrator.executeCancellationSaga(
                order = order,
                completedForwardSteps = listOf("RESERVE_INVENTORY", "AUTHORIZE_PAYMENT"),
                reason = "Customer request"
            )

            // Then
            coVerify { catalogClient.releaseInventory(any()) }
            coVerify { paymentClient.voidAuthorization(any()) }
        }

        @Test
        @DisplayName("should refund captured payment for PAID order")
        fun shouldRefundCapturedPaymentForPaidOrder() = runTest {
            // Given
            val order = sampleOrder(
                status = OrderStatus.COMPENSATING,
                paymentId = "pay-1",
                reservationIds = listOf("res-1")
            )

            coEvery { orderRepository.findSagaByOrderId(order.orderId) } returns null
            coEvery { orderRepository.inTransaction<Any>(any()) } coAnswers {
                val block = firstArg<suspend () -> Any>()
                block()
            }
            coEvery { orderRepository.save(any()) } answers { firstArg() }
            coEvery { orderRepository.saveSagaState(any()) } answers { firstArg() }
            coEvery { orderRepository.appendToOutbox(any()) } returns Unit

            coEvery { catalogClient.releaseInventory(any()) } returns ReleaseInventoryResponse(released = true)
            coEvery { paymentClient.refundPayment(any()) } returns RefundPaymentResponse(
                refundId = "refund-1",
                refunded = true,
                refundedAmount = order.total
            )

            // When - PAID order means payment was captured
            sagaOrchestrator.executeCancellationSaga(
                order = order,
                completedForwardSteps = listOf("RESERVE_INVENTORY", "AUTHORIZE_PAYMENT", "CONFIRM_ORDER"),
                reason = "Fraud detected"
            )

            // Then - should refund (not void) since payment was captured
            coVerify { paymentClient.refundPayment(any()) }
        }
    }

    // --- Saga Step Tests ---

    @Nested
    @DisplayName("Saga Step Transitions")
    inner class SagaStepTests {

        @Test
        @DisplayName("should transition step through PENDING → RUNNING → COMPLETED")
        fun shouldTransitionStepThroughStates() {
            val step = SagaStep.define("TEST_STEP", maxRetries = 3)

            assertEquals(SagaStepStatus.PENDING, step.status)

            val started = step.start()
            assertEquals(SagaStepStatus.RUNNING, started.status)
            assertNotNull(started.startedAt)

            val completed = started.complete()
            assertEquals(SagaStepStatus.COMPLETED, completed.status)
            assertNotNull(completed.completedAt)
        }

        @Test
        @DisplayName("should transition step through COMPENSATING → COMPENSATED")
        fun shouldTransitionStepCompensation() {
            val step = SagaStep.define("TEST_STEP", maxRetries = 3).start().complete()

            val compensating = step.beginCompensation()
            assertEquals(SagaStepStatus.COMPENSATING, compensating.status)

            val compensated = compensating.completeCompensation()
            assertEquals(SagaStepStatus.COMPENSATED, compensated.status)
        }

        @Test
        @DisplayName("should support retry for failed steps")
        fun shouldSupportRetryForFailedSteps() {
            val step = SagaStep.define("TEST_STEP", maxRetries = 3).start().fail("Error")

            assertEquals(SagaStepStatus.FAILED, step.status)
            assertTrue(step.canRetry)

            val retried = step.prepareRetry()
            assertEquals(SagaStepStatus.PENDING, retried.status)
            assertEquals(1, retried.retryCount)
        }

        @Test
        @DisplayName("should not allow retry when max retries exceeded")
        fun shouldNotAllowRetryWhenMaxExceeded() {
            val step = SagaStep.define("TEST_STEP", maxRetries = 1)
                .start().fail("Error").prepareRetry().start().fail("Error again")

            assertFalse(step.canRetry)
            assertThrows<IllegalArgumentException> { step.prepareRetry() }
        }
    }

    // --- Saga Instance Tests ---

    @Nested
    @DisplayName("Saga Instance State")
    inner class SagaInstanceStateTests {

        @Test
        @DisplayName("should track completed and remaining steps")
        fun shouldTrackStepProgress() {
            val saga = SagaInstance.create(
                sagaId = "saga-1",
                orderId = "order-1",
                sagaType = SagaType.ORDER_CREATION,
                steps = listOf(
                    SagaStep.define("STEP_1").start().complete(),
                    SagaStep.define("STEP_2").start(),
                    SagaStep.define("STEP_3")
                )
            )

            assertEquals(listOf("STEP_1"), saga.completedStepNames)
            assertEquals(listOf("STEP_3"), saga.remainingStepNames)
            assertEquals("STEP_2", saga.currentStep?.stepName)
            assertFalse(saga.allStepsCompleted)
        }

        @Test
        @DisplayName("should complete saga when all steps are done")
        fun shouldCompleteSagaWhenAllStepsDone() {
            val saga = SagaInstance.create(
                sagaId = "saga-1",
                orderId = "order-1",
                sagaType = SagaType.ORDER_CREATION,
                steps = listOf(SagaStep.define("STEP_1"))
            )

            val started = saga.startStep("STEP_1")
            val completed = started.completeStep("STEP_1")

            assertEquals(SagaStatus.COMPLETED, completed.status)
            assertNotNull(completed.completedAt)
            assertTrue(completed.allStepsCompleted)
        }
    }

    // --- OrderStatus State Machine Tests ---

    @Nested
    @DisplayName("Order Status State Machine")
    inner class OrderStatusStateMachineTests {

        @Test
        @DisplayName("should allow valid forward transitions")
        fun shouldAllowValidTransitions() {
            assertTrue(OrderStatus.canTransition(OrderStatus.PENDING, OrderStatus.RESERVED))
            assertTrue(OrderStatus.canTransition(OrderStatus.RESERVED, OrderStatus.PAID))
            assertTrue(OrderStatus.canTransition(OrderStatus.PAID, OrderStatus.FULFILLING))
            assertTrue(OrderStatus.canTransition(OrderStatus.FULFILLING, OrderStatus.COMPLETED))
        }

        @Test
        @DisplayName("should allow cancellation from any cancellable state")
        fun shouldAllowCancellation() {
            assertTrue(OrderStatus.canTransition(OrderStatus.PENDING, OrderStatus.CANCELLED))
            assertTrue(OrderStatus.canTransition(OrderStatus.RESERVED, OrderStatus.CANCELLED))
            assertTrue(OrderStatus.canTransition(OrderStatus.PAID, OrderStatus.CANCELLED))
            assertTrue(OrderStatus.canTransition(OrderStatus.FULFILLING, OrderStatus.CANCELLED))
        }

        @Test
        @DisplayName("should allow compensation from non-terminal states")
        fun shouldAllowCompensation() {
            assertTrue(OrderStatus.canTransition(OrderStatus.RESERVED, OrderStatus.COMPENSATING))
            assertTrue(OrderStatus.canTransition(OrderStatus.PAID, OrderStatus.COMPENSATING))
            assertTrue(OrderStatus.canTransition(OrderStatus.FULFILLING, OrderStatus.COMPENSATING))
        }

        @Test
        @DisplayName("should reject invalid transitions")
        fun shouldRejectInvalidTransitions() {
            assertFalse(OrderStatus.canTransition(OrderStatus.COMPLETED, OrderStatus.PENDING))
            assertFalse(OrderStatus.canTransition(OrderStatus.CANCELLED, OrderStatus.PENDING))
            assertFalse(OrderStatus.canTransition(OrderStatus.FAILED, OrderStatus.RESERVED))
            assertFalse(OrderStatus.canTransition(OrderStatus.PENDING, OrderStatus.COMPLETED))
            assertFalse(OrderStatus.canTransition(OrderStatus.PENDING, OrderStatus.FULFILLING))
        }

        @Test
        @DisplayName("should identify terminal states correctly") {
            assertTrue(OrderStatus.COMPLETED.isTerminal)
            assertTrue(OrderStatus.CANCELLED.isTerminal)
            assertTrue(OrderStatus.FAILED.isTerminal)
            assertFalse(OrderStatus.PENDING.isTerminal)
            assertFalse(OrderStatus.COMPENSATING.isTerminal)
        }
    }
}
