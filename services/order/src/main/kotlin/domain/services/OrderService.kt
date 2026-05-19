package com.company.order.domain.services

import com.company.order.domain.models.*
import com.company.order.domain.ports.inbound.*
import com.company.order.domain.ports.outbound.DomainEvent
import com.company.order.domain.ports.outbound.EventPublisherPort
import com.company.order.domain.ports.outbound.OutboxEntry
import com.company.order.domain.ports.outbound.OrderRepositoryPort
import com.company.order.domain.saga.SagaDefinition
import com.company.order.domain.saga.SagaInstance
import com.company.order.domain.saga.SagaType
import org.slf4j.LoggerFactory
import java.time.Instant
import java.util.UUID

/**
 * Core domain service implementing all order use cases.
 *
 * Orchestrates order lifecycle operations including creation, completion,
 * cancellation, listing, and status queries. Delegates saga orchestration
 * to [SagaOrchestrator] for complex multi-step operations.
 *
 * Domain core has ZERO external dependencies (only uses domain ports and models).
 */
class OrderService(
    private val orderRepository: OrderRepositoryPort,
    private val eventPublisher: EventPublisherPort,
    private val sagaOrchestrator: SagaOrchestrator
) : CreateOrderUseCase, CompleteOrderUseCase, CancelOrderUseCase, ListOrdersUseCase, GetOrderStatusUseCase {

    private val logger = LoggerFactory.getLogger(OrderService::class.java)

    // --- CreateOrderUseCase ---

    override suspend fun create(
        customerId: String,
        lines: List<LineItemInput>,
        shippingAddress: AddressInput,
        paymentMethodId: String,
        idempotencyKey: String?
    ): Order {
        logger.info("Creating order for customer=$customerId with ${lines.size} line items")

        // Idempotency check: if we've seen this key before, return the existing order
        if (idempotencyKey != null) {
            val existing = orderRepository.findByIdempotencyKey(idempotencyKey)
            if (existing != null) {
                logger.info("Duplicate order detected for idempotency key=$idempotencyKey, returning existing order=${existing.orderId}")
                return existing
            }
        }

        // Build the order in PENDING state
        val orderId = UUID.randomUUID().toString()
        val address = Address(
            line1 = shippingAddress.line1,
            line2 = shippingAddress.line2,
            city = shippingAddress.city,
            state = shippingAddress.state,
            postalCode = shippingAddress.postalCode,
            countryCode = shippingAddress.countryCode
        )

        // For creation, we create minimal line items with placeholder pricing
        // Pricing will be resolved during the RESERVE_INVENTORY saga step
        val orderLines = lines.map { input ->
            OrderLine.create(
                productId = input.productId,
                productName = input.productId, // Will be enriched by catalog lookup
                quantity = input.quantity,
                unitPrice = Money.zero("USD") // Placeholder until catalog resolves pricing
            )
        }

        val order = Order.create(
            orderId = orderId,
            customerId = customerId,
            lines = orderLines,
            shippingAddress = address,
            idempotencyKey = idempotencyKey
        )

        // Persist order and outbox event in the same transaction
        val savedOrder = orderRepository.inTransaction {
            val persisted = orderRepository.save(order)

            // Write order created event to outbox (same transaction)
            val event = DomainEvent(
                eventId = UUID.randomUUID().toString(),
                eventType = DomainEvent.ORDER_CREATED,
                aggregateId = orderId,
                aggregateType = "Order",
                payload = orderId.toByteArray()
            )
            orderRepository.appendToOutbox(
                OutboxEntry(
                    eventId = event.eventId,
                    aggregateId = event.aggregateId,
                    aggregateType = event.aggregateType,
                    eventType = event.eventType,
                    payload = event.payload
                )
            )

            // Initialize and persist the creation saga
            val sagaSteps = SagaDefinition.orderCreationSaga(orderId)
            val saga = SagaInstance.create(
                sagaId = UUID.randomUUID().toString(),
                orderId = orderId,
                sagaType = SagaType.ORDER_CREATION,
                steps = sagaSteps
            )
            orderRepository.saveSagaState(saga)

            persisted
        }

        // Start the creation saga asynchronously (outside the transaction)
        try {
            sagaOrchestrator.executeCreationSaga(savedOrder)
        } catch (e: Exception) {
            logger.error("Failed to start creation saga for order=$orderId", e)
            // Saga will be picked up by the recovery process
        }

        logger.info("Order created: orderId=$orderId, status=${savedOrder.status}")
        return savedOrder
    }

    // --- CompleteOrderUseCase ---

    override suspend fun complete(orderId: String, trackingNumber: String?): Order {
        logger.info("Completing order=$orderId")

        val order = findOrderOrThrow(orderId)

        if (!order.isCancellable && order.status != OrderStatus.FULFILLING) {
            throw OrderNotCompletableException(
                "Order $orderId cannot be completed from status ${order.status}",
                order.status
            )
        }

        val completedOrder = orderRepository.inTransaction {
            val updated = order.complete()
            val saved = orderRepository.save(updated)

            // Write completion event to outbox
            orderRepository.appendToOutbox(
                OutboxEntry(
                    eventId = UUID.randomUUID().toString(),
                    aggregateId = orderId,
                    aggregateType = "Order",
                    eventType = DomainEvent.ORDER_COMPLETED,
                    payload = orderId.toByteArray()
                )
            )

            saved
        }

        logger.info("Order completed: orderId=$orderId")
        return completedOrder
    }

    // --- CancelOrderUseCase ---

    override suspend fun cancel(orderId: String, reason: String, cancelledBy: String, refundRequested: Boolean): Order {
        logger.info("Cancelling order=$orderId, reason=$reason, cancelledBy=$cancelledBy")

        val order = findOrderOrThrow(orderId)

        if (!order.isCancellable) {
            if (order.status == OrderStatus.COMPENSATING) {
                throw CancellationAlreadyInProgressException(
                    "Order $orderId is already being compensated",
                    orderId
                )
            }
            throw OrderNotCancellableException(
                "Order $orderId cannot be cancelled from status ${order.status}",
                order.status
            )
        }

        // For PENDING orders, we can cancel directly without compensation
        if (order.status == OrderStatus.PENDING) {
            return orderRepository.inTransaction {
                val cancelled = order.cancel(reason)
                val saved = orderRepository.save(cancelled)

                orderRepository.appendToOutbox(
                    OutboxEntry(
                        eventId = UUID.randomUUID().toString(),
                        aggregateId = orderId,
                        aggregateType = "Order",
                        eventType = DomainEvent.ORDER_CANCELLED,
                        payload = reason.toByteArray()
                    )
                )

                saved
            }
        }

        // For orders with completed saga steps, start the cancellation saga
        val sagaState = orderRepository.findSagaByOrderId(orderId)
        val completedSteps = sagaState?.completedStepNames ?: emptyList()

        val cancelledOrder = orderRepository.inTransaction {
            val compensating = order.beginCompensation()
            orderRepository.save(compensating)
        }

        // Execute cancellation saga (outside the transaction)
        try {
            sagaOrchestrator.executeCancellationSaga(
                order = cancelledOrder,
                completedForwardSteps = completedSteps,
                reason = reason
            )
        } catch (e: Exception) {
            logger.error("Failed to start cancellation saga for order=$orderId", e)
        }

        return cancelledOrder
    }

    // --- ListOrdersUseCase ---

    override suspend fun list(
        customerId: String?,
        status: OrderStatus?,
        createdAfter: Instant?,
        createdBefore: Instant?,
        pageSize: Int,
        pageToken: String?,
        sortBy: SortField
    ): Page<Order> {
        require(pageSize in 1..100) { "Page size must be between 1 and 100, got $pageSize" }

        return when {
            customerId != null && status != null -> {
                // Filter by both customer and status: fetch by customer, then filter
                val page = orderRepository.findByCustomer(customerId, pageSize, pageToken, sortBy)
                val filtered = page.items.filter { it.status == status }
                Page(
                    items = filtered,
                    totalCount = filtered.size.toLong(),
                    cursor = page.cursor,
                    hasMore = page.hasMore
                )
            }
            customerId != null -> {
                orderRepository.findByCustomer(customerId, pageSize, pageToken, sortBy)
            }
            status != null -> {
                orderRepository.findByStatus(status, pageSize, pageToken)
            }
            else -> {
                // No filter: return all orders (should require customer in production)
                orderRepository.findByCustomer("", pageSize, pageToken, sortBy)
            }
        }
    }

    // --- GetOrderStatusUseCase ---

    override suspend fun getStatus(orderId: String, includeHistory: Boolean): OrderStatusDetail {
        val order = findOrderOrThrow(orderId)
        val saga = orderRepository.findSagaByOrderId(orderId)

        return OrderStatusDetail(
            orderId = order.orderId,
            status = order.status,
            currentSagaStep = saga?.currentStep?.stepName,
            completedSteps = saga?.completedStepNames ?: emptyList(),
            remainingSteps = saga?.remainingStepNames ?: emptyList(),
            compensationSteps = saga?.compensationStepNames ?: emptyList()
        )
    }

    // --- Helper methods ---

    private suspend fun findOrderOrThrow(orderId: String): Order {
        return orderRepository.findById(orderId)
            ?: throw OrderNotFoundException("Order not found: $orderId", orderId)
    }
}
