# Order Service - Adapters Definition

> Language: Java/Kotlin | Role: Saga orchestration, Transactional Outbox Pattern

## Inbound Adapters

### gRPC Handler

- **Maps to:** `order.v1.OrderService`
- **RPC Methods:** `Create`, `Get`, `Cancel`, `Complete`, `List`
- **Description:** The gRPC handler adapter implements the `OrderService` proto definition using Kotlin coroutines and the gRPC-Kotlin stub generator. Each RPC method maps to its corresponding inbound port: `Create` to `CreateOrderPort`, `Get` to `GetOrderPort`, `Cancel` to `CancelOrderPort`, and `Complete` to `CompleteOrderPort`. The handler is implemented as a Spring Boot service with the `grpc-spring-boot-starter` library, which manages the gRPC server lifecycle, health checking, and graceful shutdown. Server interceptors handle authentication (validating the caller's SPIFFE SVID and extracting the customer ID from the JWT claims), request logging with correlation IDs, and OpenTelemetry span creation. The `List` RPC maps to `ListOrdersPort`, accepting filter criteria and pagination parameters and returning a paginated list of order summaries. The `Create` RPC is the most complex handler: it initiates the order creation saga and returns immediately with a PENDING status, allowing the client to poll for the final status or subscribe to order events. This asynchronous design prevents the gRPC call from timing out during long-running saga executions. The gRPC server runs on port 50054 with mTLS enforced, and supports server reflection and health checking via the standard gRPC health protocol.

### REST Controller

- **Maps to:** `/api/v1/orders/*`
- **OpenAPI Path Prefix:** `/api/v1/orders`
- **Description:** The REST controller exposes the Order service's operations over HTTP/JSON for external consumers. It is implemented using Spring WebFlux with Kotlin coroutines for non-blocking request handling. Path-to-port mappings: `POST /api/v1/orders` maps to `CreateOrderPort`, `GET /api/v1/orders/{id}` maps to `GetOrderPort`, `POST /api/v1/orders/{id}/cancel` maps to `CancelOrderPort`, and `POST /api/v1/orders/{id}/complete` maps to `CompleteOrderPort`. The controller uses Spring's `@Validated` annotation for request validation and returns problem-detail RFC 7807 responses for all error conditions. An additional `GET /api/v1/orders` endpoint supports listing orders for the authenticated customer with pagination and status filtering. The REST controller includes a webhook registration endpoint that allows external systems to subscribe to order status change notifications, which are delivered via the event backbone rather than direct HTTP callbacks.

### Event Consumer

- **Maps to:** `com.company.payment.processed`, `com.company.payment.refunded`, `com.company.catalog.inventory-updated`
- **Description:** The Order service consumes payment and inventory events to drive saga step completions and handle external state changes. When a payment is processed (`com.company.payment.processed`), the consumer advances the order creation saga to the next step or transitions the order to the PROCESSING state if all saga steps are complete. When a payment is refunded (`com.company.payment.refunded`), the consumer records the refund against the order and updates the payment summary. When inventory is updated (`com.company.catalog.inventory-updated`), the consumer checks whether any pending orders are affected by stock changes and triggers order cancellation for orders that can no longer be fulfilled. The consumer is implemented using Spring Kafka with a committed consumer group (`order-event-consumer`). Event processing is idempotent using a processed-events table, and failed events are retried three times with exponential backoff before being forwarded to the `order.events.dlq` dead letter topic. The consumer includes a concurrency limiter that processes at most 10 events in parallel to prevent overloading the saga executor.

## Outbound Adapters

### Persistence Adapter

- **Database:** PostgreSQL 16 with Hibernate/JPA and jOOQ
- **ORM/Query Approach:** JPA/Hibernate for aggregate persistence, jOOQ for complex queries and outbox processing
- **Description:** The persistence adapter uses a dual-ORM strategy that leverages the strengths of both Hibernate and jOOQ. Hibernate manages the Order aggregate and its child entities (line items, status history, saga state) with standard JPA repository interfaces, providing automatic dirty checking, cascading persists, and first-level caching within a transaction scope. jOOQ is used for complex queries that involve multi-table joins, window functions, and the outbox polling operation, where Hibernate's abstraction would add unnecessary overhead. The adapter implements the Transactional Outbox Pattern by writing all domain events to an `outbox` table within the same database transaction as the order data mutation. A scheduled relay task (`OutboxRelayScheduler`) runs every 100ms during active periods, reads unpublished events, publishes them to Kafka, and marks them as processed. The outbox table includes a sequence number for ordered reading and a processed flag for efficient filtering. The adapter uses Spring's `@Transactional` annotation with `REQUIRES_NEW` propagation for the outbox relay to ensure that the Kafka publish and the outbox marking are committed together.

### Messaging Adapter

- **Kafka Topics:**
  - **Produced:** `com.company.order.created`, `com.company.order.confirmed`, `com.company.order.cancelled`, `com.company.order.completed`, `com.company.order.saga-step-completed`
  - **Consumed:** `com.company.payment.processed`, `com.company.payment.refunded`, `com.company.catalog.inventory-updated`
- **Serialization:** Protobuf (shared message definitions registered with Schema Registry)
- **Description:** The messaging adapter handles all Kafka interactions for the Order service. Produced events are published through the transactional outbox pattern as described in the persistence adapter. The outbox relay uses the Kafka transactional producer API to ensure exactly-once delivery semantics, publishing events in the order they were written to the outbox table. Consumed events are processed using Spring Kafka's `@KafkaListener` annotation with manual acknowledgment. The adapter configures a custom `ErrorHandler` that implements retry with exponential backoff (initial delay: 1 second, max delay: 30 seconds, multiplier: 2) and a dead letter queue forwarder. Each consumed event is checked against the processed-events table before processing to ensure idempotency, which is critical for the saga execution model where duplicate events could cause double-processing of payment authorizations or inventory reservations.

### External Service Adapter

- **External Dependencies:** None directly (all external integrations are mediated through the Payment and Catalog services)
- **Behind ACL:** Not applicable for the Order service itself; the Payment service handles external gateway ACL
- **Description:** The Order service does not communicate directly with any external or third-party services. All interactions with external systems (such as payment processors and shipping carriers) are mediated through the Payment and Catalog services respectively. This architectural decision keeps the Order service focused on its core responsibility of order lifecycle management and saga orchestration, while delegating external integration complexity to services that are specifically designed to handle it with appropriate ACL patterns and circuit breakers.

### Observability Adapter

- **OTel Instrumentation Points:**
  - **Saga Execution Tracing:** Each saga execution creates a root span with the order ID, saga type, and current step. Individual saga steps create child spans with the step name, target service, and outcome. Compensating actions are marked with a `compensating=true` span attribute.
  - **gRPC/HTTP Request Tracing:** Every inbound request creates a server span with attributes for the method, path, and status code. gRPC spans include the full method name and peer identity.
  - **Database Operation Tracing:** JPA and jOOQ operations create child spans for each database query with the query type, table, and duration. Slow queries exceeding 200ms are flagged.
  - **Kafka Producer/Consumer Tracing:** Produced events create producer spans; consumed events create consumer spans linked to the original producer span via trace context propagation in Kafka message headers.
  - **Order Metrics:** Counter metrics for order state transitions (`order.transitions_total` with labels: from_status, to_status), histogram metrics for order fulfillment duration (`order.fulfillment_duration` with labels: status), gauge metrics for active sagas (`order.sagas.active` with labels: saga_type), counter metrics for saga compensations (`order.saga.compensations_total` with labels: step, reason), and histogram metrics for outbox relay latency (`order.outbox.relay_latency`).
- **Description:** The observability adapter uses the OpenTelemetry Java agent for automatic instrumentation of Spring components, gRPC, JDBC, and Kafka clients. Manual spans are added for saga execution steps using the OpenTelemetry API. The adapter includes a custom `SagaExecutionSpan` that links all steps of a single saga execution, enabling end-to-end trace visualization of the entire order creation flow from initial request through inventory reservation, payment authorization, and final confirmation. Metrics are exported via OTLP to the Analytics service. Structured logs use Logback with the OTel log appender, including trace context for correlation.
