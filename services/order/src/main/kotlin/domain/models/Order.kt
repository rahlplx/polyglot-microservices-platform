package com.company.order.domain.models

import java.time.Instant

/**
 * Order aggregate root — the central domain entity.
 * Encapsulates order lifecycle, state machine transitions, and domain invariants.
 *
 * All state transitions are validated against the OrderStatus state machine.
 * Domain events are collected during mutations and cleared after persistence.
 *
 * Domain core has ZERO external dependencies.
 */
data class Order(
    val orderId: String,
    val customerId: String,
    val lines: List<OrderLine>,
    val total: Money,
    val status: OrderStatus,
    val shippingAddress: Address,
    val paymentId: String? = null,
    val reservationIds: List<String> = emptyList(),
    val createdAt: Instant,
    val updatedAt: Instant,
    val completedAt: Instant? = null,
    val cancelReason: String? = null,
    val idempotencyKey: String? = null
) {
    companion object {
        /**
         * Factory method to create a new order in PENDING state.
         * Validates all invariants before construction.
         */
        fun create(
            orderId: String,
            customerId: String,
            lines: List<OrderLine>,
            shippingAddress: Address,
            idempotencyKey: String? = null
        ): Order {
            require(orderId.isNotBlank()) { "Order ID must not be blank" }
            require(customerId.isNotBlank()) { "Customer ID must not be blank" }
            require(lines.isNotEmpty()) { "Order must have at least one line item" }
            require(lines.all { it.unitPrice.currencyCode == lines.first().unitPrice.currencyCode }) {
                "All line items must have the same currency"
            }

            val total = lines.fold(Money.zero(lines.first().unitPrice.currencyCode)) { acc, line ->
                acc + line.lineTotal
            }

            val now = Instant.now()
            return Order(
                orderId = orderId,
                customerId = customerId,
                lines = lines,
                total = total,
                status = OrderStatus.PENDING,
                shippingAddress = shippingAddress,
                createdAt = now,
                updatedAt = now,
                idempotencyKey = idempotencyKey
            )
        }
    }

    init {
        require(orderId.isNotBlank()) { "Order ID must not be blank" }
        require(customerId.isNotBlank()) { "Customer ID must not be blank" }
        require(lines.isNotEmpty()) { "Order must have at least one line item" }
    }

    // --- State transitions ---

    /**
     * Transition to RESERVED status after inventory has been reserved.
     */
    fun reserve(reservationIds: List<String>): Order {
        OrderStatus.requireTransition(status, OrderStatus.RESERVED)
        require(reservationIds.isNotEmpty()) { "Reservation IDs must not be empty when transitioning to RESERVED" }
        return copy(
            status = OrderStatus.RESERVED,
            reservationIds = reservationIds,
            updatedAt = Instant.now()
        )
    }

    /**
     * Transition to PAID status after payment has been authorized.
     */
    fun authorizePayment(paymentId: String): Order {
        OrderStatus.requireTransition(status, OrderStatus.PAID)
        require(paymentId.isNotBlank()) { "Payment ID must not be blank when transitioning to PAID" }
        return copy(
            status = OrderStatus.PAID,
            paymentId = paymentId,
            updatedAt = Instant.now()
        )
    }

    /**
     * Transition to FULFILLING status when order fulfillment begins.
     */
    fun beginFulfillment(): Order {
        OrderStatus.requireTransition(status, OrderStatus.FULFILLING)
        return copy(
            status = OrderStatus.FULFILLING,
            updatedAt = Instant.now()
        )
    }

    /**
     * Transition to COMPLETED status after delivery confirmation.
     */
    fun complete(): Order {
        OrderStatus.requireTransition(status, OrderStatus.COMPLETED)
        val now = Instant.now()
        return copy(
            status = OrderStatus.COMPLETED,
            completedAt = now,
            updatedAt = now
        )
    }

    /**
     * Transition to CANCELLED status. Can happen from PENDING directly,
     * or from COMPENSATING after all compensations are done.
     */
    fun cancel(reason: String): Order {
        OrderStatus.requireTransition(status, OrderStatus.CANCELLED)
        return copy(
            status = OrderStatus.CANCELLED,
            cancelReason = reason,
            updatedAt = Instant.now()
        )
    }

    /**
     * Transition to FAILED status when order creation fails before
     * any saga step completes, or when compensation fails.
     */
    fun fail(): Order {
        OrderStatus.requireTransition(status, OrderStatus.FAILED)
        return copy(
            status = OrderStatus.FAILED,
            updatedAt = Instant.now()
        )
    }

    /**
     * Transition to COMPENSATING status when saga compensation begins.
     * Used when a partially completed saga needs to roll back.
     */
    fun beginCompensation(): Order {
        OrderStatus.requireTransition(status, OrderStatus.COMPENSATING)
        return copy(
            status = OrderStatus.COMPENSATING,
            updatedAt = Instant.now()
        )
    }

    // --- Derived properties ---

    /** Whether this order is in a terminal state */
    val isTerminal: Boolean get() = status.isTerminal

    /** Whether this order can be cancelled */
    val isCancellable: Boolean get() = status.isCancellable

    /** Whether this order has an associated payment */
    val hasPayment: Boolean get() = paymentId != null

    /** Whether this order has inventory reservations */
    val hasReservations: Boolean get() = reservationIds.isNotEmpty()

    /** The currency code for this order */
    val currencyCode: String get() = total.currencyCode
}

/**
 * Address value object for shipping/billing.
 */
data class Address(
    val line1: String,
    val line2: String? = null,
    val city: String,
    val state: String,
    val postalCode: String,
    val countryCode: String
) {
    init {
        require(line1.isNotBlank()) { "Address line 1 must not be blank" }
        require(city.isNotBlank()) { "City must not be blank" }
        require(postalCode.isNotBlank()) { "Postal code must not be blank" }
        require(countryCode.length == 2) { "Country code must be ISO 3166-1 alpha-2 (2 characters)" }
    }
}

/**
 * Status change record for order history tracking.
 */
data class OrderStatusChange(
    val fromStatus: OrderStatus,
    val toStatus: OrderStatus,
    val changedAt: Instant,
    val reason: String? = null,
    val changedBy: String? = null
)

/**
 * Paginated result for order listing.
 */
data class Page<T>(
    val items: List<T>,
    val totalCount: Long,
    val cursor: String?,
    val hasMore: Boolean
)

/**
 * Sort field for order listing.
 */
enum class SortField {
    CREATED_AT_DESC,
    CREATED_AT_ASC,
    UPDATED_AT_DESC,
    TOTAL_DESC
}
