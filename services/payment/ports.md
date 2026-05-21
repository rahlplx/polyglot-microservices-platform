# Payment Service - Ports Definition

> Language: Go | Role: Payment processing with ACL sidecar, Circuit Breaker pattern

## Inbound Ports (Driving / Use Case Interfaces)

### ProcessPaymentPort

- **Port Name:** `ProcessPaymentPort`
- **Input Type:** `ProcessPaymentRequest` (order_id: string, amount: Money, payment_method: PaymentMethod, idempotency_key: string, customer_id: string, metadata: map<string,string>)
- **Output Type:** `ProcessPaymentResponse` (payment_id: string, status: PaymentStatus, authorization_code: optional<string>, gateway_reference: optional<string>, processed_at: timestamp)
- **Error Types:** `PaymentDeclinedError`, `PaymentMethodInvalidError`, `DuplicatePaymentError`, `GatewayUnavailableError`, `AmountValidationError`, `FraudSuspectedError`
- **Description:** Processes a payment request by communicating with the external payment gateway through the ACL sidecar. The port implements a three-phase payment model: authorization (reserving the funds), capture (collecting the reserved funds), and settlement (reconciling with the gateway). The initial call performs authorization only; capture is triggered separately by the Order service when the order is confirmed. The port includes comprehensive validation before gateway submission: amount must be positive and within per-transaction limits, the payment method must be active and support the given currency, and the idempotency key is checked to prevent duplicate charges. If the external gateway is unavailable (detected via the circuit breaker), the port returns a `GatewayUnavailableError` rather than failing silently, allowing the Order service's saga to suspend and retry later. All payment operations are logged with full audit trails, and sensitive data (card numbers, CVVs) is redacted from all logs and event payloads.

### RefundPaymentPort

- **Port Name:** `RefundPaymentPort`
- **Input Type:** `RefundPaymentRequest` (payment_id: string, amount: Money, reason: enum [CUSTOMER_REQUEST, ORDER_CANCELLED, FRAUD_REVERSAL, SYSTEM_ERROR, PARTIAL_RETURN], reference_id: string, initiated_by: string)
- **Output Type:** `RefundPaymentResponse` (refund_id: string, payment_id: string, refund_amount: Money, remaining_captured: Money, status: RefundStatus, estimated_settlement: timestamp)
- **Error Types:** `PaymentNotFoundError`, `RefundExceedsCapturedError`, `PaymentNotCapturedError`, `GatewayUnavailableError`, `DuplicateRefundError`
- **Description:** Initiates a refund for a previously captured payment through the external payment gateway via the ACL sidecar. The port supports both full and partial refunds, tracking the remaining captured amount to prevent over-refunding. Multiple partial refunds are allowed up to the total captured amount, and each refund is assigned a unique refund ID for tracking. The `reference_id` links the refund to the originating order cancellation or return request for audit traceability. The port validates that the payment exists and has been captured (you cannot refund an authorization that has not been captured), and that the requested refund amount does not exceed the remaining captured balance. If the external gateway is unavailable, the refund is recorded in a pending state and will be submitted to the gateway when connectivity is restored, ensuring that refunds are never lost.

### GetPaymentStatusPort

- **Port Name:** `GetPaymentStatusPort`
- **Input Type:** `GetPaymentStatusRequest` (payment_id: string, include_gateway_status: bool)
- **Output Type:** `GetPaymentStatusResponse` (payment_id: string, order_id: string, status: PaymentStatus, authorized_amount: Money, captured_amount: Money, refunded_amount: Money, currency: string, gateway_reference: optional<string>, created_at: timestamp, updated_at: timestamp, gateway_status: optional<GatewayStatusDetail>)
- **Error Types:** `PaymentNotFoundError`
- **Description:** Retrieves the current status of a payment, including a breakdown of authorized, captured, and refunded amounts. When `include_gateway_status` is true, the port queries the external gateway (via the ACL sidecar) to obtain the real-time status, which may differ from the locally tracked status due to asynchronous settlement or manual gateway operations. The response includes the gateway status detail only when requested, as the external call adds latency. The port first checks the local database for the payment record, then optionally enriches it with gateway data. If the gateway is unavailable when `include_gateway_status` is true, the port returns the local status with a warning that the gateway status could not be obtained. This design ensures that the Order service can always check payment status, even when the external gateway is experiencing an outage.

## Outbound Ports (Driven / Infrastructure Interfaces)

### ListTransactionsPort

- **Port Name:** `ListTransactionsPort`
- **Input Type:** `ListTransactionsRequest` (customer_id: optional<string>, order_id: optional<string>, status: optional<PaymentStatus>, start_date: optional<timestamp>, end_date: optional<timestamp>, page_size: int32, page_token: string)
- **Output Type:** `ListTransactionsResponse` (transactions: list<TransactionSummary>, total_count: int64, next_page_token: string)
- **Error Types:** `InvalidQueryError`, `PageTokenExpiredError`
- **Description:** Lists payment transactions with flexible filtering and pagination support. The port supports filtering by customer ID (returning all payment activity for a specific customer), by order ID (returning all payments associated with a specific order), by status (returning payments in a specific state such as AUTHORIZED or CAPTURED), and by date range (returning payments created or updated within a specified time window). Multiple filters can be combined to create precise queries, such as "all FAILED payments for customer X in the last 30 days." The port uses cursor-based pagination with opaque page tokens that encode the last seen payment ID and sort position, ensuring consistent results even when new payments are created between page fetches. The response includes a summary of each transaction (payment ID, order ID, amount, status, created timestamp) rather than the full payment details, optimizing for list-view performance. Full payment details including the complete state history can be retrieved via the `GetPaymentStatusPort` using the payment IDs from the summary list. This port is primarily used by the administrative payment dashboard and by financial reconciliation processes that need to enumerate payments for reporting.

### PaymentRepositoryPort

- **Port Name:** `PaymentRepositoryPort`
- **Operations:**
  - `Save(payment: Payment) -> Payment`: Persists a payment record with all state transitions.
  - `FindById(payment_id: string) -> optional<Payment>`: Retrieves a payment by ID with full history.
  - `FindByOrderId(order_id: string) -> list<Payment>`: Retrieves all payments for an order.
  - `FindByReference(gateway_reference: string) -> optional<Payment>`: Looks up a payment by its external gateway reference.
  - `SaveRefund(refund: Refund) -> Refund`: Persists a refund record linked to its parent payment.
  - `FindPendingOperations() -> list<PendingOperation>`: Retrieves all operations pending gateway submission.
- **Technology:** PostgreSQL with pgx driver and custom SQL
- **ACL Required:** No (internal data store)
- **Description:** The payment repository port manages all persistent data for the Payment service, including payment records, refund records, and pending operation queues. Each payment record includes a state machine that tracks the payment through its lifecycle: PENDING, AUTHORIZED, CAPTURED, PARTIALLY_REFUNDED, FULLY_REFUNDED, VOIDED, and FAILED. State transitions are validated against the allowed transition graph to prevent invalid state changes (e.g., you cannot capture a payment that has not been authorized). The repository uses PostgreSQL's advisory locks for concurrent payment processing, preventing two goroutines from processing the same payment simultaneously. The pending operations table stores gateway operations that could not be submitted due to gateway unavailability, enabling reliable retry when connectivity is restored.

### ExternalPaymentGatewayPort

- **Port Name:** `ExternalPaymentGatewayPort`
- **Operations:**
  - `Authorize(request: GatewayAuthRequest) -> GatewayAuthResponse`: Submits an authorization to the external gateway.
  - `Capture(request: GatewayCaptureRequest) -> GatewayCaptureResponse`: Captures a previously authorized payment.
  - `Refund(request: GatewayRefundRequest) -> GatewayRefundResponse`: Submits a refund to the external gateway.
  - `Void(request: GatewayVoidRequest) -> GatewayVoidResponse`: Voids an uncaptured authorization.
  - `GetStatus(gateway_reference: string) -> GatewayStatusResponse`: Queries the real-time status from the gateway.
- **Technology:** External payment gateway (vendor-specific, behind ACL sidecar)
- **ACL Required:** Yes (mandatory ACL sidecar for all external communication)
- **Description:** The external payment gateway port provides the interface to the third-party payment processor, which is the only external dependency in the system. This port is always accessed through the ACL sidecar, which provides circuit breaking, retry with jitter, rate limiting, and proprietary import blocking. The sidecar translates the domain-oriented request format into the vendor-specific API format, isolating the Payment service from vendor lock-in. If the payment gateway vendor is changed in the future, only the ACL sidecar's translation layer needs to be updated; the Payment service's core logic remains unchanged. The port includes idempotency keys on all write operations to handle the at-least-once delivery semantics of the retry mechanism, ensuring that duplicate submissions do not result in duplicate charges.

### EventPublisherPort

- **Port Name:** `EventPublisherPort`
- **Operations:**
  - `Publish(event: DomainEvent) -> void`: Publishes a payment domain event to the event backbone.
  - `PublishBatch(events: list<DomainEvent>) -> void`: Publishes multiple events atomically.
- **Technology:** Apache Kafka (Transactional Producer API)
- **ACL Required:** No (internal infrastructure)
- **Description:** The event publisher port handles all outbound event production for the Payment service. Events are published using the transactional outbox pattern: the event is first written to a PostgreSQL outbox table in the same transaction as the payment state change, then a relay process publishes it to Kafka. This guarantees that the payment database state and the event stream are always consistent. Payment events are among the most critical in the system because they drive downstream financial reporting, order state transitions, and customer notifications. The port includes a fallback direct-publish mechanism for infrastructure events that do not need transactional consistency.
