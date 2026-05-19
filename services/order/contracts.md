# Order Service - Contracts Definition

> Language: Java/Kotlin | Role: Saga orchestration, Transactional Outbox Pattern

## gRPC Contract

### Proto Package

- **Package Name:** `order.v1`
- **File:** `order/v1/order.proto`

### Service Definition

**Service Name:** `OrderService`

| RPC Method | Request Type | Response Type | Streaming |
|---|---|---|---|
| `Create` | `CreateOrderRequest` | `CreateOrderResponse` | Unary |
| `Get` | `GetOrderRequest` | `GetOrderResponse` | Unary |
| `Cancel` | `CancelOrderRequest` | `CancelOrderResponse` | Unary |
| `Complete` | `CompleteOrderRequest` | `CompleteOrderResponse` | Unary |
| `List` | `ListOrdersRequest` | `ListOrdersResponse` | Unary |

### RPC Details

**Create:**
Initiates the creation of a new order by starting the order creation saga. The request includes all line items, the shipping address, and the payment method identifier. The response returns immediately with a PENDING status and the order ID, which the client can use to poll for the final order status via the `Get` RPC. The saga executes asynchronously, reserving inventory and authorizing payment before confirming the order.

**Get:**
Retrieves the full details of an order by its ID. The response includes the order's current status, all line items with pricing, the shipping address, and optional payment summary and status history. The `include_history` flag controls whether the complete status change timeline is included.

**Cancel:**
Cancels an existing order by executing the cancellation saga. The request specifies the cancellation reason and whether a refund is requested. The cancellation saga releases reserved inventory and voids or refunds payments as appropriate. The response confirms the cancellation with the previous and new statuses.

**Complete:**
Marks an order as completed after fulfillment. The request may include a tracking number and delivery confirmation. The port validates that the order is in a completable state and that all payments have been captured. The response includes the final total amount, which may differ from the estimated total due to partial shipments or price adjustments.

**List:**
Lists orders with flexible filtering by customer ID, status, and date range. The request supports cursor-based pagination with opaque page tokens and configurable sort order. The response includes a paginated list of order summaries (ID, status, total, item count, created timestamp) rather than full order details, optimizing for list-view performance. Full details can be retrieved using the `Get` RPC with individual order IDs.

### Key Message Types

```protobuf
message CreateOrderRequest {
  string customer_id = 1;
  repeated OrderLineItem items = 2;
  Address shipping_address = 3;
  string payment_method_id = 4;
  string idempotency_key = 5;
}

message CreateOrderResponse {
  string order_id = 1;
  OrderStatus status = 2;
  Money estimated_total = 3;
  google.protobuf.Timestamp created_at = 4;
  repeated string reservation_ids = 5;
}

message GetOrderRequest {
  string order_id = 1;
  bool include_history = 2;
}

message GetOrderResponse {
  Order order = 1;
  repeated OrderStatusChange history = 2;
  PaymentSummary payment_summary = 3;
}

message CancelOrderRequest {
  string order_id = 1;
  enum CancelReason {
    CUSTOMER_REQUEST = 0;
    PAYMENT_FAILED = 1;
    INVENTORY_UNAVAILABLE = 2;
    SYSTEM_ERROR = 3;
    FRAUD_DETECTED = 4;
  }
  CancelReason reason = 2;
  string cancelled_by = 3;
  bool refund_requested = 4;
}

message CancelOrderResponse {
  string order_id = 1;
  OrderStatus previous_status = 2;
  OrderStatus new_status = 3;
  bool refund_initiated = 4;
  google.protobuf.Timestamp cancelled_at = 5;
}

message CompleteOrderRequest {
  string order_id = 1;
  optional string tracking_number = 2;
  optional DeliveryConfirmation delivery_confirmation = 3;
}

message CompleteOrderResponse {
  string order_id = 1;
  OrderStatus status = 2;
  google.protobuf.Timestamp completed_at = 3;
  Money final_total = 4;
}

message Order {
  string id = 1;
  string customer_id = 2;
  repeated OrderLineItem items = 3;
  Address shipping_address = 4;
  Money estimated_total = 5;
  OrderStatus status = 6;
  google.protobuf.Timestamp created_at = 7;
  google.protobuf.Timestamp updated_at = 8;
}

message OrderLineItem {
  string product_id = 1;
  string variant_id = 2;
  string product_name = 3;
  int32 quantity = 4;
  Money unit_price = 5;
  Money line_total = 6;
}

enum OrderStatus {
  PENDING = 0;      // Order created, awaiting processing
  CONFIRMED = 1;    // Inventory reserved, payment authorized
  PROCESSING = 2;   // Payment captured, order being fulfilled
  SHIPPED = 3;      // Order has been shipped
  COMPLETED = 4;    // Order delivered and finalized
  CANCELLED = 5;    // Order cancelled, compensations applied
  FAILED = 6;       // Order creation failed, no compensations needed
}

message Money {
  int64 units = 1;
  int32 nanos = 2;
  string currency_code = 3;
}

message Address {
  string line1 = 1;
  string line2 = 2;
  string city = 3;
  string state = 4;
  string postal_code = 5;
  string country = 6;
}
```

## OpenAPI Contract

### API Path Prefix

`/api/v1/orders`

### Endpoints

| Method | Path | Request Body | Response | Auth Required |
|---|---|---|---|---|
| `POST` | `/api/v1/orders` | `CreateOrderRequest` JSON | `CreateOrderResponse` JSON (201) | Yes |
| `GET` | `/api/v1/orders/{id}` | None | `GetOrderResponse` JSON | Yes |
| `GET` | `/api/v1/orders` | None (query params) | Paginated order list | Yes |
| `POST` | `/api/v1/orders/{id}/cancel` | `CancelOrderRequest` JSON | `CancelOrderResponse` JSON | Yes |
| `POST` | `/api/v1/orders/{id}/complete` | `CompleteOrderRequest` JSON | `CompleteOrderResponse` JSON | Yes |

### Endpoint Details

**POST /orders:**
Creates a new order. Requires a JWT with the `order:write` scope. The `idempotency_key` header ensures that duplicate submissions return the original order. Returns 201 with the order ID and PENDING status. Returns 409 for duplicate idempotency keys (returning the existing order). Returns 422 for validation errors such as empty line items or invalid addresses.

**GET /orders/{id}:**
Retrieves an order by ID. Requires the `order:read` scope. Customers can only access their own orders; internal services can access any order. Supports `?include=history,payment` query parameter for expansion. Returns 404 if the order does not exist.

**GET /orders:**
Lists orders for the authenticated customer. Supports `?status=CONFIRMED&page_size=20&page_token=abc` query parameters for filtering and pagination. Returns a paginated list of order summaries with links to full order details.

**POST /orders/{id}/cancel:**
Cancels an order. Requires the `order:write` scope. The request body specifies the cancellation reason. Returns 200 with the cancellation confirmation. Returns 409 if the order is not in a cancellable state.

**POST /orders/{id}/complete:**
Completes an order. Requires the `order:admin` scope (internal services only). The request body may include tracking and delivery information. Returns 200 with the final order details.

### Authentication Requirements

- All endpoints require a valid JWT token with appropriate scopes
- `order:read` scope is required for GET operations
- `order:write` scope is required for POST operations (create, cancel)
- `order:admin` scope is required for the complete operation (internal services only)
- Internal service-to-service calls use mTLS with SPIFFE SVID verification
- Customer IDs are extracted from the JWT subject claim and verified against the requested order's customer ID

## Event Contracts

### CloudEvents Type Prefix

`com.company.order.`

### Event Types

| Event Type | Payload Schema | Consumer Services |
|---|---|---|
| `com.company.order.created` | `OrderCreatedEvent` | Analytics, Notification, CDC Relay |
| `com.company.order.confirmed` | `OrderConfirmedEvent` | Analytics, Notification, Catalog |
| `com.company.order.cancelled` | `OrderCancelledEvent` | Analytics, Notification, Catalog, Payment |
| `com.company.order.completed` | `OrderCompletedEvent` | Analytics, Notification, Payment, Catalog |
| `com.company.order.failed` | `OrderFailedEvent` | Analytics, Notification |
| `com.company.order.saga-step-completed` | `SagaStepCompletedEvent` | Analytics (monitoring only) |

### Event Details

**OrderCreatedEvent:**
Emitted when a new order is created and enters the PENDING state. The payload includes the order ID, customer ID, line items, estimated total, and the idempotency key. This event signals that the order creation saga has been initiated and downstream services should prepare for potential inventory and payment operations.

**OrderConfirmedEvent:**
Emitted when the order creation saga completes successfully and the order transitions to CONFIRMED state. The payload includes the order ID, confirmed line items, reservation IDs, and the authorized payment amount. The Catalog service uses this event to confirm inventory reservations, converting temporary holds to permanent deductions. The Notification service sends an order confirmation email to the customer.

**OrderCancelledEvent:**
Emitted when an order is cancelled and the cancellation saga has completed. The payload includes the order ID, cancellation reason, refund status, and the list of reservation IDs to be released. The Catalog service releases the reserved inventory. The Payment service processes any required refunds. The Notification service sends a cancellation confirmation to the customer.

**OrderCompletedEvent:**
Emitted when an order is marked as completed after delivery. The payload includes the order ID, final total, delivery confirmation, and tracking number. This is one of the most consumed events in the system: the Payment service captures the final payment amount, the Catalog service finalizes inventory deductions, the Analytics service records the completed order for revenue tracking, and the Notification service sends a delivery confirmation and review solicitation to the customer.

**OrderFailedEvent:**
Emitted when an order creation saga fails and the order transitions to the FAILED state. The payload includes the order ID, the failed saga step, and the error details. This event is consumed by the Analytics service for failure rate monitoring and by the Notification service to alert the customer that their order could not be processed.

**SagaStepCompletedEvent:**
An infrastructure event emitted after each step of a saga completes. This event is consumed only by the Analytics service for real-time saga monitoring and alerting. It is not a business event and should not trigger any business logic in downstream services.
