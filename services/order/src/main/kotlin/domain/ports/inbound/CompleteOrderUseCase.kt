package com.company.order.domain.ports.inbound

import com.company.order.domain.models.Order

/**
 * Inbound port for completing an order after fulfillment.
 * Validates that the order is in a completable state and all payments are captured.
 */
interface CompleteOrderUseCase {

    /**
     * Mark an order as completed after delivery confirmation.
     *
     * @param orderId The order to complete
     * @param trackingNumber Optional tracking number for the shipment
     * @return The completed order
     * @throws OrderNotFoundException if the order does not exist
     * @throws OrderNotCompletableException if the order is not in a completable state
     * @throws PaymentNotCapturedException if payment has not been fully captured
     */
    suspend fun complete(
        orderId: String,
        trackingNumber: String? = null
    ): Order
}

class OrderNotCompletableException(message: String, val currentStatus: com.company.order.domain.models.OrderStatus) :
    Exception(message)

class PaymentNotCapturedException(message: String, val paymentId: String) : Exception(message)
