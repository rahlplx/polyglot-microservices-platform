# Analytics Service - Adapters Definition

> Language: Python | Role: Dual interface (gRPC for queries, events for ingestion), metrics and trace analysis

## Inbound Adapters

### gRPC Handler

- **Maps to:** `analytics.v1.AnalyticsService`
- **RPC Methods:** `GetMetrics`, `Query`, `GetDashboard`, `GetReport`
- **Description:** The gRPC handler adapter implements the `AnalyticsService` proto definition for query-side operations. The `GetMetrics` RPC maps to `GetMetricsPort`, accepting a metric query specification and returning aggregated time series data. The `Query` RPC maps to `QueryTracesPort`, accepting trace search criteria and returning matching traces with their span trees. The `GetDashboard` RPC maps to `GetDashboardPort`, accepting a dashboard ID with variables and time range, and returning the populated dashboard definition with live data for all panels. The `GetReport` RPC maps to `GetReportPort`, accepting a report type with parameters, time range, and format specification, and returning a generated analytical report with curated insights for business stakeholders. The handler is implemented using the `grpcio` library with async support via `grpcio-health-checking` for the standard health protocol. Server interceptors handle authentication (validating the caller's SPIFFE SVID for internal service-to-service calls), request logging with correlation IDs, and OpenTelemetry span creation. The handler includes request validation that rejects overly broad queries before they reach the database, preventing accidental denial-of-service from poorly constructed dashboard queries. The gRPC server runs on port 50057 with mTLS enforced. A separate OTLP receiver runs on port 4317 for OpenTelemetry SDK telemetry ingestion (traces and metrics from other services), which bypasses the gRPC handler and writes directly to the storage backend.

### REST Controller

- **Maps to:** `/api/v1/analytics/*`
- **OpenAPI Path Prefix:** `/api/v1/analytics`
- **Description:** The REST controller exposes the Analytics service's query operations over HTTP/JSON for dashboard UI consumption and external reporting tools. The controller is implemented using FastAPI with automatic OpenAPI spec generation and Pydantic models for request/response validation. Path-to-port mappings: `POST /api/v1/analytics/metrics/query` maps to `GetMetricsPort` (POST method to support complex query bodies), `POST /api/v1/analytics/traces/query` maps to `QueryTracesPort`, and `GET /api/v1/analytics/dashboards/{id}` maps to `GetDashboardPort`. Additional endpoints include `GET /api/v1/analytics/dashboards` for listing available dashboards, `PUT /api/v1/analytics/dashboards/{id}` for updating dashboard configurations, and `GET /api/v1/analytics/dependencies` for retrieving the service dependency graph. The REST controller supports CORS for browser-based dashboard access and implements token-based authentication with JWT tokens issued by the Identity service.

### Event Consumer

- **Maps to:** All `com.company.*` domain event topics
- **Description:** The event consumer adapter is the data ingestion pipeline for the Analytics service, subscribing to every domain event topic in the system. The consumer is implemented using the `confluent-kafka-python` library with a committed consumer group (`analytics-event-consumer`). Each consumed event is processed by the `EventConsumerPort`, which transforms the event payload into analytics records and writes them to ClickHouse. The consumer implements a topic-to-transformer registry: each event type has a registered transformer function that maps the event to the appropriate ClickHouse table schema. The consumer supports parallel processing with a configurable concurrency limit (default: 50 concurrent events) to handle burst volumes. Failed events are retried three times with exponential backoff and then forwarded to the `analytics.events.dlq` dead letter topic. The consumer includes adaptive batching: events are accumulated in memory for up to 5 seconds or 10,000 events (whichever comes first) before being flushed to ClickHouse, optimizing write throughput without introducing excessive latency.

## Outbound Adapters

### Persistence Adapter

- **Database:** ClickHouse (OLAP) for metrics and traces, PostgreSQL for dashboard configurations
- **ORM/Query Approach:** clickhouse-driver for ClickHouse queries, SQLAlchemy for PostgreSQL
- **Description:** The persistence adapter manages dual-database interactions for the Analytics service. ClickHouse is used for all high-volume analytical data: metric time series, trace spans, and event fact tables. The adapter uses the `clickhouse-driver` library with native protocol support for maximum write throughput. Batch writes use the INSERT format with optimized column ordering matching the table's sort key, minimizing merge overhead on the MergeTree engine. PostgreSQL is used for low-volume configuration data: dashboard definitions, alert rules, and transformer registry configurations. SQLAlchemy manages the PostgreSQL schema with Alembic migrations. The adapter includes a connection health checker that monitors both databases and reports their status through the health check endpoint. When ClickHouse is unavailable, the adapter buffers incoming writes in a local disk queue (up to 1GB) and flushes them when connectivity is restored, ensuring that no analytics data is lost during transient outages.

### Messaging Adapter

- **Kafka Topics:**
  - **Produced:** `com.company.analytics.alert.triggered` (emitted when a metric threshold is crossed)
  - **Consumed:** All `com.company.*` domain event topics (comprehensive event consumption for analytics)
- **Serialization:** CloudEvents JSON for consumed events (flexible for polyglot producers), Protobuf for produced events
- **Description:** The messaging adapter handles all Kafka interactions for the Analytics service. The adapter's primary role is consumption: it subscribes to every domain event topic and feeds events into the `EventConsumerPort` for transformation and storage. The consumer uses a topic pattern subscription (`com.company.*`) to automatically discover and consume new event topics as services are added to the system. Produced events are limited to alert notifications: when the Analytics service detects that a metric has crossed a configured threshold (e.g., error rate exceeds 5%, latency P99 exceeds 2 seconds), it publishes an alert event that is consumed by the Notification service for on-call alerting. The adapter uses the `confluent-kafka-python` library with the transactional producer API for alert events and a committed consumer group for domain event consumption.

### External Service Adapter

- **External Dependencies:** None (the Analytics service is a pure consumer and query engine)
- **Behind ACL:** Not applicable
- **Description:** The Analytics service does not communicate with any external or third-party services. It is a pure data consumer and query engine, ingesting events from the internal Kafka backbone and serving queries from internal clients via gRPC and REST. All data flows into the service through the event consumer, and all data flows out through the query interfaces. This self-contained design simplifies deployment and eliminates external dependency risks. If future requirements include integration with external monitoring tools (such as PagerDuty for alerting or Grafana for dashboard embedding), those integrations would be handled through the Notification service (for alerting) or through the REST API (for Grafana data source integration), without requiring the Analytics service itself to communicate externally.

### Observability Adapter

- **OTel Instrumentation Points:**
  - **Query Execution Tracing:** Each gRPC/REST query creates a server span with the query type, time range, and result count. ClickHouse query execution creates child spans with the SQL statement (sanitized of sensitive values), execution time, and rows scanned.
  - **Event Ingestion Tracing:** Each batch of consumed events creates a consumer span with the topic, partition, offset range, and event count. The transformation and write steps create child spans with the number of records produced.
  - **OTLP Receiver Tracing:** Each received telemetry item (from other services' OTel SDKs) creates a processing span with the telemetry type (trace or metric), service name, and item count.
  - **Analytics Metrics:** Counter metrics for queries executed (`analytics.queries.total` with labels: type, result), histogram metrics for query latency (`analytics.query.duration` with labels: type), counter metrics for events ingested (`analytics.events.ingested_total` with labels: event_type, source_service), gauge metrics for ClickHouse write buffer size (`analytics.buffer.size`), and counter metrics for alerts triggered (`analytics.alerts.triggered_total` with labels: alert_name, severity).
- **Description:** The observability adapter uses the `opentelemetry-api` and `opentelemetry-sdk` Python packages. The Analytics service is unique in that it both produces and consumes OpenTelemetry telemetry: it receives OTLP data from other services (acting as a telemetry backend) and also instruments its own operations. Self-monitoring metrics are carefully separated from ingested metrics to prevent feedback loops. The adapter exports self-monitoring telemetry to a separate OTLP endpoint (or to the same ClickHouse database with a different table prefix) to keep self-observability data distinct from customer data. Structured logs use Python's `logging` module with JSON formatting and OTel trace context injection.
