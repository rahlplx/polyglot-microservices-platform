package com.company.order.domain.ports.inbound

import com.company.order.domain.models.Order
import com.company.order.domain.models.OrderStatusChange

/**
 * Inbound port for getting order status and saga state.
 * Provides detailed information about the order's current state,
 * including saga execution progress.
 */
interface GetOrderStatusUseCase {

    /**
     * Get the current status of an order, optionally including
     * full status change history and saga state.
     *
     * @param orderId The order to query
     * @param includeHistory Whether to include the full status change timeline
     * @return The order status details
     * @throws OrderNotFoundException if the order does not exist
     */
    suspend fun getStatus(orderId: String, includeHistory: Boolean = false): OrderStatusDetail
}

/**
 * Detailed order status including saga state information.
 */
data class OrderStatusDetail(
    val orderId: String,
    val status: OrderStatus,
    val currentSagaStep: String? = null,
    val completedSteps: List<String> = emptyList(),
    val remainingSteps: List<String> = emptyList(),
    val compensationSteps: List<String> = emptyList(),
    val history: List<OrderStatusChange> = emptyList()
)
