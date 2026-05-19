# Order Service - Ports Definition

> Language: Java/Kotlin | Role: Saga orchestration, Transactional Outbox Pattern

## Inbound Ports (Driving / Use Case Interfaces)

### CreateOrderPort

- **Port Name:** `CreateOrderPort`
- **Input Type:** `CreateOrderRequest` (customer_id: string, items: list<OrderLineItem>, shipping_address: Address, payment_method_id: string, idempotency_key: string)
- **Output Type:** `CreateOrderResponse` (order_id: string, status: OrderStatus, estimated_total: Money, created_at: timestamp, reservation_ids: list<string>)
- **Error Types:** `InsufficientStockError`, `ProductNotFoundError`, `PaymentMethodInvalidError`, `DuplicateOrderError`, `ShippingAddressValidationError`
- **Description:** Creates a new order by orchestrating a multi-step saga that spans the Catalog and Payment services. The saga begins by reserving inventory for all line items via the CatalogClient port, then proceeds to authorize payment via the PaymentClient port, and finally persists the order in the CONFIRMED state. If any step fails, the saga executes compensating actions: inventory reservations are released and payment authorizations are voided. The entire saga is tracked in a saga state machine that persists its progress to the database, enabling recovery from partial failures. The `idempotency_key` field ensures that duplicate submission attempts (common in mobile clients with unreliable networks) return the original order rather than creating a duplicate. The response includes the estimated total (which may differ from the final total if prices change between order creation and completion) and the reservation IDs that can be used to track inventory holds.

### GetOrderPort

- **Port Name:** `GetOrderPort`
- **Input Type:** `GetOrderRequest` (order_id: string, include_history: bool)
- **Output Type:** `GetOrderResponse` (order: Order, history: optional<list<OrderStatusChange>>, payment_summary: optional<PaymentSummary>)
- **Error Types:** `OrderNotFoundError`, `OrderAccessDeniedError`
- **Description:** Retrieves the full details of an order by its ID. When `include_history` is true, the response includes a complete status change timeline showing every state transition with timestamps and triggering events. When the order has an associated payment, the payment summary includes the authorized amount, captured amount, and any refund totals. The port enforces access control: customers can only retrieve their own orders, while internal services can retrieve any order. Order data is cached in Redis for 30 seconds to reduce database load during order status polling (common immediately after order placement when customers are watching for confirmation).

### CancelOrderPort

- **Port Name:** `CancelOrderPort`
- **Input Type:** `CancelOrderRequest` (order_id: string, reason: enum [CUSTOMER_REQUEST, PAYMENT_FAILED, INVENTORY_UNAVAILABLE, SYSTEM_ERROR, FRAUD_DETECTED], cancelled_by: string, refund_requested: bool)
- **Output Type:** `CancelOrderResponse` (order_id: string, previous_status: OrderStatus, new_status: OrderStatus, refund_initiated: bool, cancelled_at: timestamp)
- **Error Types:** `OrderNotFoundError`, `OrderNotCancellableError`, `CancellationAlreadyInProgressError`
- **Description:** Cancels an existing order, executing the cancellation saga that reverses all completed saga steps. The cancellation logic varies by the order's current state: if the order is in CREATED or CONFIRMED state, inventory reservations are simply released; if the order is in PROCESSING state, the cancellation must also void or refund any captured payments; if the order is in SHIPPED state, cancellation is not possible and the customer must initiate a return instead. The port publishes an `order.cancelled` domain event upon successful cancellation, which triggers downstream processes such as inventory release, payment refund, and customer notification. The `refund_requested` flag is automatically set to true for any cancellation that requires a payment reversal, ensuring that customers are not charged for cancelled orders.

### CompleteOrderPort

- **Port Name:** `CompleteOrderPort`
- **Input Type:** `CompleteOrderRequest` (order_id: string, tracking_number: optional<string>, delivery_confirmation: optional<DeliveryConfirmation>)
- **Output Type:** `CompleteOrderResponse` (order_id: string, status: OrderStatus, completed_at: timestamp, final_total: Money)
- **Error Types:** `OrderNotFoundError`, `OrderNotCompletableError`, `PaymentNotCapturedError`
- **Description:** Marks an order as completed after fulfillment and delivery confirmation. The port validates that the order is in a completable state (PROCESSING or SHIPPED) and that all payments have been fully captured. If the final total differs from the estimated total (due to partial shipments or price adjustments), the port initiates a payment adjustment to capture or refund the difference. Upon completion, the port publishes an `order.completed` domain event, which is one of the most important events in the system as it triggers payment finalization, customer notification, analytics recording, and inventory finalization (converting reservations to permanent deductions). The port also archives the saga state machine for audit purposes, retaining the full execution trace of every step and compensation.

### ListOrdersPort

- **Port Name:** `ListOrdersPort`
- **Input Type:** `ListOrdersRequest` (customer_id: optional<string>, status: optional<OrderStatus>, created_after: optional<timestamp>, created_before: optional<timestamp>, page_size: int32, page_token: string, sort_by: enum [CREATED_AT_DESC, CREATED_AT_ASC, UPDATED_AT_DESC, TOTAL_DESC])
- **Output Type:** `ListOrdersResponse` (orders: list<OrderSummary>, total_count: int64, next_page_token: string)
- **Error Types:** `InvalidQueryError`, `PageTokenExpiredError`
- **Description:** Lists orders with flexible filtering and pagination support. The port supports filtering by customer ID (returning all orders for a specific customer), by status (returning all orders in a given state), and by creation date range (returning orders created within a specified time window). Multiple filters can be combined, enabling queries such as "all CONFIRMED orders for customer X created in the last 7 days." The port uses cursor-based pagination with opaque page tokens, which provide consistent results even when new orders are created or existing orders change status between page fetches. The `sort_by` parameter controls the ordering of results, with the default being most recent first. The response includes a summary of each order (ID, status, total, item count, created timestamp) rather than the full order details, optimizing for list-view performance. Full order details can be retrieved via the `GetOrderPort` using the order IDs from the summary list. This port is called by the customer-facing order history UI and by the administrative order management dashboard.

## Outbound Ports (Driven / Infrastructure Interfaces)

### OrderRepositoryPort

- **Port Name:** `OrderRepositoryPort`
- **Operations:**
  - `Save(order: Order) -> Order`: Persists an order with all line items and status history.
  - `FindById(order_id: string) -> optional<Order>`: Retrieves an order by ID with all related data.
  - `FindByCustomer(customer_id: string, page: PageRequest) -> Page<Order>`: Retrieves paginated orders for a customer.
  - `FindByStatus(status: OrderStatus, page: PageRequest) -> Page<Order>`: Retrieves orders in a specific state for processing.
  - `SaveSagaState(saga: SagaInstance) -> void`: Persists saga execution state for recovery.
  - `FindSagaByOrderId(order_id: string) -> optional<SagaInstance>`: Retrieves saga state for an order.
  - `AppendToOutbox(event: OutboxEntry) -> void`: Appends an event to the transactional outbox.
  - `ReadOutbox(limit: int) -> list<OutboxEntry>`: Reads unprocessed outbox entries for the relay.
  - `MarkOutboxProcessed(ids: list<string>) -> void`: Marks outbox entries as published.
- **Technology:** PostgreSQL with Hibernate/JPA and jOOQ for complex queries
- **ACL Required:** No (internal data store)
- **Description:** The order repository port manages all persistent data for the Order service, including orders, line items, saga state machines, and the transactional outbox. The outbox table is the cornerstone of the Transactional Outbox Pattern, ensuring that domain events are written to the database in the same transaction as the order data mutation, and a separate relay process publishes them to Kafka. This guarantees that the database state and the event stream are always consistent. The repository uses Hibernate for simple CRUD operations on the Order aggregate and jOOQ for complex queries involving joins, CTEs, and window functions for saga state analysis and outbox processing.

### EventPublisherPort

- **Port Name:** `EventPublisherPort`
- **Operations:**
  - `PublishFromOutbox(entries: list<OutboxEntry>) -> void`: Publishes outbox entries to Kafka and marks them as processed.
  - `PublishDirect(event: DomainEvent) -> void`: Publishes an event directly (for non-transactional events like saga step completion notifications).
- **Technology:** Apache Kafka (Transactional Producer API)
- **ACL Required:** No (internal infrastructure)
- **Description:** The event publisher port handles all outbound event production for the Order service. The primary publishing mechanism is the transactional outbox: events are first written to the `outbox` table in PostgreSQL within the same transaction as the order data change, then a relay process reads the outbox and publishes to Kafka. The relay runs as a scheduled task within the same JVM, polling the outbox every 100ms during active periods and backing off to 500ms during quiet periods. Direct publishing is used only for infrastructure events that do not need to be transactionally consistent with order data, such as saga step completion notifications for monitoring. All events are serialized using Protobuf and validated against the Schema Registry before publication.

### PaymentClientPort

- **Port Name:** `PaymentClientPort`
- **Operations:**
  - `AuthorizePayment(request: PaymentAuthorizationRequest) -> PaymentAuthorizationResponse`: Authorizes a payment for an order amount.
  - `CapturePayment(payment_id: string, amount: optional<Money>) -> CaptureResponse`: Captures a previously authorized payment.
  - `RefundPayment(payment_id: string, amount: Money, reason: string) -> RefundResponse`: Initiates a refund for a captured payment.
  - `VoidAuthorization(payment_id: string, reason: string) -> VoidResponse`: Voids an uncaptured authorization.
  - `GetPaymentStatus(payment_id: string) -> PaymentStatusResponse`: Retrieves the current status of a payment.
- **Technology:** gRPC to Payment Service
- **ACL Required:** No (internal service-to-service communication via mTLS)
- **Description:** The payment client port provides a synchronous interface to the Payment service for all payment operations required during order processing. The port is a critical dependency in the order creation and cancellation sagas, and its operations must be idempotent to handle saga retries. Each operation includes an idempotency key derived from the order ID and the saga step identifier, ensuring that duplicate calls (from saga retries) return the same result without double-charging or double-refunding. The port includes a circuit breaker that trips after 5 consecutive failures and resets after a 30-second cooldown, preventing cascading failures when the Payment service is degraded. When the circuit breaker is open, the saga is suspended and will be resumed by the saga recovery process once the circuit breaker resets.

### CatalogClientPort

- **Port Name:** `CatalogClientPort`
- **Operations:**
  - `ReserveInventory(request: InventoryReservationRequest) -> InventoryReservationResponse`: Reserves inventory for order line items.
  - `ReleaseInventory(reservation_ids: list<string>) -> ReleaseResponse`: Releases previously reserved inventory.
  - `GetProduct(product_id: string) -> ProductResponse`: Retrieves product details for order validation.
  - `ConfirmInventoryReservation(reservation_ids: list<string>) -> ConfirmResponse`: Converts temporary reservations to permanent deductions.
- **Technology:** gRPC to Catalog Service
- **ACL Required:** No (internal service-to-service communication via mTLS)
- **Description:** The catalog client port provides a synchronous interface to the Catalog service for inventory management during order processing. The reservation model is two-phase: inventory is first reserved (temporarily held) when an order is created, then confirmed (permanently deducted) when the order is completed, or released when the order is cancelled. Reservations have a configurable TTL (default: 30 minutes) after which they are automatically released by the Catalog service, preventing inventory from being held indefinitely by abandoned orders. The port includes the same circuit breaker and idempotency patterns as the PaymentClientPort, ensuring reliable saga execution even under partial system failures.

### NotificationClientPort

- **Port Name:** `NotificationClientPort`
- **Operations:**
  - `SendNotification(request: NotificationRequest) -> NotificationResponse`: Sends a notification to a customer or internal team via the Notification service.
  - `GetNotificationStatus(notification_id: string) -> NotificationStatusResponse`: Checks the delivery status of a previously sent notification.
- **Technology:** Asynchronous (via Kafka events, not gRPC)
- **ACL Required:** No (internal event-driven communication)
- **Description:** The notification client port provides an interface for the Order service to trigger customer notifications without directly calling the Notification service. Rather than using synchronous gRPC calls, the Order service relies on the event-driven architecture: it publishes domain events (order.created, order.confirmed, order.cancelled, order.completed) that the Notification service consumes and translates into appropriate customer communications. This port exists primarily as a conceptual boundary that documents the Order service's dependency on the Notification service, and as a fallback mechanism for scenarios where a notification must be triggered outside the normal event flow (such as an urgent fraud alert that bypasses the standard event pipeline). In the standard flow, no code directly invokes this port; instead, the Notification service's event consumer handles all notification triggers autonomously based on the domain events published by the Order service through the transactional outbox.
