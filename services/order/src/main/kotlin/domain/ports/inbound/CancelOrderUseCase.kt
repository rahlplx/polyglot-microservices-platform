package com.company.order.domain.ports.inbound

import com.company.order.domain.models.Order

/**
 * Inbound port for cancelling an order.
 * Triggers the cancellation saga which executes compensating actions
 * for any completed saga steps.
 */
interface CancelOrderUseCase {

    /**
     * Cancel an existing order, executing compensation as needed.
     *
     * The cancellation logic varies by order state:
     * - PENDING: No compensation needed, direct cancel
     * - RESERVED: Release inventory reservations
     * - PAID: Release inventory + void/refund payment
     * - FULFILLING: Release inventory + refund payment (if captured)
     * - COMPENSATING: Already compensating, idempotent
     *
     * @param orderId The order to cancel
     * @param reason The reason for cancellation
     * @param cancelledBy Who initiated the cancellation
     * @param refundRequested Whether a refund is requested
     * @return The cancelled order
     * @throws OrderNotFoundException if the order does not exist
     * @throws OrderNotCancellableException if the order is not in a cancellable state
     * @throws CancellationAlreadyInProgressException if cancellation is already in progress
     */
    suspend fun cancel(
        orderId: String,
        reason: String,
        cancelledBy: String,
        refundRequested: Boolean = true
    ): Order
}

class OrderNotFoundException(message: String, val orderId: String) : Exception(message)
class OrderNotCancellableException(message: String, val currentStatus: com.company.order.domain.models.OrderStatus) :
    Exception(message)

class CancellationAlreadyInProgressException(message: String, val orderId: String) : Exception(message)
