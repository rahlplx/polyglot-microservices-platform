package com.company.order.infrastructure.config

import com.sksamuel.hoplite.ConfigLoaderBuilder
import com.sksamuel.hoplite.addResourceSource
import com.sksamuel.hoplite.hocon.HoconParser
import org.slf4j.LoggerFactory
import java.time.Duration

/**
 * Application configuration loaded from HOCON/ENV variables.
 *
 * All configuration values have sensible defaults for local development
 * and can be overridden via environment variables or application.conf.
 *
 * Configuration follows the 12-factor app principles:
 * - Environment variables take precedence
 * - Secrets are never hardcoded
 * - All timeouts and limits are configurable
 */
data class ApplicationConfig(
    val server: ServerConfig = ServerConfig(),
    val database: DatabaseConfig = DatabaseConfig(),
    val kafka: KafkaConfig = KafkaConfig(),
    val resilience: ResilienceConfig = ResilienceConfig(),
    val observability: ObservabilityConfig = ObservabilityConfig(),
    val spiffe: SpiffeConfig = SpiffeConfig(),
    val saga: SagaConfig = SagaConfig(),
    val outbox: OutboxConfig = OutboxConfig()
) {
    companion object {
        private val logger = LoggerFactory.getLogger(ApplicationConfig::class.java)

        /**
         * Load configuration from HOCON files and environment variables.
         * Falls back to defaults if no config file is found.
         */
        fun load(): ApplicationConfig {
            return try {
                ConfigLoaderBuilder.default()
                    .addParser("hocon", HoconParser())
                    .addResourceSource("/application.conf", optional = true)
                    .addResourceSource("/application-${System.getenv("APP_ENV") ?: "dev"}.conf", optional = true)
                    .build()
                    .loadConfigOrThrow<ApplicationConfig>()
                    .also { logger.info("Configuration loaded successfully") }
            } catch (e: Exception) {
                logger.warn("Failed to load config file, using environment variables and defaults", e)
                fromEnvironment()
            }
        }

        /**
         * Build configuration from environment variables with defaults.
         */
        private fun fromEnvironment(): ApplicationConfig = ApplicationConfig(
            server = ServerConfig(
                grpcPort = envInt("GRPC_PORT", 50054),
                httpPort = envInt("HTTP_PORT", 8084),
                shutdownGracePeriodMs = envLong("SHUTDOWN_GRACE_PERIOD_MS", 30000)
            ),
            database = DatabaseConfig(
                url = env("DATABASE_URL", "jdbc:postgresql://localhost:5432/orderdb"),
                username = env("DATABASE_USERNAME", "order"),
                password = env("DATABASE_PASSWORD", ""),
                maxPoolSize = envInt("DATABASE_MAX_POOL_SIZE", 20),
                minIdle = envInt("DATABASE_MIN_IDLE", 5),
                connectionTimeoutMs = envLong("DATABASE_CONNECTION_TIMEOUT_MS", 5000),
                idleTimeoutMs = envLong("DATABASE_IDLE_TIMEOUT_MS", 600000),
                maxLifetimeMs = envLong("DATABASE_MAX_LIFETIME_MS", 1800000)
            ),
            kafka = KafkaConfig(
                bootstrapServers = env("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
                topicPrefix = env("KAFKA_TOPIC_PREFIX", "com.company.order"),
                schemaRegistryUrl = env("KAFKA_SCHEMA_REGISTRY_URL", "http://localhost:8081"),
                producerAcks = env("KAFKA_PRODUCER_ACKS", "all"),
                producerRetries = envInt("KAFKA_PRODUCER_RETRIES", 3),
                consumerGroupId = env("KAFKA_CONSUMER_GROUP_ID", "order-event-consumer"),
                consumerConcurrency = envInt("KAFKA_CONSUMER_CONCURRENCY", 10)
            ),
            resilience = ResilienceConfig(
                circuitBreakerFailureRateThreshold = envDouble("CB_FAILURE_RATE_THRESHOLD", 50.0),
                circuitBreakerWaitDurationMs = envLong("CB_WAIT_DURATION_MS", 30000),
                circuitBreakerMinimumCalls = envInt("CB_MINIMUM_CALLS", 5),
                retryMaxAttempts = envInt("RETRY_MAX_ATTEMPTS", 3),
                retryInitialIntervalMs = envLong("RETRY_INITIAL_INTERVAL_MS", 1000),
                retryMultiplier = envDouble("RETRY_MULTIPLIER", 2.0),
                rateLimiterLimit = envInt("RATE_LIMITER_LIMIT", 100),
                rateLimiterTimeoutMs = envLong("RATE_LIMITER_TIMEOUT_MS", 5000)
            ),
            observability = ObservabilityConfig(
                otlpEndpoint = env("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
                serviceName = env("OTEL_SERVICE_NAME", "order-service"),
                serviceVersion = env("OTEL_SERVICE_VERSION", "1.0.0"),
                enableLoggingExporter = envBool("OTEL_ENABLE_LOGGING_EXPORTER", false),
                samplingRate = envDouble("OTEL_SAMPLING_RATE", 0.1)
            ),
            spiffe = SpiffeConfig(
                trustDomain = env("SPIFFE_TRUST_DOMAIN", "trust.example.org"),
                socketPath = env("SPIFFE_ENDPOINT_SOCKET", "/tmp/spire-agent/public/api.sock"),
                enabled = envBool("SPIFFE_ENABLED", false)
            ),
            saga = SagaConfig(
                recoveryIntervalMs = envLong("SAGA_RECOVERY_INTERVAL_MS", 60000),
                stuckSagaTimeoutMinutes = envLong("SAGA_STUCK_TIMEOUT_MINUTES", 10),
                maxConcurrentSagas = envInt("SAGA_MAX_CONCURRENT", 10)
            ),
            outbox = OutboxConfig(
                relayIntervalMs = envLong("OUTBOX_RELAY_INTERVAL_MS", 100),
                quietIntervalMs = envLong("OUTBOX_QUIET_INTERVAL_MS", 500),
                batchSize = envInt("OUTBOX_BATCH_SIZE", 100)
            )
        )

        private fun env(key: String, default: String): String =
            System.getenv(key) ?: default

        private fun envInt(key: String, default: Int): Int =
            System.getenv(key)?.toIntOrNull() ?: default

        private fun envLong(key: String, default: Long): Long =
            System.getenv(key)?.toLongOrNull() ?: default

        private fun envDouble(key: String, default: Double): Double =
            System.getenv(key)?.toDoubleOrNull() ?: default

        private fun envBool(key: String, default: Boolean): Boolean =
            System.getenv(key)?.toBooleanStrictOrNull() ?: default
    }
}

data class ServerConfig(
    val grpcPort: Int = 50054,
    val httpPort: Int = 8084,
    val shutdownGracePeriodMs: Long = 30000
)

data class DatabaseConfig(
    val url: String = "jdbc:postgresql://localhost:5432/orderdb",
    val username: String = "order",
    val password: String = "", // No default password — must be set via DATABASE_PASSWORD env var
    val maxPoolSize: Int = 20,
    val minIdle: Int = 5,
    val connectionTimeoutMs: Long = 5000,
    val idleTimeoutMs: Long = 600000,
    val maxLifetimeMs: Long = 1800000
)

data class KafkaConfig(
    val bootstrapServers: String = "localhost:9092",
    val topicPrefix: String = "com.company.order",
    val schemaRegistryUrl: String = "http://localhost:8081",
    val producerAcks: String = "all",
    val producerRetries: Int = 3,
    val consumerGroupId: String = "order-event-consumer",
    val consumerConcurrency: Int = 10
)

data class ResilienceConfig(
    val circuitBreakerFailureRateThreshold: Double = 50.0,
    val circuitBreakerWaitDurationMs: Long = 30000,
    val circuitBreakerMinimumCalls: Int = 5,
    val retryMaxAttempts: Int = 3,
    val retryInitialIntervalMs: Long = 1000,
    val retryMultiplier: Double = 2.0,
    val rateLimiterLimit: Int = 100,
    val rateLimiterTimeoutMs: Long = 5000
)

data class ObservabilityConfig(
    val otlpEndpoint: String = "http://localhost:4317",
    val serviceName: String = "order-service",
    val serviceVersion: String = "1.0.0",
    val enableLoggingExporter: Boolean = false,
    val samplingRate: Double = 0.1
)

data class SpiffeConfig(
    val trustDomain: String = "trust.example.org",
    val socketPath: String = "/tmp/spire-agent/public/api.sock",
    val enabled: Boolean = false
)

data class SagaConfig(
    val recoveryIntervalMs: Long = 60000,
    val stuckSagaTimeoutMinutes: Long = 10,
    val maxConcurrentSagas: Int = 10
)

data class OutboxConfig(
    val relayIntervalMs: Long = 100,
    val quietIntervalMs: Long = 500,
    val batchSize: Int = 100
)
