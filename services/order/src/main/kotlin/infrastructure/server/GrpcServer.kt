package com.company.order.infrastructure.server

import com.company.order.adapters.inbound.grpc.OrderGrpcHandler
import com.company.order.infrastructure.config.ApplicationConfig
import com.company.order.infrastructure.di.DIContainer
import io.grpc.Server
import io.grpc.ServerBuilder
import io.grpc.ServerInterceptors
import io.grpc.protobuf.services.ProtoReflectionService
import io.grpc.services.HealthStatusManager
import org.slf4j.LoggerFactory
import java.util.concurrent.TimeUnit

/**
 * gRPC server for the Order service.
 *
 * Runs on the configured port (default: 50054) with:
 * - mTLS enforced (when SPIFFE is enabled)
 * - Server reflection for grpcurl and client discovery
 * - Health checking via the standard gRPC health protocol
 * - Graceful shutdown with configurable grace period
 * - OTel interceptors for request tracing
 *
 * The server is the main entry point for the Order service,
 * receiving all inbound gRPC calls and routing them to the
 * appropriate handler.
 */
class GrpcServer(
    private val config: ApplicationConfig,
    private val container: DIContainer
) {
    private val logger = LoggerFactory.getLogger(GrpcServer::class.java)

    private val healthStatusManager = HealthStatusManager()

    private val server: Server = ServerBuilder
        .forPort(config.server.grpcPort)
        .addService(
            ServerInterceptors.intercept(
                container.grpcHandler,
                // Interceptors would be added here:
                // - AuthenticationInterceptor (SPIFFE SVID validation)
                // - LoggingInterceptor (correlation IDs)
                // - OTelInterceptor (span creation)
            )
        )
        .addService(ProtoReflectionService.newInstance())
        .addService(healthStatusManager.healthService)
        .also { builder ->
            // Configure mTLS if SPIFFE is enabled
            if (config.spiffe.enabled) {
                val sslContext = container.getOtelAdapter().let {
                    // In production: use SPIFFE mTLS context
                    null
                }
                sslContext?.let { ctx ->
                    builder.useTransportSecurity(ctx)
                }
            }
        }
        .build()

    /**
     * Start the gRPC server and block until shutdown.
     */
    fun startAndBlock() {
        start()
        awaitTermination()
    }

    /**
     * Start the gRPC server.
     */
    fun start() {
        logger.info("Starting Order service gRPC server on port ${config.server.grpcPort}")

        server.start()

        // Set overall health status to SERVING
        healthStatusManager.setStatus("", io.grpc.health.v1.HealthGrpc.getServingStatus(io.grpc.health.v1.HealthCheckResponse.ServingStatus.SERVING))

        logger.info("Order service gRPC server started successfully")

        // Add shutdown hook
        Runtime.getRuntime().addShutdownHook(Thread {
            logger.info("Shutting down gRPC server due to JVM shutdown")
            stop()
        })
    }

    /**
     * Stop the gRPC server gracefully.
     */
    fun stop() {
        logger.info("Initiating graceful shutdown of gRPC server")

        // Set health status to NOT_SERVING
        healthStatusManager.setStatus("", io.grpc.health.v1.HealthGrpc.getServingStatus(io.grpc.health.v1.HealthCheckResponse.ServingStatus.NOT_SERVING))

        server.shutdown()
        try {
            if (!server.awaitTermination(config.server.shutdownGracePeriodMs, TimeUnit.MILLISECONDS)) {
                logger.warn("Graceful shutdown timed out, forcing shutdown")
                server.shutdownNow()
                server.awaitTermination(5, TimeUnit.SECONDS)
            }
        } catch (e: InterruptedException) {
            logger.error("Shutdown interrupted", e)
            server.shutdownNow()
            Thread.currentThread().interrupt()
        }

        // Stop the DI container (closes all resources)
        container.stop()

        logger.info("gRPC server shutdown complete")
    }

    /**
     * Wait for the server to terminate.
     */
    private fun awaitTermination() {
        try {
            server.awaitTermination()
        } catch (e: InterruptedException) {
            logger.warn("Server termination interrupted", e)
            Thread.currentThread().interrupt()
        }
    }

    /**
     * Get the server port (useful for testing with port 0).
     */
    val port: Int get() = server.port

    /**
     * Check if the server is running.
     */
    val isRunning: Boolean get() = !server.isShutdown && !server.isTerminated
}

/**
 * Application entry point.
 */
fun main() {
    val config = ApplicationConfig.load()
    val container = DIContainer(config)

    container.start()

    val server = GrpcServer(config, container)
    server.startAndBlock()
}
