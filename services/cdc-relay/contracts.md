# CDC Relay Service - Contracts Definition

> Language: Java | Role: Debezium-based Change Data Capture relay, configured via Kafka Connect REST API

## gRPC Contract

The CDC Relay service does not expose a gRPC server. All connector management is performed through the Kafka Connect REST API at `http://localhost:8083/connectors`, which is the standard Debezium/Kafka Connect interface.

If a gRPC management interface is required in the future for integration with a service mesh control plane or custom management UI, the following service definition would be appropriate:

```protobuf
package cdcrelay.v1;

service CDCRelayService {
  rpc StartReplication(StartReplicationRequest) returns (StartReplicationResponse);
  rpc GetReplicationStatus(GetReplicationStatusRequest) returns (GetReplicationStatusResponse);
  rpc PauseReplication(PauseReplicationRequest) returns (PauseReplicationResponse);
  rpc ResumeReplication(ResumeReplicationRequest) returns (ResumeReplicationResponse);
  rpc ListConnectors(ListConnectorsRequest) returns (ListConnectorsResponse);
}
```

However, this contract is not currently implemented and should not be considered active.

## OpenAPI Contract

The CDC Relay service does not expose its own REST API for business operations. It delegates connector lifecycle management to the Kafka Connect REST API, which follows the standard Kafka Connect REST protocol:

### Kafka Connect REST API (Internal)

| Method | Path | Description |
|---|---|---|
| `POST` | `/connectors` | Create a new connector with the given configuration |
| `GET` | `/connectors` | List all active connector names |
| `GET` | `/connectors/{name}` | Get detailed information about a connector |
| `GET` | `/connectors/{name}/status` | Get the current status of a connector |
| `PUT` | `/connectors/{name}/config` | Update a connector's configuration |
| `DELETE` | `/connectors/{name}` | Delete a connector and its tasks |
| `POST` | `/connectors/{name}/restart` | Restart a connector |
| `PUT` | `/connectors/{name}/pause` | Pause a connector |
| `PUT` | `/connectors/{name}/resume` | Resume a paused connector |

### CDC Relay Health Endpoints (Internal)

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe for the CDC Relay management process |
| `GET` | `/ready` | Readiness probe indicating the relay can manage connectors |
| `GET` | `/metrics` | Prometheus-format metrics for connector health and lag |

These health endpoints are exposed on port 8081 and are intended only for Kubernetes probes and internal monitoring. They are not exposed through the Gateway.

## Event Contracts

### CloudEvents Type Prefix

`com.company.cdc.`

### Produced Event Types

The CDC Relay produces change data capture events through Debezium connectors. Each event represents a row-level change (INSERT, UPDATE, DELETE) in a source database table. The event format follows the Debezium envelope structure with CloudEvents wrapping:

| Event Type | Payload Schema | Consumer Services |
|---|---|---|
| `com.company.cdc.catalog.products` | `CDCEnvelope<ProductRecord>` | Analytics |
| `com.company.cdc.catalog.variants` | `CDCEnvelope<VariantRecord>` | Analytics |
| `com.company.cdc.orders.orders` | `CDCEnvelope<OrderRecord>` | Analytics |
| `com.company.cdc.orders.order_lines` | `CDCEnvelope<OrderLineRecord>` | Analytics |
| `com.company.cdc.payments.payments` | `CDCEnvelope<PaymentRecord>` | Analytics |
| `com.company.cdc.payments.refunds` | `CDCEnvelope<RefundRecord>` | Analytics |
| `com.company.cdc.identity.certificates` | `CDCEnvelope<CertificateRecord>` | Analytics |
| `com.company.cdc.*.schema-changes` | `SchemaChangeEvent` | Schema Registry, Analytics |

### Event Details

**CDCEnvelope:**
The standard envelope for all CDC events, wrapping the row-level change data with metadata:

```json
{
  "specversion": "1.0",
  "type": "com.company.cdc.catalog.products",
  "source": "/cdc/catalog",
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "time": "2024-01-15T10:30:00Z",
  "datacontenttype": "application/protobuf",
  "data": {
    "before": null,
    "after": { "id": "prod-123", "name": "Widget", "base_price_cents": 999 },
    "op": "c",
    "ts_ms": 1705312200000,
    "source": {
      "version": "2.4.0.Final",
      "connector": "postgresql",
      "name": "catalog",
      "ts_ms": 1705312200000,
      "snapshot": "false",
      "db": "catalog_db",
      "sequence": "[\"1234567\",\"1234568\"]",
      "schema": "public",
      "table": "products",
      "txId": 12345,
      "lsn": 123456789,
      "xmin": null
    }
  }
}
```

The `op` field indicates the operation type: `c` for create (INSERT), `u` for update, `d` for delete, and `r` for read (snapshot). The `before` field contains the previous row state for UPDATE and DELETE operations, and the `after` field contains the new row state for INSERT and UPDATE operations. The `source` field includes Debezium's source metadata with the database, table, transaction ID, and log sequence number for exactly-once processing and ordering guarantees.

**SchemaChangeEvent:**
Emitted when a schema change is detected in the source database (e.g., ALTER TABLE, CREATE TABLE). The payload includes the DDL statement, the affected database and table, and the timestamp. The Schema Registry service consumes these events to detect schema drift and trigger compatibility checks. The Analytics service logs schema changes for audit purposes.

### Connector Configuration Template

Each Debezium connector is configured with the following standard properties (in addition to the source-specific database connection properties):

```json
{
  "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
  "database.hostname": "${SOURCE_DB_HOST}",
  "database.port": "5432",
  "database.user": "${REPLICATION_USER}",
  "database.password": "${REPLICATION_PASSWORD}",
  "database.dbname": "${SOURCE_DB_NAME}",
  "database.server.name": "${CONNECTOR_NAME}",
  "plugin.name": "pgoutput",
  "slot.name": "debezium_${CONNECTOR_NAME}",
  "snapshot.mode": "INITIAL",
  "topic.prefix": "cdc",
  "topic.creation.default.replication.factor": 3,
  "topic.creation.default.partitions": 6,
  "topic.creation.default.cleanup.policy": "delete,compact",
  "transforms": "route,unwrap,cloudEvents",
  "transforms.route.type": "org.apache.kafka.connect.transforms.RegexRouter",
  "transforms.route.regex": "([^.]+)\\.([^.]+)\\.([^.]+)",
  "transforms.route.replacement": "com.company.cdc.$2.$3",
  "transforms.unwrap.type": "io.debezium.transforms.ExtractNewRecordState",
  "transforms.unwrap.drop.tombstones": "false",
  "transforms.unwrap.delete.handling.mode": "rewrite",
  "transforms.cloudEvents.type": "io.debezium.transforms.outbox.EventRouter",
  "key.converter": "org.apache.kafka.connect.storage.StringConverter",
  "value.converter": "io.confluent.connect.protobuf.ProtobufConverter",
  "value.converter.schema.registry.url": "http://schema-registry:8080"
}
```

This configuration template is customized per connector by the `StartReplicationPort` based on the source database and table specifications provided in the request.
