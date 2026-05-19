package com.company.order.domain.ports.inbound

import com.company.order.domain.models.Order
import com.company.order.domain.models.OrderStatus
import com.company.order.domain.models.Page
import com.company.order.domain.models.SortField

/**
 * Inbound port for listing orders with filtering and pagination.
 * Supports filtering by customer, status, date range, and sorting.
 */
interface ListOrdersUseCase {

    /**
     * List orders matching the given filter criteria.
     *
     * @param customerId Filter by customer ID (optional)
     * @param status Filter by order status (optional)
     * @param createdAfter Filter orders created after this timestamp (optional)
     * @param createdBefore Filter orders created before this timestamp (optional)
     * @param pageSize Maximum number of results per page
     * @param pageToken Opaque cursor for pagination
     * @param sortBy Sort ordering
     * @return Paginated list of orders
     * @throws InvalidQueryException if the query parameters are invalid
     * @throws PageTokenExpiredException if the page token has expired
     */
    suspend fun list(
        customerId: String? = null,
        status: OrderStatus? = null,
        createdAfter: java.time.Instant? = null,
        createdBefore: java.time.Instant? = null,
        pageSize: Int = 20,
        pageToken: String? = null,
        sortBy: SortField = SortField.CREATED_AT_DESC
    ): Page<Order>
}

class InvalidQueryException(message: String) : Exception(message)
class PageTokenExpiredException(message: String, val token: String) : Exception(message)
