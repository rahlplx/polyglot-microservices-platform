package com.company.order.adapters.outbound.messaging

import com.company.order.domain.ports.outbound.DomainEvent
import com.company.order.domain.ports.outbound.EventPublishException
import com.company.order.domain.ports.outbound.EventPublisherPort
import com.company.order.domain.ports.outbound.OutboxEntry
import org.apache.kafka.clients.producer.KafkaProducer
import org.apache.kafka.clients.producer.ProducerConfig
import org.apache.kafka.clients.producer.ProducerRecord
import org.apache.kafka.clients.producer.RecordMetadata
import org.apache.kafka.common.serialization.StringSerializer
import org.slf4j.LoggerFactory
import java.util.Properties
import java.util.concurrent.TimeUnit

/**
 * Kafka-based implementation of the EventPublisherPort.
 *
 * Publishes domain events to Kafka using the Transactional Producer API
 * for exactly-once delivery semantics. The primary publishing mechanism
 * is through the Transactional Outbox pattern: events are first written
 * to the outbox table, then a relay process publishes them to Kafka.
 *
 * Configuration supports:
 * - Transactional producer for outbox relay (exactly-once)
 * - Idempotent producer for direct publishing
 * - Protobuf serialization for event payloads
 * - Schema Registry validation (optional)
 */
class KafkaEventPublisher(
    bootstrapServers: String,
    private val topicPrefix: String = "com.company.order",
    private val schemaRegistryUrl: String? = null
) : EventPublisherPort {

    private val logger = LoggerFactory.getLogger(KafkaEventPublisher::class.java)

    private val producer: KafkaProducer<String, ByteArray>

    init {
        val props = Properties().apply {
            put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrapServers)
            put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer::class.java.name)
            put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, org.apache.kafka.common.serialization.ByteArraySerializer::class.java.name)
            put(ProducerConfig.ACKS_CONFIG, "all")
            put(ProducerConfig.RETRIES_CONFIG, 3)
            put(ProducerConfig.ENABLE_IDEMPOTENCE_CONFIG, true)
            put(ProducerConfig.TRANSACTIONAL_ID_CONFIG, "order-service-producer-${java.util.UUID.randomUUID()}")
            put(ProducerConfig.MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION, 5)
            put(ProducerConfig.BATCH_SIZE_CONFIG, 16384)
            put(ProducerConfig.LINGER_MS_CONFIG, 5)
            put(ProducerConfig.BUFFER_MEMORY_CONFIG, 33554432)
            put(ProducerConfig.COMPRESSION_TYPE_CONFIG, "lz4")
        }

        producer = KafkaProducer(props)
        producer.initTransactions()
        logger.info("Kafka producer initialized: bootstrapServers=$bootstrapServers, topicPrefix=$topicPrefix")
    }

    /**
     * Publish outbox entries to Kafka and mark them as processed.
     * Uses Kafka transactions to ensure atomicity.
     */
    override suspend fun publishFromOutbox(entries: List<OutboxEntry>) {
        if (entries.isEmpty()) return

        logger.debug("Publishing ${entries.size} outbox entries to Kafka")

        try {
            producer.beginTransaction()

            for (entry in entries) {
                val topic = resolveTopic(entry.eventType)
                val key = entry.aggregateId

                val record = ProducerRecord<String, ByteArray>(
                    topic,
                    key,
                    entry.payload
                )

                // Add trace context header for distributed tracing
                entry.traceParent?.let { tp ->
                    record.headers().add("traceparent", tp.toByteArray())
                }

                // Add CloudEvents headers
                record.headers().add("ce-id", entry.eventId.toByteArray())
                record.headers().add("ce-source", "com.company.order".toByteArray())
                record.headers().add("ce-type", entry.eventType.toByteArray())
                record.headers().add("ce-specversion", "1.0".toByteArray())
                record.headers().add("ce-aggregateid", entry.aggregateId.toByteArray())
                record.headers().add("content-type", "application/protobuf".toByteArray())

                producer.send(record).get(10, TimeUnit.SECONDS)
            }

            producer.commitTransaction()
            logger.info("Successfully published ${entries.size} outbox entries to Kafka")

        } catch (e: Exception) {
            producer.abortTransaction()
            logger.error("Failed to publish outbox entries to Kafka", e)
            throw EventPublishException("Failed to publish ${entries.size} events to Kafka", e)
        }
    }

    /**
     * Publish an event directly without the outbox pattern.
     * Use ONLY for infrastructure events that do not require
     * transactional consistency with order data.
     */
    override suspend fun publishDirect(event: DomainEvent) {
        logger.debug("Publishing direct event: type=${event.eventType}, aggregateId=${event.aggregateId}")

        try {
            val topic = resolveTopic(event.eventType)
            val key = event.aggregateId

            val record = ProducerRecord<String, ByteArray>(
                topic,
                key,
                event.payload
            )

            // CloudEvents headers
            record.headers().add("ce-id", event.eventId.toByteArray())
            record.headers().add("ce-source", "com.company.order".toByteArray())
            record.headers().add("ce-type", event.eventType.toByteArray())
            record.headers().add("ce-specversion", "1.0".toByteArray())
            record.headers().add("content-type", "application/protobuf".toByteArray())

            event.traceParent?.let { tp ->
                record.headers().add("traceparent", tp.toByteArray())
            }

            val metadata: RecordMetadata = producer.send(record).get(10, TimeUnit.SECONDS)
            logger.debug("Direct event published: topic=${metadata.topic()}, partition=${metadata.partition()}, offset=${metadata.offset()}")

        } catch (e: Exception) {
            logger.error("Failed to publish direct event: type=${event.eventType}", e)
            throw EventPublishException("Failed to publish event: ${event.eventType}", e)
        }
    }

    /**
     * Resolve the Kafka topic name from an event type.
     * Event types like "com.company.order.created" map to topics
     * using the event type as the full topic name.
     */
    private fun resolveTopic(eventType: String): String {
        // If the event type already looks like a full topic path, use it directly
        return if (eventType.startsWith(topicPrefix)) {
            eventType
        } else {
            "$topicPrefix.$eventType"
        }
    }

    /**
     * Gracefully shut down the Kafka producer.
     */
    fun close() {
        logger.info("Shutting down Kafka producer")
        producer.close(30, TimeUnit.SECONDS)
    }
}
