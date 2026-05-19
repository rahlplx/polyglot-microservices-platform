package com.company.order.domain.models

/**
 * A single line item within an order.
 * Immutable value object — quantity and pricing are set at creation time.
 *
 * Domain core has ZERO external dependencies.
 */
data class OrderLine(
    val productId: String,
    val productName: String,
    val quantity: Int,
    val unitPrice: Money,
    val lineTotal: Money
) {
    companion object {
        /**
         * Create an OrderLine with automatic line total calculation.
         * Line total = unit price × quantity.
         */
        fun create(
            productId: String,
            productName: String,
            quantity: Int,
            unitPrice: Money
        ): OrderLine {
            require(productId.isNotBlank()) { "Product ID must not be blank" }
            require(productName.isNotBlank()) { "Product name must not be blank" }
            require(quantity > 0) { "Quantity must be positive, got $quantity" }
            require(!unitPrice.isNegative) { "Unit price must not be negative: $unitPrice" }

            val lineTotal = unitPrice.multiply(quantity)
            return OrderLine(
                productId = productId,
                productName = productName,
                quantity = quantity,
                unitPrice = unitPrice,
                lineTotal = lineTotal
            )
        }
    }

    init {
        require(productId.isNotBlank()) { "Product ID must not be blank" }
        require(quantity > 0) { "Quantity must be positive" }
    }
}

/**
 * Request DTO for creating an order line (before product details are known).
 */
data class OrderLineRequest(
    val productId: String,
    val quantity: Int
) {
    init {
        require(productId.isNotBlank()) { "Product ID must not be blank" }
        require(quantity > 0) { "Quantity must be positive" }
    }
}
