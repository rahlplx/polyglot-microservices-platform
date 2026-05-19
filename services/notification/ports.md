# Notification Service - Ports Definition

> Language: Python | Role: Event-driven notification delivery, ML-driven delivery optimization

## Inbound Ports (Driving / Use Case Interfaces)

### SendNotificationPort

- **Port Name:** `SendNotificationPort`
- **Input Type:** `SendNotificationRequest` (recipient: Recipient, channel: enum [EMAIL, SMS, PUSH, WEBHOOK], template_id: string, template_vars: map<string,string>, priority: enum [LOW, NORMAL, HIGH, URGENT], scheduled_at: optional<timestamp>, correlation_id: string)
- **Output Type:** `SendNotificationResponse` (notification_id: string, status: NotificationStatus, scheduled_delivery: optional<timestamp>, estimated_delivery: timestamp)
- **Error Types:** `TemplateNotFoundError`, `RecipientOptedOutError`, `ChannelUnavailableError`, `RateLimitExceededError`, `InvalidTemplateVarsError`
- **Description:** The primary use case for sending notifications through any supported channel. The port receives a notification request specifying the recipient, channel, template, and template variables, then orchestrates the delivery pipeline. The pipeline includes template rendering (substituting variables into the template), delivery optimization (using the ML model to determine the optimal delivery time if not explicitly scheduled), channel-specific formatting (converting the rendered template to the appropriate format for email, SMS, push, or webhook), and delivery execution (sending the formatted message through the delivery provider). The port respects recipient opt-out preferences: if a recipient has opted out of the specified channel, the notification is silently discarded and a `RecipientOptedOutError` is returned. High-priority and urgent notifications bypass the delivery optimization model and are sent immediately, while low and normal priority notifications may be delayed by the model to maximize open rates. The `correlation_id` field links the notification to the originating domain event for end-to-end traceability.

### GetDeliveryStatusPort

- **Port Name:** `GetDeliveryStatusPort`
- **Input Type:** `GetDeliveryStatusRequest` (notification_id: string, include_tracking_details: bool)
- **Output Type:** `GetDeliveryStatusResponse` (notification_id: string, status: DeliveryStatus, channel: string, recipient: string, sent_at: optional<timestamp>, delivered_at: optional<timestamp>, opened_at: optional<timestamp>, clicked_at: optional<timestamp>, bounced_at: optional<timestamp>, tracking_details: optional<list<TrackingEvent>>)
- **Error Types:** `NotificationNotFoundError`
- **Description:** Retrieves the delivery status of a previously sent notification, including the full tracking timeline if requested. The tracking details include every tracking event received from the delivery provider: sent, delivered, opened, clicked, bounced, complained, and unsubscribed. These events are received asynchronously from the delivery provider via webhook callbacks and stored in the notification repository. The port aggregates these events into a coherent timeline, deduplicating events that may be sent multiple times by the provider. The response includes the timestamp of each tracking event and, for open and click events, additional metadata such as the user agent and IP address (subject to privacy controls). This port is used primarily by the analytics pipeline to calculate delivery metrics and by customer support tools to investigate delivery issues.

## Outbound Ports (Driven / Infrastructure Interfaces)

### GetNotificationPreferencesPort

- **Port Name:** `GetNotificationPreferencesPort`
- **Input Type:** `GetNotificationPreferencesRequest` (recipient_id: string, channel: optional<enum [EMAIL, SMS, PUSH, WEBHOOK]>)
- **Output Type:** `GetNotificationPreferencesResponse` (recipient_id: string, preferences: list<ChannelPreference>, global_opt_out: bool, quiet_hours: optional<QuietHours>, timezone: string)
- **Error Types:** `RecipientNotFoundError`, `PreferencesNotConfiguredError`
- **Description:** Retrieves the notification preferences for a specific recipient, including per-channel opt-in/opt-out status, quiet hours configuration, and timezone settings. The port returns the recipient's current communication preferences, which control whether notifications are delivered, suppressed, or deferred based on the recipient's explicit choices. Each channel preference includes whether the channel is enabled, the maximum notification frequency allowed by the recipient, and any category-specific overrides (for example, a recipient may opt out of marketing emails but remain opted in to transactional emails). The `quiet_hours` configuration specifies a time window during which non-urgent notifications are held and delivered after the quiet period ends, respecting the recipient's desired communication schedule. The `global_opt_out` flag indicates that the recipient has opted out of all non-essential communications, in which case only legally required notifications (such as payment receipts and security alerts) will be delivered. This port is called by the `SendNotificationPort` before delivering any notification to verify that the recipient has not opted out of the specified channel.

### TemplateEnginePort

- **Port Name:** `TemplateEnginePort`
- **Operations:**
  - `Render(template_id: string, variables: map<string,string>) -> RenderedTemplate`: Renders a notification template with the given variables.
  - `Validate(template_id: string, variables: map<string,string>) -> ValidationResult`: Validates that all required template variables are provided.
  - `GetTemplate(template_id: string) -> Template`: Retrieves the raw template definition.
  - `ListTemplates(channel: optional<string>) -> list<TemplateSummary>`: Lists available templates, optionally filtered by channel.
- **Technology:** Jinja2 template engine with PostgreSQL template storage
- **ACL Required:** No (internal component)
- **Description:** The template engine port manages notification template rendering and validation. Templates are stored in PostgreSQL as Jinja2 templates with metadata (channel, locale, required variables, and version history). The rendering operation substitutes the provided variables into the template and returns the rendered content in a channel-appropriate format. The validation operation checks that all required variables are present and that optional variables have valid default values, returning detailed error messages for any missing or invalid variables. The engine supports template inheritance (base templates with channel-specific overrides), conditional sections (showing different content based on variable values), and locale-specific templates (using the recipient's preferred language). Template versioning ensures that in-flight notifications continue to use the template version that was active when the notification was created, preventing rendering errors due to template changes.

### DeliveryProviderPort

- **Port Name:** `DeliveryProviderPort`
- **Operations:**
  - `Send(request: DeliveryRequest) -> DeliveryResponse`: Sends a notification through the delivery provider.
  - `GetDeliveryStatus(provider_id: string) -> ProviderDeliveryStatus`: Queries the provider for delivery status.
  - `ProcessWebhook(event: WebhookEvent) -> void`: Processes a webhook callback from the delivery provider.
- **Technology:** External delivery providers (e.g., SendGrid for email, Twilio for SMS, Firebase for push)
- **ACL Required:** Yes (ACL sidecar recommended for external provider communication)
- **Description:** The delivery provider port abstracts the interface to external notification delivery services such as SendGrid (email), Twilio (SMS), Firebase Cloud Messaging (push), and custom webhook endpoints. Each channel has its own provider implementation that translates the rendered notification content into the provider's API format. The port includes retry logic with exponential backoff for transient failures, and a dead letter mechanism for permanent failures (such as invalid email addresses or unsubscribed phone numbers). Webhook callbacks from the providers are received via a dedicated HTTP endpoint and processed asynchronously, updating the notification's tracking status in the repository. An ACL sidecar is recommended for external provider communication to isolate the service from vendor-specific SDKs and to provide circuit breaking for provider outages.

### NotificationRepositoryPort

- **Port Name:** `NotificationRepositoryPort`
- **Operations:**
  - `Save(notification: Notification) -> Notification`: Persists a notification record with its current status.
  - `FindById(notification_id: string) -> optional<Notification>`: Retrieves a notification by ID.
  - `FindByCorrelationId(correlation_id: string) -> list<Notification>`: Retrieves all notifications linked to a correlation ID.
  - `FindByRecipient(recipient_id: string, page: PageRequest) -> Page<Notification>`: Retrieves paginated notifications for a recipient.
  - `AppendTrackingEvent(event: TrackingEvent) -> void`: Appends a tracking event to a notification.
  - `FindPendingRetry(limit: int) -> list<Notification>`: Retrieves notifications pending retry delivery.
  - `SaveDeliveryOptimization(model: DeliveryModel) -> void`: Persists the ML model's learned parameters.
- **Technology:** PostgreSQL with SQLAlchemy ORM
- **ACL Required:** No (internal data store)
- **Description:** The notification repository port manages all persistent data for the Notification service, including notification records, tracking events, template definitions, and the ML delivery optimization model parameters. Each notification record includes its current delivery status, the rendered content, the channel, the recipient, and the correlation ID linking it to the originating event. Tracking events are stored in a separate table with a foreign key to the notification, enabling efficient time-series queries for delivery analytics. The ML model parameters are stored as JSONB in a dedicated table, with versioning to support A/B testing of different model configurations. The repository uses PostgreSQL's LISTEN/NOTIFY feature to trigger real-time processing of new notifications without polling.
