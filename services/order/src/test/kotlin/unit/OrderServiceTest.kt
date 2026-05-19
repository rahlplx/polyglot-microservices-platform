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
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.DisplayName
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.time.Instant
import java.util.UUID

/**
 * Unit tests for OrderService.
 *
 * Tests the core domain logic with mocked outbound ports,
 * verifying that state transitions, idempotency, and saga
 * orchestration behave correctly.
 */
class OrderServiceTest {

    private lateinit var orderRepository: OrderRepositoryPort
    private lateinit var eventPublisher: EventPublisherPort
    private lateinit var sagaOrchestrator: SagaOrchestrator
    private lateinit var catalogClient: CatalogClientPort
    private lateinit var paymentClient: PaymentClientPort
    private lateinit var orderService: OrderService

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

        orderService = OrderService(
            orderRepository = orderRepository,
            eventPublisher = eventPublisher,
            sagaOrchestrator = sagaOrchestrator
        )
    }

    private fun sampleAddress() = Address(
        line1 = "123 Main St",
        city = "Springfield",
        state = "IL",
        postalCode = "62701",
        countryCode = "US"
    )

    private fun sampleAddressInput() = AddressInput(
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
        lines = listOf(
            OrderLine.create("product-1", "Widget", 2, Money.of(29, 990000000, "USD"))
        ),
        total = Money.of(59, 980000000, "USD"),
        status = status,
        shippingAddress = sampleAddress(),
        paymentId = paymentId,
        reservationIds = reservationIds,
        createdAt = Instant.now(),
        updatedAt = Instant.now()
    )

    // --- Create Order Tests ---

    @Nested
    @DisplayName("Create Order")
    inner class CreateOrderTests {

        @Test
        @DisplayName("should create order in PENDING status")
        fun shouldCreateOrderInPendingStatus() = runTest {
            // Given
            coEvery { orderRepository.findByIdempotencyKey(any()) } returns null
            coEvery { orderRepository.inTransaction<Any>(any()) } coAnswers {
                val block = firstArg<suspend () -> Any>()
                block()
            }
            coEvery { orderRepository.save(any()) } answers { firstArg() }
            coEvery { orderRepository.saveSagaState(any()) } answers { firstArg() }
            coEvery { orderRepository.appendToOutbox(any()) } returns Unit

            // When
            val order = orderService.create(
                customerId = "customer-1",
                lines = listOf(LineItemInput("product-1", 2)),
                shippingAddress = sampleAddressInput(),
                paymentMethodId = "pm-123"
            )

            // Then
            assertNotNull(order)
            assertEquals(OrderStatus.PENDING, order.status)
            assertEquals("customer-1", order.customerId)
            assertEquals(1, order.lines.size)
        }

        @Test
        @DisplayName("should return existing order for duplicate idempotency key")
        fun shouldReturnExistingOrderForDuplicateKey() = runTest {
            // Given
            val existingOrder = sampleOrder()
            coEvery { orderRepository.findByIdempotencyKey("idem-1") } returns existingOrder

            // When
            val order = orderService.create(
                customerId = "customer-1",
                lines = listOf(LineItemInput("product-1", 2)),
                shippingAddress = sampleAddressInput(),
                paymentMethodId = "pm-123",
                idempotencyKey = "idem-1"
            )

            // Then
            assertEquals(existingOrder.orderId, order.orderId)
            coVerify(exactly = 0) { orderRepository.save(any()) }
        }

        @Test
        @DisplayName("should reject empty line items")
        fun shouldRejectEmptyLineItems() = runTest {
            assertThrows<IllegalArgumentException> {
                orderService.create(
                    customerId = "customer-1",
                    lines = emptyList(),
                    shippingAddress = sampleAddressInput(),
                    paymentMethodId = "pm-123"
                )
            }
        }

        @Test
        @DisplayName("should reject blank customer ID")
        fun shouldRejectBlankCustomerId() = runTest {
            assertThrows<IllegalArgumentException> {
                orderService.create(
                    customerId = "",
                    lines = listOf(LineItemInput("product-1", 2)),
                    shippingAddress = sampleAddressInput(),
                    paymentMethodId = "pm-123"
                )
            }
        }
    }

    // --- Cancel Order Tests ---

    @Nested
    @DisplayName("Cancel Order")
    inner class CancelOrderTests {

        @Test
        @DisplayName("should cancel PENDING order directly without compensation")
        fun shouldCancelPendingOrder() = runTest {
            // Given
            val order = sampleOrder(status = OrderStatus.PENDING)
            coEvery { orderRepository.findById(order.orderId) } returns order
            coEvery { orderRepository.inTransaction<Any>(any()) } coAnswers {
                val block = firstArg<suspend () -> Any>()
                block()
            }
            coEvery { orderRepository.save(any()) } answers { firstArg() }

            // When
            val cancelled = orderService.cancel(order.orderId, "customer request", "customer-1")

            // Then
            assertEquals(OrderStatus.CANCELLED, cancelled.status)
            assertEquals("customer request", cancelled.cancelReason)
        }

        @Test
        @DisplayName("should throw OrderNotFoundException for non-existent order")
        fun shouldThrowForNonExistentOrder() = runTest {
            coEvery { orderRepository.findById("nonexistent") } returns null

            assertThrows<OrderNotFoundException> {
                orderService.cancel("nonexistent", "reason", "user")
            }
        }

        @Test
        @DisplayName("should throw OrderNotCancellableException for COMPLETED order")
        fun shouldThrowForCompletedOrder() = runTest {
            val order = sampleOrder(status = OrderStatus.COMPLETED)
            coEvery { orderRepository.findById(order.orderId) } returns order

            assertThrows<OrderNotCancellableException> {
                orderService.cancel(order.orderId, "reason", "user")
            }
        }

        @Test
        @DisplayName("should begin compensation for RESERVED order")
        fun shouldBeginCompensationForReservedOrder() = runTest {
            // Given
            val order = sampleOrder(
                status = OrderStatus.RESERVED,
                reservationIds = listOf("res-1")
            )
            coEvery { orderRepository.findById(order.orderId) } returns order
            coEvery { orderRepository.findSagaByOrderId(order.orderId) } returns null
            coEvery { orderRepository.inTransaction<Any>(any()) } coAnswers {
                val block = firstArg<suspend () -> Any>()
                block()
            }
            coEvery { orderRepository.save(any()) } answers { firstArg() }

            // When
            val result = orderService.cancel(order.orderId, "reason", "user")

            // Then
            assertEquals(OrderStatus.COMPENSATING, result.status)
        }
    }

    // --- Complete Order Tests ---

    @Nested
    @DisplayName("Complete Order")
    inner class CompleteOrderTests {

        @Test
        @DisplayName("should complete FULFILLING order")
        fun shouldCompleteFulfillingOrder() = runTest {
            // Given
            val order = sampleOrder(status = OrderStatus.FULFILLING)
            coEvery { orderRepository.findById(order.orderId) } returns order
            coEvery { orderRepository.inTransaction<Any>(any()) } coAnswers {
                val block = firstArg<suspend () -> Any>()
                block()
            }
            coEvery { orderRepository.save(any()) } answers { firstArg() }

            // When
            val completed = orderService.complete(order.orderId)

            // Then
            assertEquals(OrderStatus.COMPLETED, completed.status)
            assertNotNull(completed.completedAt)
        }

        @Test
        @DisplayName("should throw for non-completable PENDING order")
        fun shouldThrowForPendingOrder() = runTest {
            val order = sampleOrder(status = OrderStatus.PENDING)
            coEvery { orderRepository.findById(order.orderId) } returns order

            assertThrows<OrderNotCompletableException> {
                orderService.complete(order.orderId)
            }
        }
    }

    // --- List Orders Tests ---

    @Nested
    @DisplayName("List Orders")
    inner class ListOrdersTests {

        @Test
        @DisplayName("should list orders for customer")
        fun shouldListOrdersForCustomer() = runTest {
            // Given
            val orders = listOf(sampleOrder(), sampleOrder())
            val page = Page(items = orders, totalCount = 2, cursor = null, hasMore = false)
            coEvery { orderRepository.findByCustomer("customer-1", any(), any(), any()) } returns page

            // When
            val result = orderService.list(customerId = "customer-1")

            // Then
            assertEquals(2, result.items.size)
            assertEquals(2L, result.totalCount)
        }

        @Test
        @DisplayName("should reject invalid page size")
        fun shouldRejectInvalidPageSize() = runTest {
            assertThrows<IllegalArgumentException> {
                orderService.list(pageSize = 0)
            }
            assertThrows<IllegalArgumentException> {
                orderService.list(pageSize = 101)
            }
        }
    }

    // --- Get Order Status Tests ---

    @Nested
    @DisplayName("Get Order Status")
    inner class GetOrderStatusTests {

        @Test
        @DisplayName("should return order status with saga info")
        fun shouldReturnOrderStatusWithSagaInfo() = runTest {
            // Given
            val order = sampleOrder(status = OrderStatus.RESERVED)
            val saga = SagaInstance.create(
                sagaId = "saga-1",
                orderId = order.orderId,
                sagaType = SagaType.ORDER_CREATION,
                steps = listOf(
                    SagaStep.define("RESERVE_INVENTORY").start().complete(),
                    SagaStep.define("AUTHORIZE_PAYMENT").start()
                )
            )
            coEvery { orderRepository.findById(order.orderId) } returns order
            coEvery { orderRepository.findSagaByOrderId(order.orderId) } returns saga

            // When
            val status = orderService.getStatus(order.orderId, includeHistory = true)

            // Then
            assertEquals(order.orderId, status.orderId)
            assertEquals(OrderStatus.RESERVED, status.status)
            assertEquals("AUTHORIZE_PAYMENT", status.currentSagaStep)
            assertEquals(listOf("RESERVE_INVENTORY"), status.completedSteps)
            assertEquals(listOf("AUTHORIZE_PAYMENT"), status.remainingSteps)
        }
    }
}
