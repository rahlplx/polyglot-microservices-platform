# Catalog Service - Adapters Definition

> Language: Node.js/TypeScript | Role: Full CRUD product catalog with search

## Inbound Adapters

### gRPC Handler

- **Maps to:** `catalog.v1.CatalogService`
- **RPC Methods:** `Get`, `Search`, `Create`, `Update`, `Delete`
- **Description:** The gRPC handler adapter implements the `CatalogService` proto definition and maps each RPC to its corresponding inbound port. The `Get` RPC maps to `GetProductPort`, accepting a product ID and returning the full product details. The `Search` RPC maps to `SearchCatalogPort`, accepting a search query with filters and returning paginated results with facets. The `Create` RPC maps to `CreateProductPort`, accepting a product input message and returning the created product ID and metadata. The `Update` RPC is used for both product updates and inventory adjustments, with the request type determined by an update mask field that specifies which fields are being modified. The `Delete` RPC maps to `DeleteProductPort`, accepting a product ID and deletion parameters and returning a confirmation response indicating whether a soft or hard delete was performed. The handler is implemented using the `@grpc/grpc-js` package with TypeScript type generation from the proto definitions. Server interceptors handle authentication (validating the caller's SVID), request logging, and OpenTelemetry span creation. The gRPC server runs on port 50053 with mTLS enforced, and supports server reflection for development tooling.

### REST Controller

- **Maps to:** `/api/v1/catalog/*`
- **OpenAPI Path Prefix:** `/api/v1/catalog`
- **Description:** The REST controller exposes the Catalog service's operations over HTTP/JSON for external consumers and browser-based clients. The controller is implemented using Fastify with the `@fastify/swagger` plugin for automatic OpenAPI spec generation. Path-to-port mappings are as follows: `GET /api/v1/catalog/products/:id` maps to `GetProductPort`, `GET /api/v1/catalog/products` maps to `SearchCatalogPort` (with query parameters for search, filters, and pagination), `POST /api/v1/catalog/products` maps to `CreateProductPort`, and `PATCH /api/v1/catalog/products/:id/inventory` maps to `UpdateInventoryPort`. Request validation is performed using JSON Schema derived from the OpenAPI spec, and response serialization uses fast-json-stringify for maximum throughput. The controller includes CORS support for web clients and generates standard HTTP status codes: 200 for successful reads, 201 for creation, 404 for not found, 409 for conflicts (duplicate SKU), and 422 for validation errors.

### Event Consumer

- **Maps to:** `com.company.order.placed`, `com.company.order.cancelled`
- **Description:** The Catalog service consumes order events to trigger inventory reservations and releases. When an order is placed (`com.company.order.placed`), the consumer calls `UpdateInventoryPort` with a negative quantity delta for each line item, reserving stock for the order. When an order is cancelled (`com.company.order.cancelled`), the consumer releases the reserved stock with a positive quantity delta. The consumer is implemented using the `kafkajs` library with a committed consumer group (`catalog-order-consumer`). Event processing is idempotent: each inventory update includes the order ID as the reference, and duplicate events are detected and skipped using a processed-events table in PostgreSQL. The consumer includes a dead letter queue handler that forwards unprocessable events to `catalog.events.dlq` after three retry attempts with exponential backoff. The consumer also listens to `com.company.catalog.product-updated` events produced by other catalog instances for cache invalidation in multi-instance deployments.

## Outbound Adapters

### Persistence Adapter

- **Database:** PostgreSQL 16 with Prisma ORM
- **ORM/Query Approach:** Prisma with TypeScript type generation, raw SQL for complex queries
- **Description:** The persistence adapter uses Prisma as the primary ORM for the Catalog service. Prisma's schema definition language defines the product, variant, category, inventory, and outbox models with their relationships. The adapter leverages Prisma's interactive transactions for multi-step operations such as product creation with variants and inventory initialization. For complex queries that exceed Prisma's query builder capabilities (such as recursive category tree traversal and full-text search fallback), the adapter falls back to raw SQL queries using Prisma's `$queryRaw` and `$executeRaw` methods, with results mapped to TypeScript types using `zod` schema validation. The adapter uses Prisma's connection pooling with a pool size tuned to the number of concurrent requests expected at peak load. Database migrations are managed through Prisma Migrate and applied automatically during service startup in development, or through CI/CD pipelines in production.

### Messaging Adapter

- **Kafka Topics:**
  - **Produced:** `com.company.catalog.product-created`, `com.company.catalog.product-updated`, `com.company.catalog.inventory-low`, `com.company.catalog.inventory-updated`
  - **Consumed:** `com.company.order.placed`, `com.company.order.cancelled`
- **Serialization:** Protobuf (shared message definitions registered with Schema Registry)
- **Description:** The messaging adapter handles all Kafka interactions for the Catalog service, implementing both the event producer and consumer roles. Produced events are written to a PostgreSQL outbox table first (as part of the transactional outbox pattern), then a background relay worker reads the outbox and publishes to Kafka using the transactional producer API. This two-phase approach ensures that the database state and the event stream remain consistent. The relay worker uses a polling strategy with adaptive intervals: it polls every 100ms when there are pending events, and backs off to 1-second intervals when the outbox is empty. Consumed events are processed using the `kafkajs` consumer with manual offset commits after successful processing, ensuring at-least-once delivery with idempotent handlers for exactly-once semantics.

### External Service Adapter

- **External Dependencies:** None directly (all external integrations are handled by downstream services)
- **Behind ACL:** Not applicable
- **Description:** The Catalog service does not communicate with any external or third-party services. Image storage and CDN operations are handled by a dedicated media service that is not part of the current scope. All catalog operations are self-contained within the service's own PostgreSQL database and Elasticsearch cluster. If future requirements include integration with external product data feeds or pricing APIs, those integrations would be implemented behind an ACL sidecar following the pattern established by the Payment service's external gateway adapter.

### Observability Adapter

- **OTel Instrumentation Points:**
  - **gRPC/HTTP Request Tracing:** Every inbound request creates a span with attributes for method/path, status code, and latency. gRPC spans include the full method name, while HTTP spans include the route pattern and query parameters (with sensitive values redacted).
  - **Database Query Tracing:** Prisma query logging creates child spans for each database operation with the query type, table, and duration. Slow queries exceeding 100ms are flagged with a warning span event.
  - **Search Operation Tracing:** Each Elasticsearch query creates a span capturing the query DSL, hit count, and total latency. Facet computation is timed separately from document retrieval.
  - **Kafka Producer/Consumer Tracing:** Produced events create producer spans with the topic, partition, and offset. Consumed events create consumer spans linked to the producer span via trace context propagation in message headers.
  - **Catalog Metrics:** Counter metrics for CRUD operations (`catalog.crud.operations_total` with labels: operation, result), histogram metrics for search latency (`catalog.search.duration` with labels: query_type, result_count), gauge metrics for cache hit rates (`catalog.cache.hit_rate` with labels: cache_type), and counter metrics for inventory updates (`catalog.inventory.updates_total` with labels: reason).
- **Description:** The observability adapter uses the `@opentelemetry/api` and `@opentelemetry/sdk-node` packages for automatic and manual instrumentation. Auto-instrumentation is enabled for HTTP, gRPC, and Prisma queries. Manual spans are added for search operations and Kafka interactions to provide deeper visibility. Metrics are exported via OTLP to the Analytics service. Structured logs use the `pino` logger with OTel trace context injection, enabling log-trace correlation in the centralized logging backend.
