package com.company.order.adapters.outbound.outbox

import com.company.order.domain.ports.outbound.DomainEvent
import com.company.order.domain.ports.outbound.EventPublisherPort
import com.company.order.domain.ports.outbound.OutboxEntry
import com.company.order.domain.ports.outbound.OrderRepositoryPort
import org.slf4j.LoggerFactory
import java.time.Instant
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit

/**
 * Transactional Outbox writer and relay.
 *
 * The OutboxWriter serves two purposes:
 * 1. Writing events to the outbox table within the same transaction as
 *    order data mutations (handled by OrderRepositoryPort.appendToOutbox)
 * 2. Relaying outbox entries to Kafka via a scheduled polling task
 *
 * The relay runs on a configurable interval (default: 100ms active,
 * 500ms quiet) and reads unprocessed outbox entries, publishes them
 * to Kafka, and marks them as processed.
 *
 * This implementation ensures that the database state and the event
 * stream are always consistent: events are written to the same
 * transaction as the order data, and the relay guarantees at-least-once
 * delivery to Kafka.
 */
class OutboxWriter(
    private val orderRepository: OrderRepositoryPort,
    private val eventPublisher: EventPublisherPort,
    private val relayIntervalMs: Long = 100,
    private val quietIntervalMs: Long = 500,
    private val batchSize: Int = 100
) {
    private val logger = LoggerFactory.getLogger(OutboxWriter::class.java)

    private val scheduler: ScheduledExecutorService = Executors.newSingleThreadScheduledExecutor { r ->
        Thread(r, "outbox-relay").apply { isDaemon = true }
    }

    @Volatile
    private var running = false

    @Volatile
    private var lastEventTime: Instant = Instant.EPOCH

    /**
     * Start the outbox relay process.
     * Polls the outbox table at the configured interval and publishes
     * unprocessed entries to Kafka.
     */
    fun start() {
        if (running) {
            logger.warn("Outbox relay is already running")
            return
        }

        running = true
        logger.info("Starting outbox relay: intervalMs=$relayIntervalMs, batchSize=$batchSize")

        scheduler.scheduleWithFixedDelay({
            try {
                relay()
            } catch (e: Exception) {
                logger.error("Outbox relay error", e)
            }
        }, 0, relayIntervalMs, TimeUnit.MILLISECONDS)
    }

    /**
     * Stop the outbox relay process gracefully.
     */
    fun stop() {
        logger.info("Stopping outbox relay")
        running = false
        scheduler.shutdown()
        if (!scheduler.awaitTermination(30, TimeUnit.SECONDS)) {
            scheduler.shutdownNow()
        }
        logger.info("Outbox relay stopped")
    }

    /**
     * Execute a single relay cycle: read outbox entries, publish to Kafka,
     * mark as processed.
     */
    private fun relay() {
        val entries = kotlinx.coroutines.runBlocking {
            orderRepository.readOutbox(batchSize)
        }

        if (entries.isEmpty()) {
            return
        }

        logger.debug("Outbox relay: processing ${entries.size} entries")
        lastEventTime = Instant.now()

        try {
            kotlinx.coroutines.runBlocking {
                eventPublisher.publishFromOutbox(entries)
            }

            // Mark entries as processed after successful publication
            val ids = entries.map { it.eventId }
            kotlinx.coroutines.runBlocking {
                orderRepository.markOutboxProcessed(ids)
            }

            logger.debug("Outbox relay: published and marked ${entries.size} entries")

        } catch (e: Exception) {
            logger.error("Outbox relay: failed to publish ${entries.size} entries", e)
            // Entries remain unprocessed and will be retried in the next cycle
        }
    }

    /**
     * Get the count of unprocessed outbox entries (for monitoring).
     */
    suspend fun getUnprocessedCount(): Long = orderRepository.readOutbox(0).size.toLong()

    /**
     * Get metrics about the outbox relay.
     */
    fun getMetrics(): OutboxMetrics = OutboxMetrics(
        running = running,
        lastEventTime = lastEventTime,
        relayIntervalMs = relayIntervalMs
    )
}

/**
 * Metrics for the outbox relay.
 */
data class OutboxMetrics(
    val running: Boolean,
    val lastEventTime: Instant,
    val relayIntervalMs: Long
)
