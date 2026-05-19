# Payment Service - Contracts Definition

> Language: Go | Role: Payment processing with ACL sidecar, Circuit Breaker pattern

## gRPC Contract

### Proto Package

- **Package Name:** `payment.v1`
- **File:** `payment/v1/payment.proto`

### Service Definition

**Service Name:** `PaymentService`

| RPC Method | Request Type | Response Type | Streaming |
|---|---|---|---|
| `Process` | `ProcessPaymentRequest` | `ProcessPaymentResponse` | Unary |
| `Refund` | `RefundPaymentRequest` | `RefundPaymentResponse` | Unary |
| `GetStatus` | `GetPaymentStatusRequest` | `GetPaymentStatusResponse` | Unary |
| `ListTransactions` | `ListTransactionsRequest` | `ListTransactionsResponse` | Unary |

### RPC Details

**Process:**
Submits a payment for authorization through the external payment gateway via the ACL sidecar. The request includes the order ID, amount, payment method details, and an idempotency key. The response returns the payment ID, authorization status, and the gateway reference number. If the gateway declines the payment, the response includes the decline reason code. If the gateway is unavailable (circuit breaker open), the RPC returns a UNAVAILABLE status with a `GatewayUnavailableError` detail.

**Refund:**
Initiates a refund for a previously captured payment. The request specifies the payment ID, refund amount, reason, and a reference ID linking to the originating cancellation or return. The response confirms the refund with the refund ID and the estimated settlement date. Partial refunds are supported, and the response includes the remaining captured balance after the refund.

**GetStatus:**
Retrieves the current status of a payment. The response includes a breakdown of authorized, captured, and refunded amounts. When `include_gateway_status` is true, the service queries the external gateway in real-time for the most up-to-date status, which may reflect asynchronous settlement events not yet visible in the local database.

**ListTransactions:**
Lists payment transactions with flexible filtering by customer ID, order ID, status, and date range. The request supports cursor-based pagination with opaque page tokens. The response includes a paginated list of transaction summaries (payment ID, order ID, amount, status, created timestamp) for administrative dashboards and financial reconciliation. Full payment details can be retrieved using the `GetStatus` RPC with individual payment IDs.

### Key Message Types

```protobuf
message ProcessPaymentRequest {
  string order_id = 1;
  Money amount = 2;
  PaymentMethod payment_method = 3;
  string idempotency_key = 4;
  string customer_id = 5;
  map<string, string> metadata = 6;
}

message ProcessPaymentResponse {
  string payment_id = 1;
  PaymentStatus status = 2;
  optional string authorization_code = 3;
  optional string gateway_reference = 4;
  google.protobuf.Timestamp processed_at = 5;
}

message RefundPaymentRequest {
  string payment_id = 1;
  Money amount = 2;
  enum RefundReason {
    CUSTOMER_REQUEST = 0;
    ORDER_CANCELLED = 1;
    FRAUD_REVERSAL = 2;
    SYSTEM_ERROR = 3;
    PARTIAL_RETURN = 4;
  }
  RefundReason reason = 3;
  string reference_id = 4;
  string initiated_by = 5;
}

message RefundPaymentResponse {
  string refund_id = 1;
  string payment_id = 2;
  Money refund_amount = 3;
  Money remaining_captured = 4;
  RefundStatus status = 5;
  google.protobuf.Timestamp estimated_settlement = 6;
}

message GetPaymentStatusRequest {
  string payment_id = 1;
  bool include_gateway_status = 2;
}

message GetPaymentStatusResponse {
  string payment_id = 1;
  string order_id = 2;
  PaymentStatus status = 3;
  Money authorized_amount = 4;
  Money captured_amount = 5;
  Money refunded_amount = 6;
  string currency = 7;
  optional string gateway_reference = 8;
  google.protobuf.Timestamp created_at = 9;
  google.protobuf.Timestamp updated_at = 10;
  optional GatewayStatusDetail gateway_status = 11;
}

enum PaymentStatus {
  PENDING = 0;
  AUTHORIZED = 1;
  CAPTURED = 2;
  PARTIALLY_REFUNDED = 3;
  FULLY_REFUNDED = 4;
  VOIDED = 5;
  FAILED = 6;
}

enum RefundStatus {
  REFUND_PENDING = 0;
  REFUND_SUBMITTED = 1;
  REFUND_SETTLED = 2;
  REFUND_FAILED = 3;
}

message PaymentMethod {
  oneof method {
    CardDetails card = 1;
    string payment_method_token = 2;  // Vaulted payment method reference
  }
}

message CardDetails {
  string last_four = 1;         // Last 4 digits only (PII redaction)
  string brand = 2;             // visa, mastercard, amex
  int32 expiry_month = 3;
  int32 expiry_year = 4;
}

message Money {
  int64 units = 1;
  int32 nanos = 2;
  string currency_code = 3;
}

message GatewayStatusDetail {
  string raw_status = 1;
  string settlement_status = 2;
  google.protobuf.Timestamp settlement_date = 3;
}
```

## OpenAPI Contract

The Payment service does not expose a public REST API. All payment operations are available exclusively through the gRPC interface defined above. This is a deliberate security design decision: payment operations involve sensitive financial data and should only be invoked by trusted internal services (primarily the Order service) over mTLS-authenticated gRPC connections.

Administrative payment operations (such as dispute management, chargeback handling, and reconciliation) are handled through the payment gateway's own web console or through an internal admin service that is out of scope for this architecture.

## Event Contracts

### CloudEvents Type Prefix

`com.company.payment.`

### Event Types

| Event Type | Payload Schema | Consumer Services |
|---|---|---|
| `com.company.payment.authorized` | `PaymentAuthorizedEvent` | Order, Analytics, Notification |
| `com.company.payment.captured` | `PaymentCapturedEvent` | Order, Analytics |
| `com.company.payment.refunded` | `PaymentRefundedEvent` | Order, Analytics, Notification |
| `com.company.payment.voided` | `PaymentVoidedEvent` | Order, Analytics |
| `com.company.payment.failed` | `PaymentFailedEvent` | Order, Analytics, Notification |
| `com.company.payment.processed` | `PaymentProcessedEvent` | Notification, Analytics (composite event for convenience) |

### Event Details

**PaymentAuthorizedEvent:**
Emitted when a payment authorization is successfully obtained from the external gateway. The payload includes the payment ID, order ID, authorized amount, authorization code, and gateway reference. The Order service consumes this event to advance the order creation saga. The Analytics service tracks authorization rates and latency. The Notification service does not send a customer notification at this stage (authorization is invisible to the customer).

**PaymentCapturedEvent:**
Emitted when a previously authorized payment is captured (the funds are actually collected from the customer's account). The payload includes the payment ID, order ID, captured amount, and the capture timestamp. The Order service consumes this event to update the order's payment summary. The Analytics service tracks capture rates, which are important for revenue recognition. This event is consumed by the `com.company.payment.processed` composite event generator, which creates a customer-facing notification.

**PaymentRefundedEvent:**
Emitted when a refund is processed for a captured payment. The payload includes the refund ID, payment ID, order ID, refund amount, remaining captured balance, reason, and the estimated settlement date. The Order service consumes this event to update the order's payment summary and potentially transition the order status. The Analytics service tracks refund rates and reasons for financial reporting. The Notification service sends a refund confirmation email to the customer.

**PaymentVoidedEvent:**
Emitted when an uncaptured authorization is voided (cancelled before capture). The payload includes the payment ID, order ID, and void reason. The Order service consumes this event to release the order's payment hold. The Analytics service tracks void rates, which may indicate order cancellation patterns or fraud detection effectiveness.

**PaymentFailedEvent:**
Emitted when a payment operation fails at the gateway level (e.g., card declined, insufficient funds). The payload includes the payment ID, order ID, failure reason code, and a human-readable failure message (without sensitive details). The Order service consumes this event to fail the order creation saga or trigger the cancellation saga. The Analytics service tracks failure rates and reason distributions for fraud detection and payment method optimization. The Notification service sends a payment failure notification to the customer with instructions for updating their payment method.

**PaymentProcessedEvent:**
A composite convenience event emitted after a payment is successfully captured, combining authorization and capture data into a single event. This event exists because most downstream consumers (especially Notification) only care about successful completed payments, not the intermediate authorization step. The payload includes the payment ID, order ID, total captured amount, and the payment method summary. This event reduces the need for consumers to track and correlate multiple payment events.
