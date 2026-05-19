# CDC Relay Service - Ports Definition

> Language: Java | Role: Debezium-based Change Data Capture relay, configured via Kafka Connect REST API

## Inbound Ports (Driving / Use Case Interfaces)

### StartReplicationPort

- **Port Name:** `StartReplicationPort`
- **Input Type:** `StartReplicationRequest` (source_database: string, source_tables: list<string>, target_topic_prefix: string, snapshot_mode: enum [INITIAL, SCHEMA_ONLY, NEVER, WHEN_NEEDED], pipeline_config: PipelineConfig)
- **Output Type:** `StartReplicationResponse` (connector_name: string, status: ConnectorStatus, snapshot_progress: optional<SnapshotProgress>, started_at: timestamp)
- **Error Types:** `DatabaseConnectionError`, `ConnectorAlreadyExistsError`, `SchemaValidationError`, `ConfigurationError`
- **Description:** Starts a new CDC replication pipeline by creating a Debezium connector configuration and submitting it to the Kafka Connect REST API. The port validates the source database connectivity and table schemas before creating the connector, ensuring that the replication can proceed without immediate errors. The `snapshot_mode` parameter controls the initial data capture behavior: INITIAL performs a full snapshot of existing data before streaming changes, SCHEMA_ONLY captures only the schema and then streams changes from the current position, NEVER starts streaming from the current position without any snapshot, and WHEN_NEEDED performs a snapshot only if no previous offset is available. The `pipeline_config` parameter allows customization of Debezium's behavior, including column include/exclude lists, transformation pipelines, and error handling strategies. Upon successful connector creation, the port monitors the connector status until it reaches a RUNNING state or a configurable timeout expires, returning the final status and any snapshot progress information.

### GetReplicationStatusPort

- **Port Name:** `GetReplicationStatusPort`
- **Input Type:** `GetReplicationStatusRequest` (connector_name: string, include_task_details: bool, include_metrics: bool)
- **Output Type:** `GetReplicationStatusResponse` (connector_name: string, status: ConnectorStatus, tasks: list<TaskStatus>, lag_ms: optional<int64>, source_offset: optional<SourceOffset>, snapshot_progress: optional<SnapshotProgress>, error_message: optional<string>, metrics: optional<ConnectorMetrics>)
- **Error Types:** `ConnectorNotFoundError`, `KafkaConnectUnavailableError`
- **Description:** Retrieves the current status of a CDC replication connector by querying the Kafka Connect REST API. The response includes the connector's overall status (RUNNING, PAUSED, FAILED, UNASSIGNED), the status of each task within the connector, the current replication lag (the time difference between the source database's current position and the last captured change event), and the source offset (the position in the source database's transaction log from which the next change will be captured). When `include_task_details` is true, the response includes per-task status with error messages for failed tasks. When `include_metrics` is true, the response includes JMX-style metrics from the connector, such as the number of events captured, the number of events filtered, and the throughput in events per second. The lag metric is critical for monitoring: if the lag exceeds a configurable threshold, an alert is published to the Notification service. The port includes a cache with a 10-second TTL to avoid overwhelming the Kafka Connect REST API with frequent status queries from monitoring dashboards.

## Outbound Ports (Driven / Infrastructure Interfaces)

### PauseReplicationPort

- **Port Name:** `PauseReplicationPort`
- **Input Type:** `PauseReplicationRequest` (connector_name: string, reason: enum [MAINTENANCE_WINDOW, SCHEMA_MIGRATION, UPSTREAM_ISSUE, MANUAL_PAUSE], resume_at: optional<timestamp>, notify_on_resume: bool)
- **Output Type:** `PauseReplicationResponse` (connector_name: string, previous_status: ConnectorStatus, new_status: ConnectorStatus, paused_at: timestamp, scheduled_resume: optional<timestamp>)
- **Error Types:** `ConnectorNotFoundError`, `ConnectorAlreadyPausedError`, `KafkaConnectUnavailableError`
- **Description:** Pauses a running CDC replication connector, temporarily stopping change event capture without deleting the connector or its offsets. Pausing is preferred over deletion when the interruption is temporary, because the connector retains its position in the source database's transaction log and can resume from that position when unpaused. The port calls the Kafka Connect REST API's pause endpoint and waits for the connector to transition to a PAUSED state before returning. The `resume_at` parameter allows scheduling an automatic resume at a specific time, which is useful for planned maintenance windows where the source database will be temporarily unavailable (such as during a schema migration or a database upgrade). The `notify_on_resume` flag triggers a notification event when the connector automatically resumes, ensuring that the operations team is aware that the CDC pipeline has restarted. The port publishes a `cdc.connector.paused` event for monitoring and audit purposes, and the Analytics service tracks pause frequency and duration to identify services that frequently interrupt their CDC pipelines.

### ResumeReplicationPort

- **Port Name:** `ResumeReplicationPort`
- **Input Type:** `ResumeReplicationRequest` (connector_name: string, reset_offset: bool, new_offset: optional<SourceOffset>)
- **Output Type:** `ResumeReplicationResponse` (connector_name: string, previous_status: ConnectorStatus, new_status: ConnectorStatus, resumed_at: timestamp, current_offset: SourceOffset, lag_ms: int64)
- **Error Types:** `ConnectorNotFoundError`, `ConnectorNotPausedError`, `KafkaConnectUnavailableError`, `OffsetResetFailedError`
- **Description:** Resumes a paused CDC replication connector, restarting change event capture from the connector's last committed offset. The port calls the Kafka Connect REST API's resume endpoint and monitors the connector until it transitions to a RUNNING state. The response includes the current replication lag, which indicates how far behind the connector is relative to the source database's current position; a large lag after resume is expected and the connector will catch up at its maximum throughput rate. The `reset_offset` parameter allows resetting the connector's offset to a specific position, which is useful for reprocessing events after a data correction or for skipping corrupted events. When `reset_offset` is true, the `new_offset` parameter must specify the target position in the source database's transaction log (LSN for PostgreSQL). Offset resets are audited and require the `cdc:admin` scope to prevent accidental data loss from resetting to an incorrect position. The port publishes a `cdc.connector.resumed` event for monitoring, and if the lag after resume exceeds a configurable threshold, an alert is published to the Notification service for on-call attention.

### SourceDatabasePort

- **Port Name:** `SourceDatabasePort`
- **Operations:**
  - `TestConnection(config: DatabaseConfig) -> ConnectionTestResult`: Tests connectivity to the source database.
  - `GetSchema(database: string, tables: list<string>) -> DatabaseSchema`: Retrieves the schema of the source tables.
  - `ValidateReplicationIdentity(database: string, tables: list<string>) -> ValidationResult`: Validates that tables have a replication identity (primary key or unique index) suitable for CDC.
- **Technology:** PostgreSQL (source database, using logical replication protocol)
- **ACL Required:** No (internal infrastructure, read-only access to source databases)
- **Description:** The source database port provides read-only access to the source databases for connectivity testing, schema discovery, and replication identity validation. The CDC relay does not write to the source database; it reads change events through PostgreSQL's logical replication protocol, which is managed by Debezium's PostgreSQL connector. The port validates that each source table has a replication identity (either a primary key or a REPLICA IDENTITY USING INDEX) before allowing a replication pipeline to be created. Tables without a replication identity cannot be reliably captured because DELETE and UPDATE events would not include enough information to identify the affected row. The port also checks that the source database has logical replication enabled (wal_level = logical) and that the replication user has the REPLICATION privilege.

### KafkaProducerPort

- **Port Name:** `KafkaProducerPort`
- **Operations:**
  - `ConfigureConnector(config: ConnectorConfig) -> ConnectorCreationResult`: Creates a Debezium connector via the Kafka Connect REST API.
  - `UpdateConnector(name: string, config: ConnectorConfig) -> ConnectorUpdateResult`: Updates an existing connector's configuration.
  - `DeleteConnector(name: string) -> void`: Deletes a connector and its tasks.
  - `PauseConnector(name: string) -> void`: Pauses a connector temporarily.
  - `ResumeConnector(name: string) -> void`: Resumes a paused connector.
  - `RestartConnector(name: string) -> void`: Restarts a failed connector.
  - `GetConnectorStatus(name: string) -> ConnectorStatusResult`: Queries the connector's current status.
- **Technology:** Kafka Connect REST API (Debezium connectors)
- **ACL Required:** No (internal infrastructure)
- **Description:** The Kafka producer port manages all interactions with the Kafka Connect REST API for Debezium connector lifecycle management. The port translates the domain-oriented `StartReplicationRequest` into a Debezium-specific connector configuration JSON, including the database connection details, table include lists, topic routing rules, and transformation pipelines. The port supports all connector lifecycle operations: create, update, delete, pause, resume, and restart. The restart operation is particularly important for automated recovery: when the CDC relay detects a failed connector (via the `GetReplicationStatusPort`), it can automatically restart the connector after a configurable backoff period. The port includes rate limiting for the Kafka Connect REST API (maximum 10 requests per second) to prevent overwhelming the Kafka Connect cluster during bulk connector management operations.

### SchemaValidatorPort

- **Port Name:** `SchemaValidatorPort`
- **Operations:**
  - `ValidateSchema(event_schema: EventSchema) -> ValidationResult`: Validates that a change event's schema is compatible with the Schema Registry.
  - `RegisterSchema(subject: string, schema: EventSchema) -> SchemaRegistrationResult`: Registers a new schema version with the Schema Registry.
  - `CheckCompatibility(subject: string, schema: EventSchema) -> CompatibilityResult`: Checks if a schema is compatible with the latest registered version.
- **Technology:** Schema Registry Service (gRPC) and Buf CLI for Protobuf schema validation
- **ACL Required:** No (internal service-to-service communication via mTLS)
- **Description:** The schema validator port ensures that all change events produced by Debezium connectors conform to the schemas registered in the Schema Registry. Before a new connector is started, the port validates that the source table's schema maps to a valid Protobuf schema in the Schema Registry. If the schema does not exist, the port can optionally register it (with appropriate approval workflows in production). If the source table's schema has changed since the last registered version, the port checks backward compatibility using the Schema Registry's compatibility rules. Incompatible schema changes are flagged and the connector creation is blocked until the schema is resolved, preventing breaking changes from propagating through the event backbone. The port also validates that Debezium's Single Message Transforms (SMTs) produce event payloads that match the expected Protobuf schema, ensuring that the transformation pipeline does not silently corrupt the event structure.
