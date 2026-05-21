# Notification Service - Contracts Definition

> Language: Python | Role: Event-driven notification delivery, ML-driven delivery optimization

## gRPC Contract

The Notification service does not expose a gRPC server. All notification operations are triggered by consuming domain events from the Kafka event backbone. The `SendNotificationPort` is invoked internally by the event consumer adapter, and the `GetDeliveryStatusPort` is exposed only through the REST API for administrative use.

If a gRPC interface is required in the future for synchronous notification delivery (for example, to support real-time in-app notification streaming), the following service definition would be appropriate:

```protobuf
package notification.v1;

service NotificationService {
  rpc Send(SendNotificationRequest) returns (SendNotificationResponse);
  rpc GetStatus(GetDeliveryStatusRequest) returns (GetDeliveryStatusResponse);
  rpc StreamNotifications(StreamNotificationsRequest) returns (stream NotificationEvent);
}
```

However, this contract is not currently implemented and should not be considered active.

## OpenAPI Contract

### API Path Prefix

`/api/v1/notifications`

### Endpoints

| Method | Path | Request Body | Response | Auth Required |
|---|---|---|---|---|
| `POST` | `/api/v1/notifications/webhooks/{provider}` | Provider-specific webhook payload | 200 OK | Provider signature |
| `GET` | `/api/v1/notifications/{id}/status` | None | `DeliveryStatusResponse` JSON | Yes (internal) |
| `POST` | `/api/v1/notifications/send` | `SendNotificationRequest` JSON | `SendNotificationResponse` JSON | Yes (admin) |
| `GET` | `/api/v1/notifications` | None (query params) | Paginated notification list | Yes (internal) |

### Endpoint Details

**POST /webhooks/{provider}:**
Receives delivery tracking callbacks from external notification providers. The `{provider}` path segment identifies the provider (sendgrid, twilio, firebase). The request body format varies by provider and is parsed by the provider-specific webhook handler. The endpoint validates the provider's signature header to prevent spoofing. Processing is asynchronous: the webhook event is published to an internal processing queue and a 200 OK is returned immediately. Duplicate webhook events are deduplicated using the event ID provided by the provider.

**GET /{id}/status:**
Returns the delivery status of a notification, including the full tracking timeline. This endpoint is restricted to internal service mesh access and is not exposed through the Gateway. It maps to `GetDeliveryStatusPort`.

**POST /send:**
Directly sends a notification, bypassing the event-driven pipeline. This endpoint is restricted to administrative use and requires the `notification:admin` scope. It maps to `SendNotificationPort`. The request body specifies the recipient, channel, template, and template variables. This endpoint is intended for manual notification dispatch (such as system alerts or marketing campaigns) and should not be used for automated transactional notifications, which should be triggered by domain events.

**GET /notifications:**
Lists notifications for a recipient or correlation ID. Supports query parameters `?recipient_id=abc&correlation_id=xyz&status=DELIVERED&page_size=20`. Returns a paginated list of notification summaries. This endpoint is restricted to internal service mesh access.

### Authentication Requirements

- Webhook endpoints authenticate using the provider's signature mechanism (not JWT/mTLS)
- All other endpoints require internal service mesh authentication (mTLS with SPIFFE SVID)
- The `POST /send` endpoint additionally requires a JWT with the `notification:admin` scope
- Rate limiting is applied per provider for webhook endpoints and per service for internal endpoints

## Event Contracts

### CloudEvents Type Prefix

`com.company.notification.`

### Consumed Event Types

The Notification service subscribes to domain events from multiple services, mapping each event type to a notification template and delivery rule:

| Consumed Event Type | Triggered Notification | Channel | Template ID | Priority |
|---|---|---|---|---|
| `com.company.order.confirmed` | Order confirmation email | EMAIL, PUSH | `order-confirmation` | NORMAL |
| `com.company.order.cancelled` | Order cancellation notice | EMAIL, SMS | `order-cancellation` | HIGH |
| `com.company.order.completed` | Delivery confirmation | EMAIL, PUSH | `order-delivery` | NORMAL |
| `com.company.payment.processed` | Payment receipt | EMAIL | `payment-receipt` | NORMAL |
| `com.company.payment.refunded` | Refund confirmation | EMAIL, SMS | `payment-refund` | HIGH |
| `com.company.payment.failed` | Payment failure alert | EMAIL, PUSH | `payment-failure` | URGENT |
| `com.company.catalog.inventory-low` | Inventory low alert | WEBHOOK | `inventory-alert` | HIGH |

### Produced Event Types

| Event Type | Payload Schema | Consumer Services |
|---|---|---|
| `com.company.notification.sent` | `NotificationSentEvent` | Analytics |
| `com.company.notification.delivered` | `NotificationDeliveredEvent` | Analytics |
| `com.company.notification.opened` | `NotificationOpenedEvent` | Analytics |
| `com.company.notification.failed` | `NotificationFailedEvent` | Analytics |

### Event Details

**NotificationSentEvent:**
Emitted when a notification has been successfully submitted to the external delivery provider. The payload includes the notification ID, channel, recipient identifier, template ID, and the submission timestamp. This event does not guarantee delivery; it only confirms that the provider accepted the notification for processing. The Analytics service consumes this event to track send volumes and provider acceptance rates.

**NotificationDeliveredEvent:**
Emitted when the external delivery provider confirms that the notification has been delivered to the recipient's device or inbox. The payload includes the notification ID, channel, delivery timestamp, and any provider-specific metadata (such as the SMTP response code for email). This event is received asynchronously via the provider's webhook callback. The Analytics service uses delivery events to calculate delivery rates and latency percentiles.

**NotificationOpenedEvent:**
Emitted when the recipient opens the notification (for channels that support open tracking, primarily email). The payload includes the notification ID, channel, open timestamp, user agent, and IP address (subject to privacy controls). Open tracking uses a transparent tracking pixel for email and deep link wrappers for push notifications. The Analytics service uses open events to calculate open rates and to train the ML delivery optimization model.

**NotificationFailedEvent:**
Emitted when a notification permanently fails to deliver after all retries have been exhausted. The payload includes the notification ID, channel, failure reason (e.g., bounced email, invalid phone number, uninstalled app), and the final error message. The Analytics service tracks failure rates and reasons for delivery quality monitoring. Failed notifications are stored with a FAILED status and can be manually retried through the administrative REST API.

### ML Delivery Optimization Model

The Notification service includes an ML model that optimizes delivery timing for low and normal priority notifications. The model is trained on historical delivery data (open rates by time of day, day of week, channel, and recipient segment) and outputs an optimal delivery time window for each notification. The model parameters are:

- **Input Features:** recipient timezone, recipient open history, channel, day of week, hour of day, notification category
- **Output:** optimal delivery window (start timestamp, end timestamp) and predicted open probability
- **Training Data:** `NotificationDeliveredEvent` and `NotificationOpenedEvent` events from the past 90 days
- **Retraining Schedule:** Daily, using a batch training pipeline that runs during off-peak hours
- **Model Storage:** PostgreSQL JSONB column in the `delivery_models` table, versioned for A/B testing
