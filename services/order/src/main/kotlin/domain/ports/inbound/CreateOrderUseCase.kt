package com.company.order.domain.ports.inbound

import com.company.order.domain.models.Order
import com.company.order.domain.models.Page
import com.company.order.domain.models.SortField
import com.company.order.domain.models.OrderStatus

/**
 * Inbound port for creating a new order.
 * Initiates the order creation saga which reserves inventory and authorizes payment.
 */
interface CreateOrderUseCase {

    /**
     * Create a new order and start the creation saga.
     *
     * @param customerId The customer placing the order
     * @param lines The line items to order
     * @param shippingAddress Where to ship the order
     * @param paymentMethodId The payment method to charge
     * @param idempotencyKey Optional key for duplicate submission protection
     * @return The created order in PENDING status
     * @throws InsufficientStockException if inventory cannot be reserved
     * @throws PaymentMethodInvalidException if payment method is rejected
     * @throws DuplicateOrderException if idempotency key matches an existing order
     */
    suspend fun create(
        customerId: String,
        lines: List<LineItemInput>,
        shippingAddress: AddressInput,
        paymentMethodId: String,
        idempotencyKey: String? = null
    ): Order
}

/** Input DTO for a line item during order creation */
data class LineItemInput(
    val productId: String,
    val quantity: Int
)

/** Input DTO for an address during order creation */
data class AddressInput(
    val line1: String,
    val line2: String? = null,
    val city: String,
    val state: String,
    val postalCode: String,
    val countryCode: String
)

// Domain exceptions (no external dependencies)
class InsufficientStockException(message: String, val productId: String) : Exception(message)
class ProductNotFoundException(message: String, val productId: String) : Exception(message)
class PaymentMethodInvalidException(message: String, val paymentMethodId: String) : Exception(message)
class DuplicateOrderException(message: String, val existingOrderId: String) : Exception(message)
class ShippingAddressValidationException(message: String) : Exception(message)
