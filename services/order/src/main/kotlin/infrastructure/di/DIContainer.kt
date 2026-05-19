package com.company.order.infrastructure.di

import com.company.order.adapters.inbound.grpc.OrderGrpcHandler
import com.company.order.adapters.outbound.messaging.KafkaEventPublisher
import com.company.order.adapters.outbound.observability.OtelAdapter
import com.company.order.adapters.outbound.outbox.OutboxWriter
import com.company.order.adapters.outbound.persistence.JooqOrderRepository
import com.company.order.adapters.outbound.resilience.Resilience4jConfig
import com.company.order.domain.ports.outbound.EventPublisherPort
import com.company.order.domain.ports.outbound.OrderRepositoryPort
import com.company.order.domain.services.CatalogClientPort
import com.company.order.domain.services.OrderService
import com.company.order.domain.services.PaymentClientPort
import com.company.order.domain.services.SagaOrchestrator
import com.company.order.infrastructure.config.ApplicationConfig
import com.company.order.infrastructure.identity.SpiffeIntegration
import com.zaxxer.hikari.HikariConfig
import com.zaxxer.hikari.HikariDataSource
import org.jooq.DSLContext
import org.jooq.SQLDialect
import org.jooq.impl.DSL
import org.slf4j.LoggerFactory
import javax.sql.DataSource

/**
 * Manual dependency injection container for the Order service.
 *
 * Wires all components together following the hexagonal architecture:
 * - Domain services depend only on ports (interfaces)
 * - Adapters implement ports and depend on infrastructure
 * - Infrastructure provides configuration and lifecycle management
 *
 * No reflection-based DI framework needed — explicit wiring provides
 * compile-time safety and clear dependency graphs.
 */
class DIContainer(
    private val config: ApplicationConfig
) {
    private val logger = LoggerFactory.getLogger(DIContainer::class.java)

    // --- Infrastructure ---

    private val dataSource: DataSource by lazy {
        val hikariConfig = HikariConfig().apply {
            jdbcUrl = config.database.url
            username = config.database.username
            password = config.database.password
            maximumPoolSize = config.database.maxPoolSize
            minimumIdle = config.database.minIdle
            connectionTimeout = config.database.connectionTimeoutMs
            idleTimeout = config.database.idleTimeoutMs
            maxLifetime = config.database.maxLifetimeMs
            poolName = "order-service-pool"
            connectionTestQuery = "SELECT 1"
        }
        HikariDataSource(hikariConfig).also {
            logger.info("Database connection pool created: url=${config.database.url}, maxPool=${config.database.maxPoolSize}")
        }
    }

    private val dslContext: DSLContext by lazy {
        DSL.using(dataSource, SQLDialect.POSTGRES)
    }

    private val otelAdapter: OtelAdapter by lazy {
        OtelAdapter(
            serviceName = config.observability.serviceName,
            serviceVersion = config.observability.serviceVersion,
            otlpEndpoint = config.observability.otlpEndpoint,
            enableLoggingExporter = config.observability.enableLoggingExporter
        )
    }

    private val resilience4jConfig: Resilience4jConfig by lazy {
        Resilience4jConfig().also {
            it.registerCircuitBreakerListeners()
        }
    }

    private val spiffeIntegration: SpiffeIntegration by lazy {
        SpiffeIntegration(
            trustDomain = config.spiffe.trustDomain,
            socketPath = config.spiffe.socketPath,
            enabled = config.spiffe.enabled
        )
    }

    // --- Outbound Adapters ---

    private val orderRepository: OrderRepositoryPort by lazy {
        JooqOrderRepository(dslContext)
    }

    private val eventPublisher: EventPublisherPort by lazy {
        KafkaEventPublisher(
            bootstrapServers = config.kafka.bootstrapServers,
            topicPrefix = config.kafka.topicPrefix,
            schemaRegistryUrl = config.kafka.schemaRegistryUrl
        )
    }

    private val outboxWriter: OutboxWriter by lazy {
        OutboxWriter(
            orderRepository = orderRepository,
            eventPublisher = eventPublisher,
            relayIntervalMs = config.outbox.relayIntervalMs,
            quietIntervalMs = config.outbox.quietIntervalMs,
            batchSize = config.outbox.batchSize
        )
    }

    private val catalogClient: CatalogClientPort by lazy {
        ResilientCatalogClient(
            delegate = GrpcCatalogClient(config, spiffeIntegration),
            resilience4jConfig = resilience4jConfig
        )
    }

    private val paymentClient: PaymentClientPort by lazy {
        ResilientPaymentClient(
            delegate = GrpcPaymentClient(config, spiffeIntegration),
            resilience4jConfig = resilience4jConfig
        )
    }

    // --- Domain Services ---

    private val sagaOrchestrator: SagaOrchestrator by lazy {
        SagaOrchestrator(
            orderRepository = orderRepository,
            eventPublisher = eventPublisher,
            catalogClient = catalogClient,
            paymentClient = paymentClient
        )
    }

    val orderService: OrderService by lazy {
        OrderService(
            orderRepository = orderRepository,
            eventPublisher = eventPublisher,
            sagaOrchestrator = sagaOrchestrator
        )
    }

    // --- Inbound Adapters ---

    val grpcHandler: OrderGrpcHandler by lazy {
        OrderGrpcHandler(
            createOrderUseCase = orderService,
            completeOrderUseCase = orderService,
            cancelOrderUseCase = orderService,
            listOrdersUseCase = orderService,
            getOrderStatusUseCase = orderService,
            orderRepository = orderRepository
        )
    }

    // --- Lifecycle ---

    /**
     * Initialize all components and start background processes.
     */
    fun start() {
        logger.info("Starting Order service DI container")

        // Initialize SPIFFE
        spiffeIntegration.initialize()

        // Start the outbox relay
        outboxWriter.start()

        // Register shutdown hook
        Runtime.getRuntime().addShutdownHook(Thread {
            logger.info("Shutdown hook triggered")
            stop()
        })

        logger.info("Order service DI container started successfully")
    }

    /**
     * Stop all components gracefully.
     */
    fun stop() {
        logger.info("Stopping Order service DI container")

        outboxWriter.stop()

        if (eventPublisher is KafkaEventPublisher) {
            eventPublisher.close()
        }

        spiffeIntegration.close()
        otelAdapter.shutdown()

        if (dataSource is HikariDataSource) {
            (dataSource as HikariDataSource).close()
        }

        logger.info("Order service DI container stopped")
    }

    /**
     * Get the outbox writer for management operations.
     */
    fun getOutboxWriter(): OutboxWriter = outboxWriter

    /**
     * Get the resilience configuration for health checks.
     */
    fun getResilienceConfig(): Resilience4jConfig = resilience4jConfig

    /**
     * Get the OTel adapter for observability.
     */
    fun getOtelAdapter(): OtelAdapter = otelAdapter

    // --- gRPC Client Stubs (Simplified for this implementation) ---

    /**
     * gRPC-based Catalog service client.
     * In production, this would use generated gRPC stubs with mTLS.
     */
    private class GrpcCatalogClient(
        private val config: ApplicationConfig,
        private val spiffe: SpiffeIntegration
    ) : CatalogClientPort {
        override suspend fun reserveInventory(request: com.company.order.domain.services.ReservationRequest): com.company.order.domain.services.ReservationResponse {
            // In production: gRPC call to Catalog service with mTLS
            throw NotImplementedError("Catalog gRPC client not yet connected - use mock for testing")
        }

        override suspend fun releaseInventory(request: com.company.order.domain.services.ReleaseInventoryRequest): com.company.order.domain.services.ReleaseInventoryResponse {
            throw NotImplementedError("Catalog gRPC client not yet connected - use mock for testing")
        }

        override suspend fun confirmReservation(reservationIds: List<String>): com.company.order.domain.services.ConfirmReservationResponse {
            throw NotImplementedError("Catalog gRPC client not yet connected - use mock for testing")
        }
    }

    /**
     * gRPC-based Payment service client.
     * In production, this would use generated gRPC stubs with mTLS.
     */
    private class GrpcPaymentClient(
        private val config: ApplicationConfig,
        private val spiffe: SpiffeIntegration
    ) : PaymentClientPort {
        override suspend fun authorizePayment(request: com.company.order.domain.services.PaymentAuthorizationRequest): com.company.order.domain.services.PaymentAuthorizationResponse {
            throw NotImplementedError("Payment gRPC client not yet connected - use mock for testing")
        }

        override suspend fun capturePayment(paymentId: String, amount: com.company.order.domain.models.Money): com.company.order.domain.services.CapturePaymentResponse {
            throw NotImplementedError("Payment gRPC client not yet connected - use mock for testing")
        }

        override suspend fun refundPayment(request: com.company.order.domain.services.RefundPaymentRequest): com.company.order.domain.services.RefundPaymentResponse {
            throw NotImplementedError("Payment gRPC client not yet connected - use mock for testing")
        }

        override suspend fun voidAuthorization(request: com.company.order.domain.services.VoidAuthorizationRequest): com.company.order.domain.services.VoidAuthorizationResponse {
            throw NotImplementedError("Payment gRPC client not yet connected - use mock for testing")
        }

        override suspend fun getPaymentStatus(paymentId: String): com.company.order.domain.services.PaymentStatusResponse {
            throw NotImplementedError("Payment gRPC client not yet connected - use mock for testing")
        }
    }

    // --- Resilient Client Wrappers ---

    /**
     * Wraps Catalog client calls with circuit breaker, retry, and rate limiter.
     */
    private class ResilientCatalogClient(
        private val delegate: CatalogClientPort,
        private val resilience4jConfig: Resilience4jConfig
    ) : CatalogClientPort {
        override suspend fun reserveInventory(request: com.company.order.domain.services.ReservationRequest): com.company.order.domain.services.ReservationResponse {
            return resilience4jConfig.executeWithResilience(
                resilience4jConfig.catalogCircuitBreaker,
                resilience4jConfig.catalogRetry,
                resilience4jConfig.catalogRateLimiter
            ) { delegate.reserveInventory(request) }
        }

        override suspend fun releaseInventory(request: com.company.order.domain.services.ReleaseInventoryRequest): com.company.order.domain.services.ReleaseInventoryResponse {
            return resilience4jConfig.executeWithResilience(
                resilience4jConfig.catalogCircuitBreaker,
                resilience4jConfig.catalogRetry,
                resilience4jConfig.catalogRateLimiter
            ) { delegate.releaseInventory(request) }
        }

        override suspend fun confirmReservation(reservationIds: List<String>): com.company.order.domain.services.ConfirmReservationResponse {
            return resilience4jConfig.executeWithResilience(
                resilience4jConfig.catalogCircuitBreaker,
                resilience4jConfig.catalogRetry,
                resilience4jConfig.catalogRateLimiter
            ) { delegate.confirmReservation(reservationIds) }
        }
    }

    /**
     * Wraps Payment client calls with circuit breaker, retry, and rate limiter.
     */
    private class ResilientPaymentClient(
        private val delegate: PaymentClientPort,
        private val resilience4jConfig: Resilience4jConfig
    ) : PaymentClientPort {
        override suspend fun authorizePayment(request: com.company.order.domain.services.PaymentAuthorizationRequest): com.company.order.domain.services.PaymentAuthorizationResponse {
            return resilience4jConfig.executeWithResilience(
                resilience4jConfig.paymentCircuitBreaker,
                resilience4jConfig.paymentRetry,
                resilience4jConfig.paymentRateLimiter
            ) { delegate.authorizePayment(request) }
        }

        override suspend fun capturePayment(paymentId: String, amount: com.company.order.domain.models.Money): com.company.order.domain.services.CapturePaymentResponse {
            return resilience4jConfig.executeWithResilience(
                resilience4jConfig.paymentCircuitBreaker,
                resilience4jConfig.paymentRetry,
                resilience4jConfig.paymentRateLimiter
            ) { delegate.capturePayment(paymentId, amount) }
        }

        override suspend fun refundPayment(request: com.company.order.domain.services.RefundPaymentRequest): com.company.order.domain.services.RefundPaymentResponse {
            return resilience4jConfig.executeWithResilience(
                resilience4jConfig.paymentCircuitBreaker,
                resilience4jConfig.paymentRetry,
                resilience4jConfig.paymentRateLimiter
            ) { delegate.refundPayment(request) }
        }

        override suspend fun voidAuthorization(request: com.company.order.domain.services.VoidAuthorizationRequest): com.company.order.domain.services.VoidAuthorizationResponse {
            return resilience4jConfig.executeWithResilience(
                resilience4jConfig.paymentCircuitBreaker,
                resilience4jConfig.paymentRetry,
                resilience4jConfig.paymentRateLimiter
            ) { delegate.voidAuthorization(request) }
        }

        override suspend fun getPaymentStatus(paymentId: String): com.company.order.domain.services.PaymentStatusResponse {
            return resilience4jConfig.executeWithResilience(
                resilience4jConfig.paymentCircuitBreaker,
                resilience4jConfig.paymentRetry,
                resilience4jConfig.paymentRateLimiter
            ) { delegate.getPaymentStatus(paymentId) }
        }
    }
}
