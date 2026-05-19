package com.company.order.adapters.outbound.resilience

import io.github.resilience4j.circuitbreaker.CircuitBreaker
import io.github.resilience4j.circuitbreaker.CircuitBreakerConfig
import io.github.resilience4j.circuitbreaker.CircuitBreakerRegistry
import io.github.resilience4j.kotlin.circuitbreaker.executeSuspendFunction
import io.github.resilience4j.kotlin.retry.executeSuspendFunction
import io.github.resilience4j.retry.Retry
import io.github.resilience4j.retry.RetryConfig
import io.github.resilience4j.retry.RetryRegistry
import io.github.resilience4j.ratelimiter.RateLimiter
import io.github.resilience4j.ratelimiter.RateLimiterConfig
import io.github.resilience4j.ratelimiter.RateLimiterRegistry
import org.slf4j.LoggerFactory
import java.time.Duration

/**
 * Resilience4j configuration for the Order service.
 *
 * Provides circuit breaker, retry, and rate limiter instances for
 * all external service calls and critical operations:
 *
 * - Circuit breaker: protects against cascading failures when
 *   downstream services (Payment, Catalog) are degraded
 * - Retry: automatic retry with exponential backoff for transient failures
 * - Rate limiter: prevents overloading downstream services
 *
 * Configuration is aligned with the performance-budget.md spec:
 * - Payment service: 5 failures → open, 30s cooldown
 * - Catalog service: 5 failures → open, 30s cooldown
 * - Kafka producer: 3 failures → open, 10s cooldown
 * - Retry: 3 attempts, exponential backoff (1s → 2s → 4s)
 */
class Resilience4jConfig {

    private val logger = LoggerFactory.getLogger(Resilience4jConfig::class.java)

    // --- Circuit Breaker Configuration ---

    private val circuitBreakerRegistry: CircuitBreakerRegistry = CircuitBreakerRegistry.of(
        CircuitBreakerConfig.custom()
            .failureRateThreshold(50.0f)
            .slowCallRateThreshold(80.0f)
            .slowCallDurationThreshold(Duration.ofSeconds(2))
            .waitDurationInOpenState(Duration.ofSeconds(30))
            .permittedNumberOfCallsInHalfOpenState(3)
            .minimumNumberOfCalls(5)
            .slidingWindowType(CircuitBreakerConfig.SlidingWindowType.COUNT_BASED)
            .slidingWindowSize(10)
            .recordExceptions { true } // Record all exceptions as failures
            .build()
    )

    /** Circuit breaker for Payment service calls */
    val paymentCircuitBreaker: CircuitBreaker = circuitBreakerRegistry.circuitBreaker("payment") {
        CircuitBreakerConfig.custom()
            .failureRateThreshold(50.0f)
            .slowCallRateThreshold(80.0f)
            .slowCallDurationThreshold(Duration.ofSeconds(3))
            .waitDurationInOpenState(Duration.ofSeconds(30))
            .permittedNumberOfCallsInHalfOpenState(3)
            .minimumNumberOfCalls(5)
            .slidingWindowSize(10)
            .build()
    }

    /** Circuit breaker for Catalog service calls */
    val catalogCircuitBreaker: CircuitBreaker = circuitBreakerRegistry.circuitBreaker("catalog") {
        CircuitBreakerConfig.custom()
            .failureRateThreshold(50.0f)
            .slowCallRateThreshold(80.0f)
            .slowCallDurationThreshold(Duration.ofSeconds(2))
            .waitDurationInOpenState(Duration.ofSeconds(30))
            .permittedNumberOfCallsInHalfOpenState(3)
            .minimumNumberOfCalls(5)
            .slidingWindowSize(10)
            .build()
    }

    /** Circuit breaker for Kafka publishing */
    val kafkaCircuitBreaker: CircuitBreaker = circuitBreakerRegistry.circuitBreaker("kafka") {
        CircuitBreakerConfig.custom()
            .failureRateThreshold(60.0f)
            .slowCallRateThreshold(90.0f)
            .slowCallDurationThreshold(Duration.ofSeconds(5))
            .waitDurationInOpenState(Duration.ofSeconds(10))
            .permittedNumberOfCallsInHalfOpenState(5)
            .minimumNumberOfCalls(3)
            .slidingWindowSize(5)
            .build()
    }

    // --- Retry Configuration ---

    private val retryRegistry: RetryRegistry = RetryRegistry.of(
        RetryConfig.custom<Any>()
            .maxAttempts(3)
            .waitDuration(Duration.ofMillis(1000))
            .retryOnException { e ->
                // Retry on transient errors, not on business logic errors
                when (e) {
                    is com.company.order.domain.ports.inbound.InsufficientStockException -> false
                    is com.company.order.domain.ports.inbound.PaymentMethodInvalidException -> false
                    is com.company.order.domain.ports.inbound.DuplicateOrderException -> false
                    is com.company.order.domain.ports.outbound.EventPublishException -> true
                    else -> true // Retry on unknown exceptions (network, timeout, etc.)
                }
            }
            .intervalFunction(io.github.resilience4j.core.IntervalFunction.ofExponentialBackoff(
                Duration.ofMillis(1000), 2.0
            ))
            .build()
    )

    /** Retry for Payment service calls */
    val paymentRetry: Retry = retryRegistry.retry("payment") {
        RetryConfig.custom<Any>()
            .maxAttempts(3)
            .waitDuration(Duration.ofMillis(1000))
            .intervalFunction(io.github.resilience4j.core.IntervalFunction.ofExponentialBackoff(
                Duration.ofMillis(1000), 2.0
            ))
            .build()
    }

    /** Retry for Catalog service calls */
    val catalogRetry: Retry = retryRegistry.retry("catalog") {
        RetryConfig.custom<Any>()
            .maxAttempts(3)
            .waitDuration(Duration.ofMillis(500))
            .intervalFunction(io.github.resilience4j.core.IntervalFunction.ofExponentialBackoff(
                Duration.ofMillis(500), 2.0
            ))
            .build()
    }

    /** Retry for Kafka publishing */
    val kafkaRetry: Retry = retryRegistry.retry("kafka") {
        RetryConfig.custom<Any>()
            .maxAttempts(3)
            .waitDuration(Duration.ofMillis(200))
            .intervalFunction(io.github.resilience4j.core.IntervalFunction.ofExponentialBackoff(
                Duration.ofMillis(200), 2.0
            ))
            .build()
    }

    // --- Rate Limiter Configuration ---

    private val rateLimiterRegistry: RateLimiterRegistry = RateLimiterRegistry.of(
        RateLimiterConfig.custom()
            .limitForPeriod(100)
            .limitRefreshPeriod(Duration.ofSeconds(1))
            .timeoutDuration(Duration.ofSeconds(5))
            .build()
    )

    /** Rate limiter for Payment service calls (50 req/s) */
    val paymentRateLimiter: RateLimiter = rateLimiterRegistry.rateLimiter("payment") {
        RateLimiterConfig.custom()
            .limitForPeriod(50)
            .limitRefreshPeriod(Duration.ofSeconds(1))
            .timeoutDuration(Duration.ofSeconds(5))
            .build()
    }

    /** Rate limiter for Catalog service calls (100 req/s) */
    val catalogRateLimiter: RateLimiter = rateLimiterRegistry.rateLimiter("catalog") {
        RateLimiterConfig.custom()
            .limitForPeriod(100)
            .limitRefreshPeriod(Duration.ofSeconds(1))
            .timeoutDuration(Duration.ofSeconds(5))
            .build()
    }

    // --- Helper Methods ---

    /**
     * Execute a suspend function with circuit breaker, retry, and rate limiter protection.
     */
    suspend fun <T> executeWithResilience(
        circuitBreaker: CircuitBreaker,
        retry: Retry,
        rateLimiter: RateLimiter,
        block: suspend () -> T
    ): T {
        return circuitBreaker.executeSuspendFunction {
            retry.executeSuspendFunction {
                rateLimiter.acquirePermission()
                block()
            }
        }
    }

    /**
     * Execute a suspend function with circuit breaker and retry (no rate limiting).
     */
    suspend fun <T> executeWithCircuitBreakerAndRetry(
        circuitBreaker: CircuitBreaker,
        retry: Retry,
        block: suspend () -> T
    ): T {
        return circuitBreaker.executeSuspendFunction {
            retry.executeSuspendFunction {
                block()
            }
        }
    }

    /**
     * Get the current state of all circuit breakers for health checks.
     */
    fun getCircuitBreakerStates(): Map<String, String> = mapOf(
        "payment" to paymentCircuitBreaker.state.name,
        "catalog" to catalogCircuitBreaker.state.name,
        "kafka" to kafkaCircuitBreaker.state.name
    )

    /**
     * Register event listeners for circuit breaker state transitions.
     */
    fun registerCircuitBreakerListeners() {
        listOf(paymentCircuitBreaker, catalogCircuitBreaker, kafkaCircuitBreaker).forEach { cb ->
            cb.eventPublisher.onStateTransition { event ->
                logger.warn("Circuit breaker '${cb.name}' state transition: ${event.stateTransition}")
            }
            cb.eventPublisher.onError { event ->
                logger.debug("Circuit breaker '${cb.name}' recorded error: ${event.throwable.message}")
            }
            cb.eventPublisher.onSuccess { event ->
                // Success events are too noisy for INFO, use DEBUG
            }
        }
    }
}
