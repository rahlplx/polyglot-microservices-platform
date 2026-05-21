package com.company.order.domain.ports.outbound

/**
 * Outbound port for sending notifications to customers.
 *
 * In the standard flow, notifications are triggered by domain events
 * published through the transactional outbox. The Notification service
 * consumes these events and handles delivery autonomously.
 *
 * This port exists as a fallback for scenarios where a notification
 * must be triggered outside the normal event flow (e.g., urgent fraud alerts).
 */
interface NotificationClientPort {

    /**
     * Send a notification to a customer or internal team.
     *
     * @param request The notification request
     * @return The notification response with delivery tracking ID
     */
    suspend fun sendNotification(request: NotificationRequest): NotificationResponse

    /**
     * Check the delivery status of a previously sent notification.
     *
     * @param notificationId The notification to check
     * @return The current delivery status
     */
    suspend fun getNotificationStatus(notificationId: String): NotificationStatusResponse
}

/**
 * Notification request DTO.
 */
data class NotificationRequest(
    val customerId: String,
    val notificationType: String,
    val channel: NotificationChannel = NotificationChannel.EMAIL,
    val templateId: String,
    val templateData: Map<String, String> = emptyMap(),
    val priority: NotificationPriority = NotificationPriority.NORMAL,
    val orderId: String? = null
)

/**
 * Notification response DTO.
 */
data class NotificationResponse(
    val notificationId: String,
    val status: String,
    val channel: NotificationChannel,
    val scheduledAt: java.time.Instant? = null
)

/**
 * Notification status response DTO.
 */
data class NotificationStatusResponse(
    val notificationId: String,
    val status: NotificationDeliveryStatus,
    val deliveredAt: java.time.Instant? = null,
    val failureReason: String? = null
)

enum class NotificationChannel { EMAIL, SMS, PUSH, WEBHOOK }
enum class NotificationPriority { LOW, NORMAL, HIGH, URGENT }
enum class NotificationDeliveryStatus { PENDING, SENT, DELIVERED, FAILED, BOUNCED }
