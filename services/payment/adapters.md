# Payment Service - Adapters Definition

> Language: Go | Role: Payment processing with ACL sidecar, Circuit Breaker pattern

## Inbound Adapters

### gRPC Handler

- **Maps to:** `payment.v1.PaymentService`
- **RPC Methods:** `Process`, `Refund`, `GetStatus`, `ListTransactions`
- **Description:** The gRPC handler adapter implements the `PaymentService` proto definition using the `google.golang.org/grpc` library. Each RPC method maps to its corresponding inbound port: `Process` maps to `ProcessPaymentPort`, `Refund` maps to `RefundPaymentPort`, `GetStatus` maps to `GetPaymentStatusPort`, and `ListTransactions` maps to `ListTransactionsPort`. The handler is implemented with unary interceptors for authentication (validating the caller's SPIFFE SVID and extracting the service identity), request logging with correlation IDs, and OpenTelemetry span creation. The `Process` RPC is the most critical handler: it accepts a payment request, validates the input, and delegates to the `ProcessPaymentPort` which communicates with the external gateway via the ACL sidecar. The handler implements a timeout of 30 seconds for the `Process` RPC (matching the external gateway's SLA) and returns a DEADLINE_EXCEEDED gRPC status if the gateway does not respond in time. The gRPC server runs on port 50055 with mTLS enforced, and supports server reflection for development tooling and the standard gRPC health checking protocol.

### REST Controller

- **Maps to:** None (the Payment service does not expose a REST API to external clients)
- **Description:** The Payment service does not expose a REST API. All payment operations are triggered by the Order service via gRPC or by consuming events from the event backbone. This design decision is intentional: payment operations are sensitive and should only be invoked by trusted internal services with proper authentication and authorization. External-facing payment UIs (such as checkout pages and payment method management) are handled by a separate frontend service that communicates with the Payment service through the Gateway. If a REST API is needed in the future for administrative operations (such as refund management or payment dispute handling), it should be implemented as a separate adapter with strict access controls and audit logging.

### Event Consumer

- **Maps to:** `com.company.order.confirmed`, `com.company.order.cancelled`, `com.company.order.completed`
- **Description:** The Payment service consumes order lifecycle events to trigger payment state transitions. When an order is confirmed (`com.company.order.confirmed`), the consumer captures the previously authorized payment, converting the hold on the customer's funds into an actual charge. When an order is cancelled (`com.company.order.cancelled`), the consumer either voids the authorization (if not yet captured) or initiates a refund (if already captured), depending on the payment's current state. When an order is completed (`com.company.order.completed`), the consumer verifies that the captured amount matches the final order total and initiates an adjustment if there is a discrepancy. The consumer is implemented using the `segmentio/kafka-go` library with a committed consumer group (`payment-order-consumer`). Event processing is idempotent: each event includes an idempotency key derived from the order ID and event type, and the payment repository tracks processed events to prevent duplicate processing. Failed events are retried three times with exponential backoff and then forwarded to the `payment.events.dlq` dead letter topic for manual investigation.

## Outbound Adapters

### Persistence Adapter

- **Database:** PostgreSQL 16 with pgx driver and custom SQL
- **ORM/Query Approach:** Custom SQL using pgx with sqlc for type-safe query generation
- **Description:** The persistence adapter uses the pgx PostgreSQL driver with sqlc for compile-time SQL type checking in Go. The adapter manages the payment state machine, refund records, and the transactional outbox. Each payment record includes a `version` column for optimistic concurrency control, preventing race conditions when multiple goroutines attempt to update the same payment simultaneously. The outbox table follows the same pattern as the Order service: events are written to the outbox in the same transaction as the payment state change, and a relay process publishes them to Kafka. The adapter uses PostgreSQL's `SELECT ... FOR UPDATE SKIP LOCKED` pattern for the outbox relay, enabling multiple Payment service instances to share the outbox processing load without conflicts. Connection pooling is managed by pgxpool with a maximum of 25 connections, tuned for the expected payment throughput of 100-500 transactions per second.

### Messaging Adapter

- **Kafka Topics:**
  - **Produced:** `com.company.payment.authorized`, `com.company.payment.captured`, `com.company.payment.refunded`, `com.company.payment.voided`, `com.company.payment.failed`
  - **Consumed:** `com.company.order.confirmed`, `com.company.order.cancelled`, `com.company.order.completed`
- **Serialization:** Protobuf (shared message definitions registered with Schema Registry)
- **Description:** The messaging adapter handles all Kafka interactions for the Payment service. Produced events follow the transactional outbox pattern, ensuring that every payment state change is accompanied by a corresponding event in the outbox table. The outbox relay runs as a background goroutine, polling the outbox every 100ms and publishing events to Kafka using the transactional producer API. Consumed events are processed with manual offset commits after successful database writes. The adapter uses the `segmentio/kafka-go` library configured with idempotent production, zstd compression, and a batch size optimized for the relatively low volume but high criticality of payment events. Each produced event includes a `correlation_id` header that links it to the originating order event, enabling end-to-end traceability from order creation through payment processing.

### External Service Adapter

- **External Dependencies:** External payment gateway (vendor-specific API, e.g., Stripe, Adyen, or Braintree)
- **Behind ACL:** Yes (mandatory ACL sidecar for all external communication)
- **Description:** The external service adapter is the most critical adapter in the Payment service, as it communicates with the third-party payment processor. This adapter is always invoked through the ACL sidecar, which provides several essential capabilities. First, the sidecar implements the circuit breaker pattern: after 5 consecutive failures, the circuit opens and all subsequent requests fail fast with a `GatewayUnavailableError` for 30 seconds, preventing cascading failures and giving the gateway time to recover. Second, the sidecar implements retry with jitter: failed requests are retried up to 3 times with exponentially increasing delays (1s, 2s, 4s) plus a random jitter of up to 500ms, preventing thundering herd problems. Third, the sidecar enforces rate limiting to stay within the gateway's API rate limits (typically 100 requests per second). Fourth, the sidecar blocks proprietary imports: the Go code in the Payment service never directly imports the vendor's SDK, ensuring that a vendor change only requires updating the sidecar's translation layer. The sidecar communicates with the Payment service over localhost via a simple REST or gRPC interface.

### Observability Adapter

- **OTel Instrumentation Points:**
  - **Payment Processing Tracing:** Each payment operation creates a root span with the payment ID, order ID, amount, and currency. Sub-spans track the gateway communication (through the ACL sidecar), database persistence, and event publication. Gateway response codes and latency are recorded as span attributes.
  - **Circuit Breaker Metrics:** Gauge metrics for circuit breaker state (`payment.circuit_breaker.state` with labels: gateway), counter metrics for circuit breaker state transitions (`payment.circuit_breaker.transitions_total` with labels: from_state, to_state), and histogram metrics for gateway request latency (`payment.gateway.latency` with labels: operation, result).
  - **Payment Metrics:** Counter metrics for payment state transitions (`payment.transitions_total` with labels: from_status, to_status), histogram metrics for payment processing duration (`payment.processing.duration` with labels: operation), gauge metrics for pending gateway operations (`payment.gateway.pending_operations`), and counter metrics for refund amounts (`payment.refunds.total` with labels: reason).
  - **ACL Sidecar Metrics:** Counter metrics for sidecar proxy requests (`payment.sidecar.requests_total` with labels: operation, result), histogram metrics for sidecar overhead latency (`payment.sidecar.overhead_duration`), and counter metrics for blocked proprietary imports (`payment.sidecar.blocked_imports_total`).
- **Description:** The observability adapter uses the OpenTelemetry Go SDK for manual and automatic instrumentation. Auto-instrumentation covers HTTP, gRPC, and database operations. Manual spans are added for gateway communication, circuit breaker state changes, and the ACL sidecar proxy operations. Payment events are specially tagged in traces with `payment.id` and `order.id` attributes for cross-service trace correlation. The adapter includes a custom metric exporter that aggregates financial metrics (total authorized, captured, and refunded amounts) in real-time for dashboarding. Structured logs use the `slog` package with JSON formatting and include trace context for correlation.
