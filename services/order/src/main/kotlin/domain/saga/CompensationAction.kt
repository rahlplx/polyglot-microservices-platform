package com.company.order.domain.saga

/**
 * Compensation action to be executed when a saga step needs to be rolled back.
 * Each compensation action knows how to reverse the effects of its
 * corresponding forward step.
 *
 * Compensation actions are executed in reverse order of the completed
 * steps (LIFO), ensuring that dependencies are properly unwound.
 *
 * Domain core has ZERO external dependencies.
 */
data class CompensationAction(
    val actionType: CompensationType,
    val targetService: String,
    val description: String,
    val parameters: Map<String, String> = emptyMap()
)

/**
 * Types of compensation actions in the Order service.
 * Each type corresponds to a specific rollback operation.
 */
enum class CompensationType {
    /** Release inventory reservations in the Catalog service */
    RELEASE_INVENTORY,

    /** Void a payment authorization in the Payment service */
    VOID_AUTHORIZATION,

    /** Refund a captured payment in the Payment service */
    REFUND_PAYMENT,

    /** Confirm inventory deduction (undo reservation release) */
    CANCEL_INVENTORY_CONFIRMATION,

    /** Send cancellation notification via Notification service */
    NOTIFY_CANCELLATION
}

/**
 * Factory for creating common compensation actions.
 */
object CompensationActions {

    /**
     * Create a compensation action to release inventory reservations.
     */
    fun releaseInventory(reservationIds: List<String>): CompensationAction = CompensationAction(
        actionType = CompensationType.RELEASE_INVENTORY,
        targetService = "catalog",
        description = "Release inventory reservations: ${reservationIds.joinToString()}",
        parameters = mapOf("reservation_ids" to reservationIds.joinToString(","))
    )

    /**
     * Create a compensation action to void a payment authorization.
     */
    fun voidAuthorization(paymentId: String, reason: String): CompensationAction = CompensationAction(
        actionType = CompensationType.VOID_AUTHORIZATION,
        targetService = "payment",
        description = "Void payment authorization: $paymentId",
        parameters = mapOf(
            "payment_id" to paymentId,
            "reason" to reason
        )
    )

    /**
     * Create a compensation action to refund a captured payment.
     */
    fun refundPayment(paymentId: String, amount: String, reason: String): CompensationAction = CompensationAction(
        actionType = CompensationType.REFUND_PAYMENT,
        targetService = "payment",
        description = "Refund payment: $paymentId for $amount",
        parameters = mapOf(
            "payment_id" to paymentId,
            "amount" to amount,
            "reason" to reason
        )
    )

    /**
     * Create a compensation action to send cancellation notification.
     */
    fun notifyCancellation(orderId: String, customerId: String, reason: String): CompensationAction =
        CompensationAction(
            actionType = CompensationType.NOTIFY_CANCELLATION,
            targetService = "notification",
            description = "Send cancellation notification for order $orderId",
            parameters = mapOf(
                "order_id" to orderId,
                "customer_id" to customerId,
                "reason" to reason
            )
        )
}
