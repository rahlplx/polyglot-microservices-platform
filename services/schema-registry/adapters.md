# Schema Registry Service - Adapters Definition

> Language: Go | Role: Buf integration, breaking change detection, schema management

## Inbound Adapters

### gRPC Handler

- **Maps to:** `schemaregistry.v1.SchemaRegistryService`
- **RPC Methods:** `Register`, `Get`, `Validate`, `CheckBreaking`, `List`
- **Description:** The gRPC handler adapter implements the `SchemaRegistryService` proto definition using the `google.golang.org/grpc` library. The `Register` RPC maps to `RegisterSchemaPort`, accepting a schema definition and subject, validating and registering it, and returning the assigned schema ID and version. The `Get` RPC maps to `GetSchemaPort`, accepting a subject and optional version, and returning the schema definition with its metadata. The `Validate` RPC maps to `ValidateSchemaPort`, accepting a schema definition and validation level, and returning validation results without registering the schema. The `CheckBreaking` operation is exposed as a separate RPC method that maps to `CheckBreakingPort`, accepting a proposed schema and a reference version, and returning a detailed breaking change analysis. The `List` RPC maps to `ListSchemasPort`, accepting optional filter criteria such as subject prefix and schema type, and returning a paginated list of schema subject summaries for browsing and discovery. Server interceptors handle authentication (validating the caller's SPIFFE SVID), request logging, and OpenTelemetry span creation. The gRPC server runs on port 50058 with mTLS enforced, and supports server reflection for development tooling. The handler includes request size limits (maximum 5MB per schema definition) and timeout configuration (30 seconds for breaking change checks, which may take longer for large schemas).

### REST Controller

- **Maps to:** `/api/v1/schemas/*`
- **OpenAPI Path Prefix:** `/api/v1/schemas`
- **Description:** The REST controller exposes the Schema Registry's operations over HTTP/JSON for tools and workflows that prefer REST over gRPC. The controller is implemented using Go's standard `net/http` package with a custom multiplexer and middleware chain for authentication, logging, and metrics. Path-to-port mappings: `POST /api/v1/schemas/subjects/{subject}/versions` maps to `RegisterSchemaPort` (compatible with the Confluent Schema Registry API for drop-in compatibility), `GET /api/v1/schemas/subjects/{subject}/versions/{version}` maps to `GetSchemaPort`, `POST /api/v1/schemas/subjects/{subject}/validate` maps to `ValidateSchemaPort`, and `POST /api/v1/schemas/subjects/{subject}/check-breaking` maps to `CheckBreakingPort`. Additional endpoints include `GET /api/v1/schemas/subjects` for listing all subjects, `GET /api/v1/schemas/subjects/{subject}/versions` for listing all versions of a subject, and `DELETE /api/v1/schemas/subjects/{subject}` for soft-deleting a subject. The REST API is designed to be compatible with the Confluent Schema Registry's REST interface where possible, enabling existing tools and Kafka connectors to use the Schema Registry without modification.

### Event Consumer

- **Maps to:** `com.company.cdc.*.schema-changes`
- **Description:** The Schema Registry consumes schema change events from the CDC Relay to detect schema drift in source databases. When a schema change is detected (e.g., an ALTER TABLE operation on a source database table), the consumer checks whether the change affects any registered Protobuf schemas that map to the changed table. If a mapping exists, the consumer automatically runs a compatibility check between the current database schema and the registered Protobuf schema, and publishes a warning event if incompatibilities are detected. The consumer also triggers an update to the CDC Relay's connector configuration when a schema change requires a transformation rule update, ensuring that CDC events continue to conform to the expected Protobuf schema even after source database schema changes. The consumer is implemented using the `segmentio/kafka-go` library with a committed consumer group (`schema-registry-cdc-consumer`). Schema change events are processed with high priority to minimize the window during which CDC events may be produced with an outdated schema.

## Outbound Adapters

### Persistence Adapter

- **Database:** PostgreSQL 16 with pgx driver and custom SQL
- **ORM/Query Approach:** Custom SQL using pgx with sqlc for type-safe query generation
- **Description:** The persistence adapter manages all database interactions for the Schema Registry service. The adapter uses the same pgx + sqlc stack as the Payment service for compile-time SQL type safety. The primary tables are `subjects` (subject name, compatibility level, metadata), `schemas` (schema ID, subject, version, type, definition, fingerprint, references, status), and `schema_references` (source schema ID, target schema ID, reference name). The adapter uses PostgreSQL's full-text search capabilities (tsvector on subject names and descriptions) for the subject listing and search endpoints. The schema definition is stored as TEXT with a GIN index on the fingerprint column for fast deduplication checks. The adapter implements optimistic concurrency control using a version column on the subjects table, preventing race conditions when multiple services register schemas for the same subject simultaneously. Database migrations are managed by golang-migrate and applied automatically during service startup.

### Messaging Adapter

- **Kafka Topics:**
  - **Produced:** `com.company.schema-registry.schema-registered`, `com.company.schema-registry.schema-deprecated`, `com.company.schema-registry.compatibility-violation`
  - **Consumed:** `com.company.cdc.*.schema-changes`
- **Serialization:** Protobuf (produced events), CloudEvents JSON (consumed CDC events)
- **Description:** The messaging adapter handles all Kafka interactions for the Schema Registry service. Produced events are published directly (without the transactional outbox pattern, since the Schema Registry's database writes and event publications do not need to be transactionally consistent with each other; a missed event is acceptable because consumers can always query the REST API for the latest schema). The `schema-registered` event notifies the CDC Relay and other services that a new schema version is available for use. The `schema-deprecated` event signals that a schema version should no longer be used for new development, though existing consumers may continue using it. The `compatibility-violation` event is published when an automated compatibility check detects a potential incompatibility, typically triggered by a schema change event from the CDC Relay. Consumed events are CDC schema change events that trigger the drift detection workflow described in the event consumer adapter.

### External Service Adapter

- **External Dependencies:** Buf CLI (open-source tool, executed as a local subprocess)
- **Behind ACL:** No (open-source tool, no external API calls)
- **Description:** The external service adapter manages the execution of the Buf CLI and protoc compiler as local subprocesses. These tools are open-source and do not make any external API calls; they operate entirely on local files and stdin/stdout. The adapter includes a binary manager that downloads and caches the appropriate Buf and protoc versions from their official GitHub releases, verifying SHA-256 checksums before execution. The adapter implements a subprocess pool with a maximum of 10 concurrent compilations to prevent resource exhaustion during burst validation requests. Each subprocess is executed with a timeout (30 seconds for lint, 60 seconds for breaking change checks) and resource limits (maximum 512MB memory, 1 CPU core). Failed subprocesses are cleaned up immediately to prevent zombie processes.

### Observability Adapter

- **OTel Instrumentation Points:**
  - **Schema Registration Tracing:** Each registration operation creates a span with the subject, version, schema type, and the result of each validation step (syntax, compatibility, breaking change). The span includes links to previous versions for trace-level schema evolution tracking.
  - **Validation Tracing:** Each validation operation creates a span with the subject, validation level, number of errors and warnings, and the duration of each validation phase (parsing, linting, compatibility checking).
  - **Buf CLI Execution Tracing:** Each Buf CLI execution creates a child span with the command, arguments, exit code, and duration. The span captures stdout and stderr (truncated to 10KB) for debugging validation failures.
  - **Schema Registry Metrics:** Counter metrics for schema registrations (`schema.registry.registrations_total` with labels: subject, type, result), counter metrics for validation checks (`schema.registry.validations_total` with labels: level, result), histogram metrics for validation duration (`schema.registry.validation_duration` with labels: level), gauge metrics for registered subjects and versions (`schema.registry.subjects`, `schema.registry.versions`), and counter metrics for compatibility violations detected (`schema.registry.violations_total` with labels: subject, type).
- **Description:** The observability adapter uses the OpenTelemetry Go SDK for manual and automatic instrumentation. Auto-instrumentation covers HTTP and gRPC server operations. Manual spans are added for schema validation pipeline stages and Buf CLI subprocess execution. The adapter includes a custom span processor that adds schema-specific attributes (subject, version, fingerprint) to all spans within a schema operation context. Structured logs use the `slog` package with JSON formatting and include the subject and version as structured fields for filtering. The adapter also exports a Prometheus-compatible metrics endpoint on port 9090 for direct scraping by monitoring infrastructure.
