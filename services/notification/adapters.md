# Notification Service - Adapters Definition

> Language: Python | Role: Event-driven notification delivery, ML-driven delivery optimization

## Inbound Adapters

### gRPC Handler

- **Maps to:** None (the Notification service does not expose a gRPC server)
- **Description:** The Notification service is an event-driven consumer and does not expose a gRPC server interface. All notification triggers are received as domain events from the Kafka event backbone, and the `SendNotificationPort` is invoked internally by the event consumer adapter. This design simplifies the service's deployment model and reduces the attack surface, as there are no directly accessible network endpoints. If a synchronous notification API is needed in the future (for example, for real-time in-app notification delivery), a gRPC server adapter can be added without modifying the core business logic, following the hexagonal architecture principle.

### REST Controller

- **Maps to:** `/api/v1/notifications/*` (limited administrative endpoints only)
- **OpenAPI Path Prefix:** `/api/v1/notifications`
- **Description:** The Notification service exposes a minimal REST API for administrative and webhook purposes only. The primary endpoints are: `POST /api/v1/notifications/webhooks/{provider}` for receiving delivery tracking callbacks from external providers (SendGrid, Twilio, Firebase), `GET /api/v1/notifications/{id}/status` for querying the delivery status of a notification (maps to `GetDeliveryStatusPort`), and `POST /api/v1/notifications/send` for direct notification submission (maps to `SendNotificationPort`, used only by internal admin tools). The REST controller is implemented using FastAPI with automatic OpenAPI spec generation and Pydantic models for request/response validation. Webhook endpoints validate the provider's signature to prevent spoofing, and they process events asynchronously by publishing them to an internal processing queue. The REST server runs on port 8080 with TLS, but only the webhook endpoints are exposed through the Gateway; the send and status endpoints are restricted to internal service mesh access.

### Event Consumer

- **Maps to:** `com.company.order.confirmed`, `com.company.order.cancelled`, `com.company.order.completed`, `com.company.payment.processed`, `com.company.payment.refunded`, `com.company.payment.failed`, `com.company.catalog.inventory-low`
- **Description:** The event consumer adapter is the primary entry point for the Notification service, subscribing to multiple domain event topics and triggering notification delivery based on event content. Each event type maps to a notification template and a set of delivery rules: order confirmation events trigger an email and push notification to the customer, payment processed events trigger an email receipt, inventory low events trigger an internal webhook notification to the procurement team, and so on. The consumer is implemented using the `confluent-kafka-python` library with a committed consumer group (`notification-event-consumer`). Event processing follows a multi-step pipeline: event parsing and validation, notification template selection (based on event type and recipient preferences), template rendering via `TemplateEnginePort`, delivery optimization via the ML model, and execution via `DeliveryProviderPort`. Each step is idempotent and can be retried independently. Failed events are retried three times with exponential backoff and then forwarded to the `notification.events.dlq` dead letter topic. The consumer supports parallel processing with a configurable concurrency limit (default: 20 concurrent notifications) to prevent overloading the delivery providers.

## Outbound Adapters

### Persistence Adapter

- **Database:** PostgreSQL 16 with SQLAlchemy ORM and Alembic migrations
- **ORM/Query Approach:** SQLAlchemy ORM with async session support, Alembic for schema migrations
- **Description:** The persistence adapter uses SQLAlchemy's async ORM for all database operations in the Notification service. The async session support is critical for the event-driven architecture, where a single consumer task may need to write multiple notification records and tracking events concurrently. The adapter defines models for notifications, tracking events, templates, recipient preferences, and ML model parameters. Alembic manages schema migrations, with automatic migration generation during development and validated migration scripts for production deployments. The adapter uses PostgreSQL's JSONB type for flexible template metadata and ML model parameter storage, and the `INSERT ... ON CONFLICT DO UPDATE` pattern for upserting tracking events (which may be received multiple times from delivery provider webhooks). Connection pooling is configured with a maximum of 20 async connections, and the adapter includes a circuit breaker for the database connection that degrades gracefully during PostgreSQL outages by queuing notifications for later delivery.

### Messaging Adapter

- **Kafka Topics:**
  - **Produced:** `com.company.notification.sent`, `com.company.notification.delivered`, `com.company.notification.opened`, `com.company.notification.failed`
  - **Consumed:** `com.company.order.confirmed`, `com.company.order.cancelled`, `com.company.order.completed`, `com.company.payment.processed`, `com.company.payment.refunded`, `com.company.payment.failed`, `com.company.catalog.inventory-low`
- **Serialization:** Protobuf for produced events, CloudEvents JSON for consumed events (for flexibility with polyglot producers)
- **Description:** The messaging adapter handles all Kafka interactions for the Notification service. Produced events are notification lifecycle events that track the delivery pipeline: sent (the notification has been submitted to the delivery provider), delivered (the provider confirmed delivery), opened (the recipient opened the notification), and failed (the delivery permanently failed after all retries). These events are consumed by the Analytics service for delivery metric calculation and by the ML model training pipeline for delivery optimization. Consumed events are domain events from other services that trigger notification delivery. The adapter uses the `confluent-kafka-python` library with the transactional producer API for produced events and a committed consumer group for consumed events. The consumer implements a cooperative-sticky partition assignment strategy for balanced consumption across multiple Notification service instances.

### External Service Adapter

- **External Dependencies:** SendGrid (email), Twilio (SMS), Firebase Cloud Messaging (push), custom webhook endpoints
- **Behind ACL:** Yes (ACL sidecar recommended for all external provider communication)
- **Description:** The external service adapter manages communication with multiple external notification delivery providers. Each provider has a dedicated implementation that translates the rendered notification content into the provider's API format: SendGrid's Mail Send API for email, Twilio's Messages API for SMS, Firebase's HTTP v1 API for push notifications, and standard HTTP POST for webhooks. The adapter includes a provider selection strategy that can route notifications to different providers based on cost, reliability, and geographic considerations. An ACL sidecar is recommended for all external provider communication to provide circuit breaking (preventing cascade failures when a provider is down), rate limiting (respecting provider API limits), and vendor SDK isolation (preventing proprietary imports from leaking into the core service code). The adapter implements a fallback mechanism: if the primary provider fails, the notification is automatically routed to a secondary provider if one is configured.

### Observability Adapter

- **OTel Instrumentation Points:**
  - **Notification Pipeline Tracing:** Each notification processing pipeline creates a root span that spans the entire lifecycle from event consumption to delivery confirmation. Sub-spans track template rendering, delivery optimization inference, provider submission, and webhook processing.
  - **Delivery Provider Metrics:** Counter metrics for provider submissions (`notification.provider.submissions_total` with labels: provider, channel, result), histogram metrics for provider latency (`notification.provider.latency` with labels: provider, channel), and gauge metrics for provider rate limits (`notification.provider.rate_limit_remaining` with labels: provider).
  - **Notification Metrics:** Counter metrics for notification states (`notification.states_total` with labels: channel, status), histogram metrics for delivery duration (`notification.delivery.duration` with labels: channel), gauge metrics for pending notifications (`notification.pending` with labels: channel, priority), and counter metrics for tracking events (`notification.tracking.events_total` with labels: event_type, channel).
  - **ML Model Metrics:** Gauge metrics for model accuracy (`notification.ml.model_accuracy` with labels: model_version), counter metrics for inference calls (`notification.ml.inferences_total` with labels: result), and histogram metrics for inference latency (`notification.ml.inference_duration`).
- **Description:** The observability adapter uses the `opentelemetry-api` and `opentelemetry-sdk` Python packages for automatic and manual instrumentation. Auto-instrumentation covers HTTP (FastAPI), Kafka (confluent-kafka), and database (SQLAlchemy) operations. Manual spans are added for template rendering, ML model inference, and delivery provider interactions. The adapter implements a custom span processor that adds notification-specific attributes (notification ID, channel, template ID) to all spans within a notification processing context. Structured logs use Python's `logging` module with a JSON formatter and OTel trace context injection.
