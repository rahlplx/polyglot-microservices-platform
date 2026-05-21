package com.company.order.domain.services

import com.company.order.domain.models.Money
import com.company.order.domain.models.Order
import com.company.order.domain.models.OrderLine
import com.company.order.domain.models.OrderStatus
import com.company.order.domain.ports.outbound.DomainEvent
import com.company.order.domain.ports.outbound.EventPublisherPort
import com.company.order.domain.ports.outbound.OutboxEntry
import com.company.order.domain.ports.outbound.OrderRepositoryPort
import com.company.order.domain.saga.*
import org.slf4j.LoggerFactory
import java.util.UUID

/**
 * Saga orchestrator for the Order service.
 *
 * Implements choreography-based saga coordination with compensation actions.
 * The orchestrator tracks saga state, executes steps sequentially, and
 * triggers compensations when steps fail.
 *
 * Key responsibilities:
 * 1. Execute creation saga: RESERVE_INVENTORY → AUTHORIZE_PAYMENT → CONFIRM_ORDER
 * 2. Execute cancellation saga: reverse completed steps with compensations
 * 3. Handle step failures with retry logic
 * 4. Recover stuck sagas (RUNNING status for too long)
 *
 * Uses the Transactional Outbox pattern: all state changes and events
 * are written to the database in the same transaction.
 *
 * Domain core has ZERO external dependencies (only uses domain ports and models).
 */
class SagaOrchestrator(
    private val orderRepository: OrderRepositoryPort,
    private val eventPublisher: EventPublisherPort,
    private val catalogClient: CatalogClientPort,
    private val paymentClient: PaymentClientPort
) {
    private val logger = LoggerFactory.getLogger(SagaOrchestrator::class.java)

    // --- Creation Saga ---

    /**
     * Execute the order creation saga.
     * Steps: RESERVE_INVENTORY → AUTHORIZE_PAYMENT → CONFIRM_ORDER
     *
     * If any step fails, all previously completed steps are compensated
     * in reverse order, and the order is transitioned to FAILED or CANCELLED.
     */
    suspend fun executeCreationSaga(order: Order) {
        val saga = orderRepository.findSagaByOrderId(order.orderId)
            ?: throw IllegalStateException("No saga found for order ${order.orderId}")

        logger.info("Starting creation saga for order=${order.orderId}, sagaId=${saga.sagaId}")

        var currentSaga = saga
        var currentOrder = order

        try {
            // Step 1: RESERVE_INVENTORY
            currentSaga = currentSaga.startStep(SagaDefinition.STEP_RESERVE_INVENTORY)
            currentSaga = orderRepository.inTransaction {
                orderRepository.saveSagaState(currentSaga)
                currentSaga
            }

            val reservationResult = catalogClient.reserveInventory(
                ReservationRequest(
                    orderId = order.orderId,
                    items = order.lines.map {
                        ReservationItem(
                            productId = it.productId,
                            quantity = it.quantity
                        )
                    }
                )
            )

            currentOrder = currentOrder.reserve(reservationResult.reservationIds)
            currentSaga = currentSaga.completeStep(SagaDefinition.STEP_RESERVE_INVENTORY)

            orderRepository.inTransaction {
                orderRepository.save(currentOrder)
                orderRepository.saveSagaState(currentSaga)
                appendSagaStepEvent(currentOrder.orderId, SagaDefinition.STEP_RESERVE_INVENTORY)
            }

            logger.info("Creation saga step RESERVE_INVENTORY completed for order=${order.orderId}")

            // Step 2: AUTHORIZE_PAYMENT
            currentSaga = currentSaga.startStep(SagaDefinition.STEP_AUTHORIZE_PAYMENT)
            orderRepository.inTransaction {
                orderRepository.saveSagaState(currentSaga)
            }

            val paymentResult = paymentClient.authorizePayment(
                PaymentAuthorizationRequest(
                    orderId = order.orderId,
                    customerId = order.customerId,
                    amount = currentOrder.total,
                    paymentMethodId = order.idempotencyKey ?: "" // Using idempotency key slot
                )
            )

            currentOrder = currentOrder.authorizePayment(paymentResult.paymentId)
            currentSaga = currentSaga.completeStep(SagaDefinition.STEP_AUTHORIZE_PAYMENT)

            orderRepository.inTransaction {
                orderRepository.save(currentOrder)
                orderRepository.saveSagaState(currentSaga)
                appendSagaStepEvent(currentOrder.orderId, SagaDefinition.STEP_AUTHORIZE_PAYMENT)
            }

            logger.info("Creation saga step AUTHORIZE_PAYMENT completed for order=${order.orderId}")

            // Step 3: CONFIRM_ORDER - transition order through remaining states
            currentSaga = currentSaga.startStep(SagaDefinition.STEP_CONFIRM_ORDER)
            orderRepository.inTransaction {
                orderRepository.saveSagaState(currentSaga)
            }

            // Transition order to FULFILLING (skipping PAID since we're already at PAID from authorizePayment)
            currentOrder = currentOrder.beginFulfillment()
            currentSaga = currentSaga.completeStep(SagaDefinition.STEP_CONFIRM_ORDER)

            orderRepository.inTransaction {
                orderRepository.save(currentOrder)
                orderRepository.saveSagaState(currentSaga)
                appendSagaStepEvent(currentOrder.orderId, SagaDefinition.STEP_CONFIRM_ORDER)

                // Write order confirmed event to outbox
                orderRepository.appendToOutbox(
                    OutboxEntry(
                        eventId = UUID.randomUUID().toString(),
                        aggregateId = currentOrder.orderId,
                        aggregateType = "Order",
                        eventType = "com.company.order.confirmed",
                        payload = currentOrder.orderId.toByteArray()
                    )
                )
            }

            logger.info("Creation saga completed successfully for order=${order.orderId}")

        } catch (e: Exception) {
            logger.error("Creation saga failed for order=${order.orderId} at step=${currentSaga.currentStep?.stepName}", e)

            // Fail the current step and begin compensation
            val failedStep = currentSaga.currentStep?.stepName
            if (failedStep != null) {
                currentSaga = currentSaga.failStep(failedStep, e.message ?: "Unknown error")
            }

            // Execute compensations
            compensate(currentSaga, currentOrder, "Order creation failed: ${e.message}")
        }
    }

    // --- Cancellation Saga ---

    /**
     * Execute the cancellation saga for an order.
     * Compensates all completed forward saga steps in reverse order.
     */
    suspend fun executeCancellationSaga(
        order: Order,
        completedForwardSteps: List<String>,
        reason: String
    ) {
        val existingSaga = orderRepository.findSagaByOrderId(order.orderId)

        // Create cancellation saga with adaptive steps based on completed forward steps
        val cancellationSteps = SagaDefinition.orderCancellationSaga(
            orderId = order.orderId,
            completedForwardSteps = completedForwardSteps,
            paymentId = order.paymentId,
            reservationIds = order.reservationIds,
            paymentCaptured = order.status == OrderStatus.PAID || order.status == OrderStatus.FULFILLING
        )

        val cancellationSaga = SagaInstance.create(
            sagaId = UUID.randomUUID().toString(),
            orderId = order.orderId,
            sagaType = SagaType.ORDER_CANCELLATION,
            steps = cancellationSteps
        )

        var currentSaga = orderRepository.inTransaction {
            orderRepository.saveSagaState(cancellationSaga)
            cancellationSaga
        }

        logger.info("Starting cancellation saga for order=${order.orderId}, steps=${cancellationSteps.map { it.stepName }}")

        var currentOrder = order

        try {
            for (step in cancellationSteps) {
                currentSaga = currentSaga.startStep(step.stepName)
                orderRepository.inTransaction {
                    orderRepository.saveSagaState(currentSaga)
                }

                executeCancellationStep(step.stepName, currentOrder, reason)

                currentSaga = currentSaga.completeStep(step.stepName)
                orderRepository.inTransaction {
                    orderRepository.saveSagaState(currentSaga)
                }

                logger.info("Cancellation saga step ${step.stepName} completed for order=${order.orderId}")
            }

            // All compensation steps completed, transition order to CANCELLED
            currentOrder = orderRepository.inTransaction {
                val cancelled = currentOrder.cancel(reason)
                val saved = orderRepository.save(cancelled)

                orderRepository.appendToOutbox(
                    OutboxEntry(
                        eventId = UUID.randomUUID().toString(),
                        aggregateId = order.orderId,
                        aggregateType = "Order",
                        eventType = DomainEvent.ORDER_CANCELLED,
                        payload = reason.toByteArray()
                    )
                )

                saved
            }

            logger.info("Cancellation saga completed for order=${order.orderId}")

        } catch (e: Exception) {
            logger.error("Cancellation saga failed for order=${order.orderId}", e)

            val failedStep = currentSaga.currentStep?.stepName
            if (failedStep != null) {
                currentSaga = currentSaga.failStep(failedStep, e.message ?: "Unknown error")
                orderRepository.inTransaction {
                    orderRepository.saveSagaState(currentSaga)
                }
            }

            // Transition order to FAILED if compensation cannot complete
            orderRepository.inTransaction {
                val failed = currentOrder.fail()
                orderRepository.save(failed)

                orderRepository.appendToOutbox(
                    OutboxEntry(
                        eventId = UUID.randomUUID().toString(),
                        aggregateId = order.orderId,
                        aggregateType = "Order",
                        eventType = DomainEvent.ORDER_FAILED,
                        payload = (e.message ?: "Unknown error").toByteArray()
                    )
                )
            }
        }
    }

    // --- Saga Recovery ---

    /**
     * Recover stuck sagas that have been in RUNNING status for too long.
     * Called periodically by the infrastructure layer.
     */
    suspend fun recoverStuckSagas(timeoutMinutes: Long = 10) {
        val runningSagas = orderRepository.findSagasByStatus(SagaStatus.RUNNING)
        val now = java.time.Instant.now()

        for (saga in runningSagas) {
            val elapsed = java.time.Duration.between(saga.startedAt, now).toMinutes()
            if (elapsed > timeoutMinutes) {
                logger.warn("Recovering stuck saga: sagaId=${saga.sagaId}, orderId=${saga.orderId}, elapsed=${elapsed}min")

                val order = orderRepository.findById(saga.orderId) ?: continue

                when (saga.sagaType) {
                    SagaType.ORDER_CREATION -> {
                        // Retry the creation saga
                        try {
                            executeCreationSaga(order)
                        } catch (e: Exception) {
                            logger.error("Failed to recover creation saga for order=${order.orderId}", e)
                        }
                    }
                    SagaType.ORDER_CANCELLATION -> {
                        // Retry the cancellation saga
                        try {
                            executeCancellationSaga(
                                order = order,
                                completedForwardSteps = saga.completedStepNames,
                                reason = "Cancellation saga recovery"
                            )
                        } catch (e: Exception) {
                            logger.error("Failed to recover cancellation saga for order=${order.orderId}", e)
                        }
                    }
                }
            }
        }

        // Also recover sagas stuck in COMPENSATING
        val compensatingSagas = orderRepository.findSagasByStatus(SagaStatus.COMPENSATING)
        for (saga in compensatingSagas) {
            logger.warn("Recovering stuck compensating saga: sagaId=${saga.sagaId}, orderId=${saga.orderId}")
            val order = orderRepository.findById(saga.orderId) ?: continue
            compensate(saga, order, "Saga recovery: compensation timeout")
        }
    }

    // --- Private Helpers ---

    private suspend fun compensate(saga: SagaInstance, order: Order, reason: String) {
        var currentSaga = saga.beginCompensation()
        currentSaga = orderRepository.inTransaction {
            orderRepository.saveSagaState(currentSaga)
            currentSaga
        }

        val stepsToCompensate = currentSaga.stepsNeedingCompensation()

        for (step in stepsToCompensate) {
            try {
                logger.info("Compensating step ${step.stepName} for order=${order.orderId}")

                step.compensationAction?.let { action ->
                    executeCompensationAction(action, order, reason)
                }

                currentSaga = currentSaga.completeCompensation(step.stepName)
                orderRepository.inTransaction {
                    orderRepository.saveSagaState(currentSaga)
                }

            } catch (e: Exception) {
                logger.error("Compensation failed for step ${step.stepName} on order=${order.orderId}", e)
                // Continue with other compensations (best-effort)
            }
        }

        // Transition order to CANCELLED or FAILED based on compensation results
        val finalOrder = if (order.status == OrderStatus.PENDING) {
            order.fail()
        } else {
            order.cancel(reason)
        }

        orderRepository.inTransaction {
            orderRepository.save(finalOrder)

            orderRepository.appendToOutbox(
                OutboxEntry(
                    eventId = UUID.randomUUID().toString(),
                    aggregateId = order.orderId,
                    aggregateType = "Order",
                    eventType = if (finalOrder.status == OrderStatus.CANCELLED)
                        DomainEvent.ORDER_CANCELLED else DomainEvent.ORDER_FAILED,
                    payload = reason.toByteArray()
                )
            )
        }
    }

    private suspend fun executeCancellationStep(stepName: String, order: Order, reason: String) {
        when (stepName) {
            SagaDefinition.STEP_RELEASE_INVENTORY -> {
                if (order.reservationIds.isNotEmpty()) {
                    catalogClient.releaseInventory(
                        ReleaseInventoryRequest(reservationIds = order.reservationIds)
                    )
                }
            }
            SagaDefinition.STEP_VOID_AUTHORIZATION -> {
                order.paymentId?.let { pid ->
                    paymentClient.voidAuthorization(
                        VoidAuthorizationRequest(
                            paymentId = pid,
                            reason = reason
                        )
                    )
                }
            }
            SagaDefinition.STEP_REFUND_PAYMENT -> {
                order.paymentId?.let { pid ->
                    paymentClient.refundPayment(
                        RefundPaymentRequest(
                            paymentId = pid,
                            amount = order.total,
                            reason = reason
                        )
                    )
                }
            }
            SagaDefinition.STEP_NOTIFY_CANCELLATION -> {
                // Best-effort notification - don't fail the saga if notification fails
                try {
                    // Notification is typically handled via events, this is a fallback
                    logger.info("Cancellation notification for order=${order.orderId}")
                } catch (e: Exception) {
                    logger.warn("Cancellation notification failed for order=${order.orderId}", e)
                }
            }
        }
    }

    private suspend fun executeCompensationAction(action: CompensationAction, order: Order, reason: String) {
        when (action.actionType) {
            CompensationType.RELEASE_INVENTORY -> {
                val reservationIds = action.parameters["reservation_ids"]?.split(",") ?: order.reservationIds
                if (reservationIds.isNotEmpty()) {
                    catalogClient.releaseInventory(
                        ReleaseInventoryRequest(reservationIds = reservationIds)
                    )
                }
            }
            CompensationType.VOID_AUTHORIZATION -> {
                val paymentId = action.parameters["payment_id"] ?: order.paymentId
                if (paymentId != null) {
                    paymentClient.voidAuthorization(
                        VoidAuthorizationRequest(
                            paymentId = paymentId,
                            reason = reason
                        )
                    )
                }
            }
            CompensationType.REFUND_PAYMENT -> {
                val paymentId = action.parameters["payment_id"] ?: order.paymentId
                if (paymentId != null) {
                    paymentClient.refundPayment(
                        RefundPaymentRequest(
                            paymentId = paymentId,
                            amount = order.total,
                            reason = reason
                        )
                    )
                }
            }
            CompensationType.CANCEL_INVENTORY_CONFIRMATION -> {
                // No-op: inventory confirmation is handled by the catalog service event consumer
                logger.info("Skipping inventory confirmation cancellation for order=${order.orderId}")
            }
            CompensationType.NOTIFY_CANCELLATION -> {
                logger.info("Compensation notification for order=${order.orderId}")
            }
        }
    }

    private suspend fun appendSagaStepEvent(orderId: String, stepName: String) {
        orderRepository.appendToOutbox(
            OutboxEntry(
                eventId = UUID.randomUUID().toString(),
                aggregateId = orderId,
                aggregateType = "Order",
                eventType = DomainEvent.SAGA_STEP_COMPLETED,
                payload = stepName.toByteArray()
            )
        )
    }
}

// --- Client port interfaces for external service communication ---
// These are defined here in the domain layer as ports, implemented in the adapter layer.

/**
 * Client port for communicating with the Catalog service.
 */
interface CatalogClientPort {
    suspend fun reserveInventory(request: ReservationRequest): ReservationResponse
    suspend fun releaseInventory(request: ReleaseInventoryRequest): ReleaseInventoryResponse
    suspend fun confirmReservation(reservationIds: List<String>): ConfirmReservationResponse
}

data class ReservationRequest(
    val orderId: String,
    val items: List<ReservationItem>
)

data class ReservationItem(
    val productId: String,
    val quantity: Int
)

data class ReservationResponse(
    val reservationIds: List<String>,
    val reservedItems: List<ReservedItem>
)

data class ReservedItem(
    val productId: String,
    val productName: String,
    val unitPrice: Money,
    val quantity: Int
)

data class ReleaseInventoryRequest(
    val reservationIds: List<String>
)

data class ReleaseInventoryResponse(
    val released: Boolean
)

data class ConfirmReservationResponse(
    val confirmed: Boolean
)

/**
 * Client port for communicating with the Payment service.
 */
interface PaymentClientPort {
    suspend fun authorizePayment(request: PaymentAuthorizationRequest): PaymentAuthorizationResponse
    suspend fun capturePayment(paymentId: String, amount: Money?): CapturePaymentResponse
    suspend fun refundPayment(request: RefundPaymentRequest): RefundPaymentResponse
    suspend fun voidAuthorization(request: VoidAuthorizationRequest): VoidAuthorizationResponse
    suspend fun getPaymentStatus(paymentId: String): PaymentStatusResponse
}

data class PaymentAuthorizationRequest(
    val orderId: String,
    val customerId: String,
    val amount: Money,
    val paymentMethodId: String
)

data class PaymentAuthorizationResponse(
    val paymentId: String,
    val authorized: Boolean,
    val authorizationCode: String? = null
)

data class CapturePaymentResponse(
    val captured: Boolean,
    val capturedAmount: Money
)

data class RefundPaymentRequest(
    val paymentId: String,
    val amount: Money,
    val reason: String
)

data class RefundPaymentResponse(
    val refundId: String,
    val refunded: Boolean,
    val refundedAmount: Money
)

data class VoidAuthorizationRequest(
    val paymentId: String,
    val reason: String
)

data class VoidAuthorizationResponse(
    val voided: Boolean
)

data class PaymentStatusResponse(
    val paymentId: String,
    val status: String,
    val authorizedAmount: Money? = null,
    val capturedAmount: Money? = null
)
