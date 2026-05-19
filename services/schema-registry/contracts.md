# Schema Registry Service - Contracts Definition

> Language: Go | Role: Buf integration, breaking change detection, schema management

## gRPC Contract

### Proto Package

- **Package Name:** `schemaregistry.v1`
- **File:** `schemaregistry/v1/schemaregistry.proto`

### Service Definition

**Service Name:** `SchemaRegistryService`

| RPC Method | Request Type | Response Type | Streaming |
|---|---|---|---|
| `Register` | `RegisterSchemaRequest` | `RegisterSchemaResponse` | Unary |
| `Get` | `GetSchemaRequest` | `GetSchemaResponse` | Unary |
| `Validate` | `ValidateSchemaRequest` | `ValidateSchemaResponse` | Unary |
| `CheckBreaking` | `CheckBreakingRequest` | `CheckBreakingResponse` | Unary |
| `List` | `ListSchemasRequest` | `ListSchemasResponse` | Unary |

### RPC Details

**Register:**
Registers a new schema version under a given subject. The port validates the schema for syntax and compatibility before registration. If the schema is incompatible with the latest version, the RPC returns an INVALID_ARGUMENT status with detailed compatibility violation information. The response includes the assigned schema ID, version number, content fingerprint, and the result of the compatibility check.

**Get:**
Retrieves a schema by subject and version, or by schema ID. When version is not specified, the latest version is returned. The response includes the full schema definition, type, references, fingerprint, and metadata. Optionally includes all transitive references when `include_references` is true.

**Validate:**
Validates a schema definition without registering it. Supports multiple validation levels from basic syntax checking to full Buf lint and breaking change analysis. The response includes all errors and warnings found during validation, without persisting the schema.

**CheckBreaking:**
Performs a detailed breaking change analysis between a proposed schema and a reference version. Uses Buf's breaking change detection engine for comprehensive analysis including wire, source, and file-level compatibility. The response lists all detected breaking changes with severity levels and mitigation suggestions.

**List:**
Lists all registered schema subjects with optional filtering by subject prefix, schema type, and deprecation status. The request supports cursor-based pagination. The response includes a summary for each subject containing the subject name, latest version number, schema type, total number of versions, deprecation status, and registration timestamp. This RPC is used by the Schema Registry's web UI and by CI/CD pipelines for schema discovery.

### Key Message Types

```protobuf
message RegisterSchemaRequest {
  string subject = 1;
  enum SchemaType {
    PROTOBUF = 0;
    AVRO = 1;
    JSON_SCHEMA = 2;
  }
  SchemaType schema_type = 2;
  string schema_definition = 3;
  repeated SchemaReference references = 4;
  optional CompatibilityLevel compatibility_level = 5;
  optional string description = 6;
}

message RegisterSchemaResponse {
  int32 schema_id = 1;
  int32 version = 2;
  string fingerprint = 3;
  google.protobuf.Timestamp registered_at = 4;
  CompatibilityResult compatibility_check = 5;
}

message GetSchemaRequest {
  string subject = 1;
  optional int32 version = 2;
  optional int32 schema_id = 3;
  bool include_references = 4;
  bool include_deprecated = 5;
}

message GetSchemaResponse {
  int32 schema_id = 1;
  int32 version = 2;
  string subject = 3;
  SchemaType schema_type = 4;
  string schema_definition = 5;
  repeated SchemaReference references = 6;
  string fingerprint = 7;
  google.protobuf.Timestamp registered_at = 8;
  bool deprecated = 9;
  optional string description = 10;
}

message ValidateSchemaRequest {
  string subject = 1;
  string schema_definition = 2;
  SchemaType schema_type = 3;
  enum ValidationLevel {
    SYNTAX = 0;
    SEMANTIC = 1;
    COMPATIBILITY = 2;
    FULL = 3;
  }
  ValidationLevel validation_level = 4;
  optional int32 target_version = 5;
}

message ValidateSchemaResponse {
  bool valid = 1;
  repeated ValidationError errors = 2;
  repeated ValidationWarning warnings = 3;
  optional CompatibilityResult compatibility_result = 4;
}

message CheckBreakingRequest {
  string subject = 1;
  optional int32 previous_version = 2;
  string proposed_schema = 3;
  enum CheckLevel {
    MINIMAL = 0;
    DEFAULT = 1;
    STRICT = 2;
  }
  CheckLevel check_level = 4;
  optional repeated BreakingChangeRule rules = 5;
}

message CheckBreakingResponse {
  bool has_breaking_changes = 1;
  repeated BreakingChange changes = 2;
  enum Severity {
    INFO = 0;
    WARNING = 1;
    ERROR = 2;
  }
  Severity severity = 3;
  repeated MitigationSuggestion mitigations = 4;
}

message SchemaReference {
  string name = 1;
  string subject = 2;
  int32 version = 3;
}

message CompatibilityResult {
  bool compatible = 1;
  repeated CompatibilityViolation violations = 2;
  string compatibility_level = 3;
}

message CompatibilityViolation {
  string description = 1;
  string field_path = 2;
  string rule = 3;
  string previous_type = 4;
  string proposed_type = 5;
}

message ValidationError {
  string message = 1;
  string location = 2;
  string rule_id = 3;
}

message ValidationWarning {
  string message = 1;
  string location = 2;
  string rule_id = 3;
}

message BreakingChange {
  string change_type = 1;
  string field_path = 2;
  string description = 3;
  string category = 4;  // WIRE, SOURCE, FILE
}

message MitigationSuggestion {
  string change_type = 1;
  string suggestion = 2;
  string example = 3;
}

message BreakingChangeRule {
  string id = 1;
  string category = 2;
  bool enabled = 3;
}

enum CompatibilityLevel {
  NONE = 0;
  BACKWARD = 1;
  FORWARD = 2;
  FULL = 3;
  BACKWARD_TRANSITIVE = 4;
  FORWARD_TRANSITIVE = 5;
  FULL_TRANSITIVE = 6;
}
```

## OpenAPI Contract

### API Path Prefix

`/api/v1/schemas`

### Endpoints

| Method | Path | Request Body | Response | Auth Required |
|---|---|---|---|---|
| `POST` | `/api/v1/schemas/subjects/{subject}/versions` | `RegisterSchemaRequest` JSON | `RegisterSchemaResponse` JSON | Yes |
| `GET` | `/api/v1/schemas/subjects/{subject}/versions/{version}` | None | `GetSchemaResponse` JSON | Optional |
| `GET` | `/api/v1/schemas/subjects/{subject}/versions/latest` | None | `GetSchemaResponse` JSON | Optional |
| `GET` | `/api/v1/schemas/ids/{id}` | None | `GetSchemaResponse` JSON | Optional |
| `POST` | `/api/v1/schemas/subjects/{subject}/validate` | `ValidateSchemaRequest` JSON | `ValidateSchemaResponse` JSON | Yes |
| `POST` | `/api/v1/schemas/subjects/{subject}/check-breaking` | `CheckBreakingRequest` JSON | `CheckBreakingResponse` JSON | Yes |
| `GET` | `/api/v1/schemas/subjects` | None | Subject list | Optional |
| `GET` | `/api/v1/schemas/subjects/{subject}/versions` | None | Version list | Optional |
| `DELETE` | `/api/v1/schemas/subjects/{subject}` | None | 204 No Content | Yes (admin) |

### Endpoint Details

**POST /subjects/{subject}/versions:**
Registers a new schema version. Compatible with the Confluent Schema Registry API. The request body includes the schema type and definition. Returns 200 with the schema ID and version on success. Returns 409 for incompatible schemas. Returns 422 for invalid schema syntax.

**GET /subjects/{subject}/versions/{version}:**
Retrieves a specific schema version. Supports `?include=references,deprecated` query parameter for expansion. Returns 404 if the subject or version does not exist.

**GET /subjects/{subject}/versions/latest:**
Retrieves the latest (highest version number) schema for a subject. Equivalent to `/versions/-1` in the Confluent API. Returns 404 if the subject does not exist.

**GET /ids/{id}:**
Retrieves a schema by its global unique ID. This is useful for deserialization, where the schema ID is embedded in the message payload. Returns 404 if the ID does not exist.

**POST /subjects/{subject}/validate:**
Validates a schema without registering it. The request body specifies the validation level. Returns all errors and warnings without modifying the registry.

**POST /subjects/{subject}/check-breaking:**
Checks for breaking changes between a proposed schema and the latest registered version. The request body specifies the check level. Returns a detailed list of breaking changes with mitigations.

### Authentication Requirements

- Read operations (GET) are available without authentication for internal service mesh access
- Write operations (POST, DELETE) require a valid JWT with the `schema:write` scope or mTLS with SPIFFE SVID
- The DELETE operation additionally requires the `schema:admin` scope
- CI/CD pipelines use service account tokens with the `schema:write` scope
- Rate limiting is applied per client ID with higher limits for CI/CD pipelines

## Event Contracts

### CloudEvents Type Prefix

`com.company.schema-registry.`

### Event Types

| Event Type | Payload Schema | Consumer Services |
|---|---|---|
| `com.company.schema-registry.schema-registered` | `SchemaRegisteredEvent` | CDC Relay, Analytics |
| `com.company.schema-registry.schema-deprecated` | `SchemaDeprecatedEvent` | Analytics, Notification |
| `com.company.schema-registry.compatibility-violation` | `CompatibilityViolationEvent` | Notification, Analytics |

### Event Details

**SchemaRegisteredEvent:**
Emitted when a new schema version is successfully registered. The payload includes the subject, version, schema ID, fingerprint, schema type, and the result of the compatibility check. The CDC Relay consumes this event to update connector configurations with the new schema version for message serialization. The Analytics service tracks schema registration rates and version distribution for governance reporting.

**SchemaDeprecatedEvent:**
Emitted when a schema version is marked as deprecated (either manually by an administrator or automatically when a newer version is registered with a higher compatibility level). The payload includes the subject, version, deprecation reason, and the recommended replacement version. The Analytics service tracks deprecation rates for schema lifecycle management. The Notification service sends alerts to teams that are still using deprecated schema versions, encouraging them to migrate to the latest version before the deprecated version is removed.

**CompatibilityViolationEvent:**
Emitted when an automated compatibility check detects a potential incompatibility, typically triggered by a schema change event from the CDC Relay. The payload includes the subject, the current registered version, the detected violation details, and the source of the incompatibility (e.g., a database ALTER TABLE operation). The Notification service sends alerts to the service owners who are affected by the incompatibility. The Analytics service tracks violation rates for schema governance reporting. This event does not block the schema change; it serves as an early warning system that allows teams to proactively address incompatibilities before they cause runtime errors.
