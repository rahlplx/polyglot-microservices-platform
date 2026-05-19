package com.company.order.domain.ports.outbound

import com.company.order.domain.models.Order
import com.company.order.domain.models.OrderStatus
import com.company.order.domain.models.Page
import com.company.order.domain.models.SortField
import com.company.order.domain.saga.SagaInstance
import java.time.Instant

/**
 * Outbound port for order persistence.
 * Manages orders, line items, saga state, and the transactional outbox.
 *
 * All mutations must be performed within a transaction to ensure
 * consistency between order data and outbox events.
 */
interface OrderRepositoryPort {

    // --- Order CRUD ---

    /**
     * Persist an order with all line items.
     * Returns the persisted order with any generated fields populated.
     */
    suspend fun save(order: Order): Order

    /**
     * Find an order by its ID, including all line items and related data.
     * Returns null if not found.
     */
    suspend fun findById(orderId: String): Order?

    /**
     * Find orders for a specific customer with pagination.
     */
    suspend fun findByCustomer(
        customerId: String,
        pageSize: Int = 20,
        cursor: String? = null,
        sortBy: SortField = SortField.CREATED_AT_DESC
    ): Page<Order>

    /**
     * Find orders in a specific status (for saga recovery and processing).
     */
    suspend fun findByStatus(
        status: OrderStatus,
        pageSize: Int = 100,
        cursor: String? = null
    ): Page<Order>

    /**
     * Find an order by its idempotency key.
     * Used for duplicate detection.
     */
    suspend fun findByIdempotencyKey(idempotencyKey: String): Order?

    /**
     * Check if an order exists with the given idempotency key.
     */
    suspend fun existsByIdempotencyKey(idempotencyKey: String): Boolean

    // --- Saga State ---

    /**
     * Persist saga execution state for recovery and tracking.
     */
    suspend fun saveSagaState(saga: SagaInstance): SagaInstance

    /**
     * Retrieve saga state for a specific order.
     */
    suspend fun findSagaByOrderId(orderId: String): SagaInstance?

    /**
     * Find all sagas in a given status (for recovery processing).
     */
    suspend fun findSagasByStatus(status: com.company.order.domain.saga.SagaStatus): List<SagaInstance>

    // --- Transactional Outbox ---

    /**
     * Append an event to the transactional outbox.
     * MUST be called within the same transaction as the order mutation
     * to guarantee consistency.
     */
    suspend fun appendToOutbox(event: OutboxEntry)

    /**
     * Read unprocessed outbox entries for the relay.
     * Returns entries ordered by creation time (FIFO).
     */
    suspend fun readOutbox(limit: Int = 100): List<OutboxEntry>

    /**
     * Mark outbox entries as published after successful Kafka delivery.
     */
    suspend fun markOutboxProcessed(ids: List<String>)

    // --- Transaction Management ---

    /**
     * Execute a block within a database transaction.
     * All repository operations within the block are atomic.
     */
    suspend fun <T> inTransaction(block: suspend () -> T): T
}

/**
 * Outbox entry for the Transactional Outbox pattern.
 * Written to the same database as order data to ensure consistency.
 */
data class OutboxEntry(
    val eventId: String,
    val aggregateId: String,
    val aggregateType: String,
    val eventType: String,
    val payload: ByteArray,
    val createdAt: Instant = Instant.now(),
    val published: Boolean = false,
    val publishedAt: Instant? = null,
    val traceParent: String? = null
) {
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is OutboxEntry) return false
        return eventId == other.eventId
    }

    override fun hashCode(): Int = eventId.hashCode()
}
