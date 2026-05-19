package com.company.order.domain.saga

/**
 * Defines a saga step within the order creation/cancellation flow.
 * Each step has an action (forward) and an optional compensation (rollback).
 *
 * Saga steps are executed sequentially. If any step fails, all previously
 * completed steps are compensated in reverse order.
 *
 * Domain core has ZERO external dependencies.
 */
data class SagaStep(
    val stepName: String,
    val status: SagaStepStatus = SagaStepStatus.PENDING,
    val startedAt: java.time.Instant? = null,
    val completedAt: java.time.Instant? = null,
    val errorMessage: String? = null,
    val retryCount: Int = 0,
    val maxRetries: Int = 3,
    val compensationAction: CompensationAction? = null
) {
    companion object {
        /**
         * Create a new saga step with the given name and compensation.
         */
        fun define(
            stepName: String,
            maxRetries: Int = 3,
            compensationAction: CompensationAction? = null
        ): SagaStep = SagaStep(
            stepName = stepName,
            maxRetries = maxRetries,
            compensationAction = compensationAction
        )
    }

    /** Mark this step as started */
    fun start(): SagaStep = copy(
        status = SagaStepStatus.RUNNING,
        startedAt = java.time.Instant.now()
    )

    /** Mark this step as successfully completed */
    fun complete(): SagaStep = copy(
        status = SagaStepStatus.COMPLETED,
        completedAt = java.time.Instant.now()
    )

    /** Mark this step as failed with an error message */
    fun fail(error: String): SagaStep = copy(
        status = SagaStepStatus.FAILED,
        errorMessage = error,
        completedAt = java.time.Instant.now()
    )

    /** Mark this step as compensating (rollback in progress) */
    fun beginCompensation(): SagaStep = copy(
        status = SagaStepStatus.COMPENSATING
    )

    /** Mark this step as fully compensated */
    fun completeCompensation(): SagaStep = copy(
        status = SagaStepStatus.COMPENSATED,
        completedAt = java.time.Instant.now()
    )

    /** Increment retry count and reset to pending for retry */
    fun prepareRetry(): SagaStep {
        require(retryCount < maxRetries) { "Max retries ($maxRetries) exceeded for step $stepName" }
        return copy(
            status = SagaStepStatus.PENDING,
            retryCount = retryCount + 1,
            errorMessage = null,
            startedAt = null,
            completedAt = null
        )
    }

    /** Whether this step can be retried */
    val canRetry: Boolean get() = status == SagaStepStatus.FAILED && retryCount < maxRetries

    /** Whether this step is in a terminal state */
    val isTerminal: Boolean get() = status in setOf(
        SagaStepStatus.COMPLETED,
        SagaStepStatus.COMPENSATED
    )
}

/**
 * Status of an individual saga step.
 */
enum class SagaStepStatus {
    PENDING,       // Not yet started
    RUNNING,       // Currently executing
    COMPLETED,     // Successfully completed
    FAILED,        // Execution failed
    COMPENSATING,  // Compensation (rollback) in progress
    COMPENSATED    // Compensation completed
}
