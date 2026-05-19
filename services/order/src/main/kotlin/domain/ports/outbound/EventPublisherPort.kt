package com.company.order.domain.ports.outbound

/**
 * Outbound port for publishing domain events.
 *
 * The primary publishing mechanism is through the Transactional Outbox:
 * events are first written to the outbox table within the same DB transaction
 * as the order mutation, then a relay process publishes them to Kafka.
 *
 * Direct publishing is reserved for infrastructure events that do not need
 * transactional consistency with order data (e.g., saga monitoring events).
 */
interface EventPublisherPort {

    /**
     * Publish outbox entries to the message broker and mark them as processed.
     * This is called by the outbox relay after reading entries from the database.
     *
     * @param entries The outbox entries to publish
     * @throws EventPublishException if publishing fails after retries
     */
    suspend fun publishFromOutbox(entries: List<OutboxEntry>)

    /**
     * Publish an event directly without the outbox pattern.
     * Use ONLY for infrastructure/monitoring events that do not require
     * transactional consistency with order data.
     *
     * @param event The event to publish
     * @throws EventPublishException if publishing fails
     */
    suspend fun publishDirect(event: DomainEvent)
}

/**
 * Domain event representation for the Order service.
 */
data class DomainEvent(
    val eventId: String,
    val eventType: String,
    val aggregateId: String,
    val aggregateType: String,
    val payload: ByteArray,
    val timestamp: java.time.Instant = java.time.Instant.now(),
    val traceParent: String? = null
) {
    companion object {
        // Event type constants
        const val ORDER_CREATED = "com.company.order.created"
        const val ORDER_RESERVED = "com.company.order.reserved"
        const val ORDER_PAID = "com.company.order.paid"
        const val ORDER_FULFILLING = "com.company.order.fulfilling"
        const val ORDER_COMPLETED = "com.company.order.completed"
        const val ORDER_CANCELLED = "com.company.order.cancelled"
        const val ORDER_FAILED = "com.company.order.failed"
        const val SAGA_STEP_COMPLETED = "com.company.order.saga-step-completed"
    }

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is DomainEvent) return false
        return eventId == other.eventId
    }

    override fun hashCode(): Int = eventId.hashCode()
}

class EventPublishException(message: String, cause: Throwable? = null) : Exception(message, cause)
