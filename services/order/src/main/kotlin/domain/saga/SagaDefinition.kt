package com.company.order.domain.saga

/**
 * Saga definition for the Order service.
 * Defines the steps for the order creation and cancellation sagas,
 * including their compensation actions.
 *
 * Choreography-based saga: each step emits events that trigger the next step.
 * The SagaOrchestrator tracks state and handles failures/compensations.
 *
 * Domain core has ZERO external dependencies.
 */
object SagaDefinition {

    // --- Order Creation Saga ---

    /**
     * Define the steps for the order creation saga.
     * Steps are executed sequentially; if any fails, previous steps are compensated.
     *
     * Step 1: RESERVE_INVENTORY - Reserve inventory for all line items
     * Step 2: AUTHORIZE_PAYMENT - Authorize payment for the order total
     * Step 3: CONFIRM_ORDER - Transition order to RESERVED/PAID status
     */
    fun orderCreationSaga(orderId: String): List<SagaStep> = listOf(
        SagaStep.define(
            stepName = "RESERVE_INVENTORY",
            maxRetries = 3,
            compensationAction = CompensationAction(
                actionType = CompensationType.RELEASE_INVENTORY,
                targetService = "catalog",
                description = "Release inventory reservations for order $orderId"
            )
        ),
        SagaStep.define(
            stepName = "AUTHORIZE_PAYMENT",
            maxRetries = 3,
            compensationAction = CompensationAction(
                actionType = CompensationType.VOID_AUTHORIZATION,
                targetService = "payment",
                description = "Void payment authorization for order $orderId"
            )
        ),
        SagaStep.define(
            stepName = "CONFIRM_ORDER",
            maxRetries = 1,
            compensationAction = CompensationAction(
                actionType = CompensationType.CANCEL_INVENTORY_CONFIRMATION,
                targetService = "catalog",
                description = "Cancel inventory confirmation for order $orderId"
            )
        )
    )

    // --- Order Cancellation Saga ---

    /**
     * Define the steps for the order cancellation saga.
     * Steps depend on the current order state and which forward
     * saga steps have been completed.
     *
     * Compensation is adaptive: only steps that were completed
     * in the forward saga are compensated.
     */
    fun orderCancellationSaga(
        orderId: String,
        completedForwardSteps: List<String>,
        paymentId: String?,
        reservationIds: List<String>,
        paymentCaptured: Boolean
    ): List<SagaStep> {
        val steps = mutableListOf<SagaStep>()

        // Release inventory if it was reserved
        if ("RESERVE_INVENTORY" in completedForwardSteps || "CONFIRM_ORDER" in completedForwardSteps) {
            steps.add(
                SagaStep.define(
                    stepName = "RELEASE_INVENTORY",
                    maxRetries = 3,
                    compensationAction = CompensationActions.releaseInventory(reservationIds)
                )
            )
        }

        // Void or refund payment if it was authorized/captured
        if (("AUTHORIZE_PAYMENT" in completedForwardSteps || "CONFIRM_ORDER" in completedForwardSteps) && paymentId != null) {
            if (paymentCaptured) {
                steps.add(
                    SagaStep.define(
                        stepName = "REFUND_PAYMENT",
                        maxRetries = 3,
                        compensationAction = CompensationAction(
                            actionType = CompensationType.VOID_AUTHORIZATION,
                            targetService = "payment",
                            description = "Void payment if refund fails for order $orderId"
                        )
                    )
                )
            } else {
                steps.add(
                    SagaStep.define(
                        stepName = "VOID_AUTHORIZATION",
                        maxRetries = 3,
                        compensationAction = CompensationAction(
                            actionType = CompensationType.REFUND_PAYMENT,
                            targetService = "payment",
                            description = "Refund payment if void fails for order $orderId"
                        )
                    )
                )
            }
        }

        // Send cancellation notification
        steps.add(
            SagaStep.define(
                stepName = "NOTIFY_CANCELLATION",
                maxRetries = 2,
                compensationAction = null // Notifications are best-effort
            )
        )

        return steps
    }

    // --- Step name constants ---

    const val STEP_RESERVE_INVENTORY = "RESERVE_INVENTORY"
    const val STEP_AUTHORIZE_PAYMENT = "AUTHORIZE_PAYMENT"
    const val STEP_CONFIRM_ORDER = "CONFIRM_ORDER"
    const val STEP_RELEASE_INVENTORY = "RELEASE_INVENTORY"
    const val STEP_VOID_AUTHORIZATION = "VOID_AUTHORIZATION"
    const val STEP_REFUND_PAYMENT = "REFUND_PAYMENT"
    const val STEP_NOTIFY_CANCELLATION = "NOTIFY_CANCELLATION"

    /** All creation saga step names in order */
    val CREATION_STEPS = listOf(STEP_RESERVE_INVENTORY, STEP_AUTHORIZE_PAYMENT, STEP_CONFIRM_ORDER)

    /** All possible cancellation step names */
    val CANCELLATION_STEPS = listOf(
        STEP_RELEASE_INVENTORY, STEP_VOID_AUTHORIZATION,
        STEP_REFUND_PAYMENT, STEP_NOTIFY_CANCELLATION
    )
}

/**
 * Saga instance tracking the execution state of a saga.
 */
data class SagaInstance(
    val sagaId: String,
    val orderId: String,
    val sagaType: SagaType,
    val status: SagaStatus = SagaStatus.RUNNING,
    val steps: List<SagaStep>,
    val startedAt: java.time.Instant = java.time.Instant.now(),
    val completedAt: java.time.Instant? = null,
    val failureReason: String? = null
) {
    companion object {
        /**
         * Create a new saga instance with the given steps.
         */
        fun create(
            sagaId: String,
            orderId: String,
            sagaType: SagaType,
            steps: List<SagaStep>
        ): SagaInstance = SagaInstance(
            sagaId = sagaId,
            orderId = orderId,
            sagaType = sagaType,
            status = SagaStatus.RUNNING,
            steps = steps
        )
    }

    /** Get the current running step, or null if none */
    val currentStep: SagaStep? get() = steps.firstOrNull { it.status == SagaStepStatus.RUNNING }

    /** Get the next pending step, or null if none */
    val nextPendingStep: SagaStep? get() = steps.firstOrNull { it.status == SagaStepStatus.PENDING }

    /** Get all completed step names */
    val completedStepNames: List<String> get() = steps.filter { it.status == SagaStepStatus.COMPLETED }.map { it.stepName }

    /** Get all remaining step names */
    val remainingStepNames: List<String> get() = steps.filter { it.status == SagaStepStatus.PENDING }.map { it.stepName }

    /** Get all compensation step names that have been executed */
    val compensationStepNames: List<String> get() = steps.filter {
        it.status == SagaStepStatus.COMPENSATED || it.status == SagaStepStatus.COMPENSATING
    }.map { it.stepName }

    /** Whether all steps are completed */
    val allStepsCompleted: Boolean get() = steps.all { it.status == SagaStepStatus.COMPLETED }

    /** Whether any step has failed */
    val hasFailedStep: Boolean get() = steps.any { it.status == SagaStepStatus.FAILED }

    /**
     * Start a specific step by name.
     */
    fun startStep(stepName: String): SagaInstance {
        val updatedSteps = steps.map { step ->
            if (step.stepName == stepName && step.status == SagaStepStatus.PENDING) step.start() else step
        }
        return copy(steps = updatedSteps)
    }

    /**
     * Complete a specific step by name.
     */
    fun completeStep(stepName: String): SagaInstance {
        val updatedSteps = steps.map { step ->
            if (step.stepName == stepName && step.status == SagaStepStatus.RUNNING) step.complete() else step
        }
        val newStatus = if (updatedSteps.all { it.status == SagaStepStatus.COMPLETED }) {
            SagaStatus.COMPLETED
        } else {
            status
        }
        return copy(
            steps = updatedSteps,
            status = newStatus,
            completedAt = if (newStatus == SagaStatus.COMPLETED) java.time.Instant.now() else null
        )
    }

    /**
     * Fail a specific step and transition the saga to COMPENSATING.
     */
    fun failStep(stepName: String, error: String): SagaInstance {
        val updatedSteps = steps.map { step ->
            if (step.stepName == stepName && step.status == SagaStepStatus.RUNNING) step.fail(error) else step
        }
        return copy(
            steps = updatedSteps,
            status = SagaStatus.COMPENSATING,
            failureReason = "Step $stepName failed: $error"
        )
    }

    /**
     * Begin compensating all completed steps in reverse order.
     */
    fun beginCompensation(): SagaInstance {
        val updatedSteps = steps.map { step ->
            if (step.status == SagaStepStatus.COMPLETED) step.beginCompensation() else step
        }
        return copy(
            steps = updatedSteps,
            status = SagaStatus.COMPENSATING
        )
    }

    /**
     * Complete compensation for a specific step.
     */
    fun completeCompensation(stepName: String): SagaInstance {
        val updatedSteps = steps.map { step ->
            if (step.stepName == stepName && step.status == SagaStepStatus.COMPENSATING) step.completeCompensation()
            else step
        }
        val allCompensated = updatedSteps
            .filter { it.status == SagaStepStatus.COMPENSATED || it.status == SagaStepStatus.PENDING }
            .all { it.status == SagaStepStatus.COMPENSATED || it.compensationAction == null }

        val newStatus = if (allCompensated && hasFailedStep) {
            SagaStatus.FAILED
        } else if (allCompensated) {
            SagaStatus.FAILED
        } else {
            SagaStatus.COMPENSATING
        }

        return copy(
            steps = updatedSteps,
            status = newStatus,
            completedAt = if (newStatus == SagaStatus.FAILED) java.time.Instant.now() else null
        )
    }

    /**
     * Get the steps that need compensation (completed steps in reverse order).
     */
    fun stepsNeedingCompensation(): List<SagaStep> =
        steps.filter { it.status == SagaStepStatus.COMPLETED || it.status == SagaStepStatus.FAILED }
            .reversed()
            .filter { it.compensationAction != null }
}

/**
 * Type of saga.
 */
enum class SagaType {
    ORDER_CREATION,
    ORDER_CANCELLATION
}

/**
 * Status of a saga instance.
 */
enum class SagaStatus {
    RUNNING,       // Saga is executing forward steps
    COMPLETED,     // All forward steps completed successfully
    COMPENSATING,  // Executing compensation actions
    FAILED         // Saga failed (compensation completed or no compensation needed)
}
