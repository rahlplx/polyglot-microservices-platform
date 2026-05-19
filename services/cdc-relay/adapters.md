# CDC Relay Service - Adapters Definition

> Language: Java | Role: Debezium-based Change Data Capture relay, configured via Kafka Connect REST API

## Inbound Adapters

### gRPC Handler

- **Maps to:** None (the CDC Relay does not expose a gRPC server; it is managed via Kafka Connect REST API)
- **Description:** The CDC Relay service does not expose a gRPC server interface. All management operations are performed through the Kafka Connect REST API, which is the standard interface for Debezium connector lifecycle management. The service's own business logic (connector creation, status monitoring, and error recovery) is triggered by a scheduled polling mechanism that periodically checks connector health and by the Kafka Connect REST API's callback mechanisms. This design aligns with the Debezium ecosystem's operational model, where Kafka Connect is the primary control plane for CDC connectors. If a gRPC management interface is needed in the future (for example, to integrate with a service mesh control plane), it can be added as a separate adapter without modifying the core connector management logic.

### REST Controller

- **Maps to:** None directly (the CDC Relay delegates to the Kafka Connect REST API at localhost:8083)
- **Description:** The CDC Relay service does not expose its own REST API for connector management. Instead, it acts as a management wrapper around the Kafka Connect REST API, which runs as a separate process (typically in the same pod for Kubernetes deployments). The CDC Relay's scheduled tasks call the Kafka Connect REST API to create, monitor, and manage connectors. The Kafka Connect REST API itself is available at `http://localhost:8083/connectors` and follows the standard Kafka Connect REST protocol. The CDC Relay includes a lightweight HTTP server (port 8081) that exposes health check and metrics endpoints for Kubernetes liveness/readiness probes, but this is not a business API.

### Event Consumer

- **Maps to:** None (the CDC Relay does not consume business domain events)
- **Description:** The CDC Relay service does not consume domain events from the Kafka backbone. It is a pure producer of change events: Debezium connectors read the source database's write-ahead log (WAL) and produce change events to Kafka topics. The CDC Relay's own lifecycle is driven by scheduled tasks (for health monitoring and automatic recovery) and by the Kafka Connect REST API's status callbacks. However, the service does monitor a configuration topic (`cdc-relay.config`) that receives connector configuration updates from the Schema Registry service when schema changes are detected, allowing the CDC Relay to automatically update affected connectors with new transformation rules or schema mappings.

## Outbound Adapters

### Persistence Adapter

- **Database:** PostgreSQL (source databases, read-only) and Kafka Connect's internal state storage
- **ORM/Query Approach:** JDBC for source database schema queries, Kafka Connect's internal status topic for connector state
- **Description:** The persistence adapter manages two distinct data access patterns. First, it uses JDBC to query the source PostgreSQL databases for schema discovery, connectivity testing, and replication identity validation. These queries are always read-only and use a dedicated replication user with limited privileges (USAGE on schema, SELECT on tables). Second, it relies on Kafka Connect's internal state storage (the `connect-status` and `connect-offsets` topics in Kafka) for connector state management. The adapter does not maintain its own database for connector configurations; instead, it reads and writes connector configurations through the Kafka Connect REST API, which persists them in Kafka's config storage topic. This design ensures that connector configurations are durable and can be recovered if the Kafka Connect cluster is restarted. The adapter includes a connection pool for each source database with a maximum of 5 connections, sufficient for the low-frequency schema queries and health checks.

### Messaging Adapter

- **Kafka Topics:**
  - **Produced (via Debezium):** Per-connector change event topics (e.g., `cdc.catalog.products`, `cdc.orders.order_lines`), schema change topics (e.g., `cdc.catalog.schema-changes`)
  - **Consumed:** `cdc-relay.config` (connector configuration updates from Schema Registry)
- **Serialization:** Debezium's built-in Protobuf or JSON serialization, with schema validation via Schema Validator port
- **Description:** The messaging adapter manages the CDC pipeline's interaction with Kafka. Debezium connectors produce change events to topic names derived from the connector configuration: `{prefix}.{database}.{table}` for data events and `{prefix}.{schema-changes}` for schema change events. The adapter configures each connector with a Single Message Transform (SMT) pipeline that transforms the raw Debezium envelope into the domain event format expected by downstream consumers. The SMT pipeline includes: topic routing (mapping the Debezium topic name to the domain event topic name), payload transformation (extracting the after-image from the Debezium envelope and mapping it to the Protobuf schema), and metadata injection (adding CloudEvents headers with the event type, source, and timestamp). The adapter uses Kafka Connect's converter configuration to specify Protobuf serialization, with the schema ID retrieved from the Schema Registry for each event type. The `cdc-relay.config` consumer uses a committed consumer group (`cdc-relay-config-consumer`) to receive configuration updates, which trigger connector reconfiguration without requiring a service restart.

### External Service Adapter

- **External Dependencies:** None (the CDC Relay communicates only with internal infrastructure)
- **Behind ACL:** Not applicable
- **Description:** The CDC Relay service does not communicate with any external or third-party services. It interacts exclusively with internal infrastructure components: the source PostgreSQL databases (for schema queries and logical replication), the Kafka Connect cluster (for connector lifecycle management), and the Schema Registry service (for schema validation). This self-contained design is intentional: the CDC Relay is a critical infrastructure component that must remain operational even when external services are unavailable. Its only external dependency is the Kafka Connect REST API, which runs as part of the internal Kafka infrastructure and is subject to the same availability SLAs.

### Observability Adapter

- **OTel Instrumentation Points:**
  - **Connector Health Monitoring:** Each connector health check creates a span with the connector name, status, and lag. Failed connectors trigger error span events with the failure reason and stack trace.
  - **Schema Validation Tracing:** Each schema validation operation creates a span with the subject, version, and compatibility result.
  - **Kafka Connect API Tracing:** Each Kafka Connect REST API call creates a client span with the HTTP method, path, status code, and latency.
  - **CDC Metrics:** Gauge metrics for connector lag (`cdc.connector.lag_ms` with labels: connector, database, table), counter metrics for events captured (`cdc.connector.events_captured_total` with labels: connector, table, operation), gauge metrics for connector status (`cdc.connector.status` with labels: connector, status), counter metrics for connector restarts (`cdc.connector.restarts_total` with labels: connector, reason), and histogram metrics for snapshot progress (`cdc.connector.snapshot_progress` with labels: connector, table).
- **Description:** The observability adapter uses the OpenTelemetry Java agent for automatic instrumentation of HTTP client calls (to the Kafka Connect REST API) and JDBC operations (to source databases). Manual spans are added for connector health monitoring, schema validation, and configuration update processing. The adapter includes a custom `DebeziumMetricsExporter` that reads Debezium's JMX metrics (via the Kafka Connect REST API's metrics endpoint) and exports them as OTel gauge metrics, providing visibility into connector throughput, lag, and error rates. Structured logs use Logback with the OTel log appender and include the connector name as a structured field for filtering. The adapter also publishes connector health events to the `com.company.analytics.alert.triggered` topic when a connector's lag exceeds a configurable threshold or when a connector transitions to a FAILED state, ensuring that the on-call team is notified of CDC pipeline issues.
