package com.company.order.domain.ports.outbound

/**
 * Outbound port for the Transactional Outbox writer.
 *
 * Responsible for writing events to the outbox table within the same
 * database transaction as the order data mutation. This guarantees
 * that the database state and the event stream are always consistent.
 *
 * The outbox writer is used by the domain services to record domain
 * events that should be published to Kafka. A separate relay process
 * reads the outbox and publishes the events asynchronously.
 */
interface OutboxRepositoryPort {

    /**
     * Append an event to the outbox table.
     * MUST be called within the same transaction as the order mutation.
     *
     * @param entry The outbox entry to persist
     */
    suspend fun append(entry: OutboxEntry)

    /**
     * Append multiple events to the outbox in a single batch.
     * More efficient than individual appends for saga step events.
     *
     * @param entries The outbox entries to persist
     */
    suspend fun appendBatch(entries: List<OutboxEntry>)

    /**
     * Read unprocessed outbox entries ordered by creation time.
     * Called by the outbox relay process.
     *
     * @param limit Maximum number of entries to return
     * @return List of unprocessed outbox entries, ordered FIFO
     */
    suspend fun readUnprocessed(limit: Int = 100): List<OutboxEntry>

    /**
     * Mark outbox entries as published after successful delivery.
     *
     * @param ids The IDs of the entries to mark as published
     */
    suspend fun markProcessed(ids: List<String>)

    /**
     * Count unprocessed entries (for monitoring).
     */
    suspend fun countUnprocessed(): Long
}
