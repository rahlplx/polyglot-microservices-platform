# Schema Registry Service - Ports Definition

> Language: Go | Role: Buf integration, breaking change detection, schema management

## Inbound Ports (Driving / Use Case Interfaces)

### RegisterSchemaPort

- **Port Name:** `RegisterSchemaPort`
- **Input Type:** `RegisterSchemaRequest` (subject: string, schema_type: enum [PROTOBUF, AVRO, JSON_SCHEMA], schema_definition: string, references: list<SchemaReference>, compatibility_level: optional<enum [NONE, BACKWARD, FORWARD, FULL, BACKWARD_TRANSITIVE, FORWARD_TRANSITIVE, FULL_TRANSITIVE]>, description: optional<string>)
- **Output Type:** `RegisterSchemaResponse` (schema_id: int32, version: int32, fingerprint: string, registered_at: timestamp, compatibility_check: CompatibilityResult)
- **Error Types:** `SchemaIncompatibleError`, `InvalidSchemaError`, `SubjectNotFoundError`, `DuplicateSchemaError`
- **Description:** Registers a new schema version under a given subject in the Schema Registry. The port first validates the schema definition for syntactic correctness using the appropriate parser (Protobuf, Avro, or JSON Schema), then checks compatibility against the latest registered version for the subject using the configured compatibility level. If the schema is incompatible (e.g., a breaking change such as removing a required field or changing a field type), the port returns a `SchemaIncompatibleError` with detailed information about which compatibility rules were violated and suggestions for resolving the incompatibility. If the schema passes all validation and compatibility checks, it is assigned a unique schema ID and version number, and the fingerprint of the schema definition is computed for deduplication. The `references` field supports schema composition: a Protobuf message can reference other proto files, and the registry resolves these references transitively. Upon successful registration, the port publishes a `com.company.schema-registry.schema-registered` event, which notifies the CDC Relay and other services that a new schema version is available.

### GetSchemaPort

- **Port Name:** `GetSchemaPort`
- **Input Type:** `GetSchemaRequest` (subject: string, version: optional<int32>, schema_id: optional<int32>, include_references: bool, include_deprecated: bool)
- **Output Type:** `GetSchemaResponse` (schema_id: int32, version: int32, subject: string, schema_type: SchemaType, schema_definition: string, references: list<SchemaReference>, fingerprint: string, registered_at: timestamp, deprecated: bool, description: optional<string>)
- **Error Types:** `SchemaNotFoundError`, `VersionNotFoundError`, `SubjectNotFoundError`
- **Description:** Retrieves a schema by subject and version, or by schema ID. When version is not specified, the port returns the latest version for the subject. When `include_references` is true, the port recursively resolves all schema references and includes their definitions in the response, providing a complete schema package that can be used for serialization without additional lookups. When `include_deprecated` is true, deprecated schema versions are included in the search results; by default, only active schemas are returned. The port maintains a two-level cache: an in-memory LRU cache for the 1000 most recently accessed schemas, and a Redis cache for all schemas. Cache hits return in sub-millisecond time, while cache misses query PostgreSQL and populate both cache layers. The cache is invalidated when a new schema version is registered for the same subject, ensuring that callers always see the latest schema after registration.

### ValidateSchemaPort

- **Port Name:** `ValidateSchemaPort`
- **Input Type:** `ValidateSchemaRequest` (subject: string, schema_definition: string, schema_type: SchemaType, validation_level: enum [SYNTAX, SEMANTIC, COMPATIBILITY, FULL], target_version: optional<int32>)
- **Output Type:** `ValidateSchemaResponse` (valid: bool, errors: list<ValidationError>, warnings: list<ValidationWarning>, compatibility_result: optional<CompatibilityResult>)
- **Description:** Validates a schema definition without registering it. The port supports multiple validation levels that can be progressively applied: SYNTAX checks that the schema is well-formed and parseable; SEMANTIC checks for naming conventions, field naming patterns, and other style guidelines; COMPATIBILITY checks the schema against the latest registered version for the subject; and FULL performs all validation levels including Buf lint rules and breaking change detection. The COMPATIBILITY and FULL levels require a `target_version` to compare against (defaulting to the latest registered version). The response includes a list of errors (which must be fixed before the schema can be registered) and warnings (which should be reviewed but do not block registration). This port is used by CI/CD pipelines to validate schema changes before they are merged, by IDE plugins for real-time validation during development, and by the Buf CLI integration for pre-commit hook validation.

### CheckBreakingPort

- **Port Name:** `CheckBreakingPort`
- **Input Type:** `CheckBreakingRequest` (subject: string, previous_version: optional<int32>, proposed_schema: string, check_level: enum [MINIMAL, DEFAULT, STRICT], rules: optional<list<BreakingChangeRule>>)
- **Output Type:** `CheckBreakingResponse` (has_breaking_changes: bool, changes: list<BreakingChange>, severity: enum [INFO, WARNING, ERROR], mitigations: list<MitigationSuggestion>)
- **Error Types:** `SubjectNotFoundError`, `InvalidSchemaError`
- **Description:** Checks whether a proposed schema change introduces breaking changes relative to a previously registered version. The port integrates with Buf's breaking change detection engine, which provides a comprehensive set of rules for Protobuf schemas: field removal (breaking for existing consumers), field type change (breaking for both producers and consumers), field number change (breaking for wire compatibility), message removal (breaking for consumers), enum value removal (breaking for consumers), and many more. The check level controls the strictness of the analysis: MINIMAL checks only wire compatibility (changes that break binary deserialization), DEFAULT adds source compatibility checks (changes that break code generation), and STRICT adds all Buf lint rules including documentation and naming requirements. The response includes a detailed list of detected breaking changes, each with the affected field or message, the type of breakage, and a severity level. The `mitigations` field provides actionable suggestions for resolving each breaking change without requiring a version bump, such as adding a new field instead of modifying an existing one, or using a wrapper message for type changes.

## Outbound Ports (Driven / Infrastructure Interfaces)

### ListSchemasPort

- **Port Name:** `ListSchemasPort`
- **Input Type:** `ListSchemasRequest` (prefix: optional<string>, schema_type: optional<enum [PROTOBUF, AVRO, JSON_SCHEMA]>, include_deprecated: bool, page_size: int32, page_token: string)
- **Output Type:** `ListSchemasResponse` (subjects: list<SubjectSummary>, total_count: int64, next_page_token: string)
- **Error Types:** `InvalidQueryError`, `PageTokenExpiredError`
- **Description:** Lists all registered schema subjects with optional filtering and pagination support. The port supports filtering by subject prefix (returning only subjects whose names start with the specified prefix, such as "com.company.order." to list all Order service schemas), by schema type (returning only Protobuf, Avro, or JSON Schema subjects), and by deprecation status (by default, deprecated schemas are excluded from listing to reduce noise, but they can be included by setting `include_deprecated` to true). The response includes a summary for each subject containing the subject name, the latest version number, the schema type, the total number of versions, whether the latest version is deprecated, and the registration timestamp of the latest version. The port uses cursor-based pagination with opaque page tokens for consistent results across pages. This port is used by the Schema Registry's web UI for browsing registered schemas, by CI/CD pipelines for validating that all required schemas exist before deployment, and by the CDC Relay service for discovering schemas that map to its connector configurations.

### SchemaStorePort

- **Port Name:** `SchemaStorePort`
- **Operations:**
  - `Save(schema: SchemaRecord) -> SchemaRecord`: Persists a schema record with version and metadata.
  - `FindBySubject(subject: string) -> list<SchemaRecord>`: Retrieves all versions of a schema by subject.
  - `FindBySubjectAndVersion(subject: string, version: int32) -> optional<SchemaRecord>`: Retrieves a specific schema version.
  - `FindById(schema_id: int32) -> optional<SchemaRecord>`: Retrieves a schema by its unique ID.
  - `FindByFingerprint(fingerprint: string) -> optional<SchemaRecord>`: Looks up a schema by its content fingerprint.
  - `DeleteSubject(subject: string, permanent: bool) -> void`: Soft-deletes or permanently deletes all versions of a subject.
  - `ListSubjects(prefix: optional<string>) -> list<string>`: Lists all registered subjects, optionally filtered by prefix.
- **Technology:** PostgreSQL with custom SQL (pgx driver)
- **ACL Required:** No (internal data store)
- **Description:** The schema store port manages all persistent storage for schema records in the Schema Registry. Each schema record includes the subject, version, schema type, definition, fingerprint, references, compatibility level, and metadata (registration timestamp, registrar identity, description). The store uses PostgreSQL's unique constraints on (subject, version) pairs to prevent duplicate versions, and a partial unique index on (subject, fingerprint) for active (non-deleted) schemas to prevent duplicate registrations of the same schema content. The fingerprint is computed using SHA-256 over the canonical schema definition, enabling instant deduplication checks without parsing the schema. The store supports soft deletion of subjects (marking all versions as deleted without removing the data), which can be reversed by an administrator, and permanent deletion (physically removing the data), which is irreversible and only used for compliance-driven data removal.

### BufCLIPort

- **Port Name:** `BufCLIPort`
- **Operations:**
  - `Lint(request: BufLintRequest) -> BufLintResponse`: Runs Buf lint checks on a schema definition.
  - `CheckBreaking(request: BufBreakingRequest) -> BufBreakingResponse`: Runs Buf breaking change detection between two schema versions.
  - `Build(request: BufBuildRequest) -> BufBuildResponse`: Compiles a schema definition and returns any compilation errors.
  - `Generate(request: BufGenerateRequest) -> BufGenerateResponse`: Runs code generation plugins on a schema definition.
- **Technology:** Buf CLI (executed as a subprocess with gRPC plugin support)
- **ACL Required:** No (internal tool, open-source)
- **Description:** The Buf CLI port provides integration with the Buf command-line tool for Protobuf schema linting, breaking change detection, compilation, and code generation. The port executes the Buf CLI as a subprocess, passing the schema definition via stdin or a temporary file, and parsing the structured output. The port includes a Buf CLI binary manager that downloads and caches the appropriate Buf version, ensuring that all services in the organization use the same Buf version for consistent validation results. The `Lint` operation runs Buf's built-in lint rules, which enforce best practices such as using snake_case for field names, requiring comments on messages and fields, and prohibiting reserved field number reuse. The `CheckBreaking` operation runs Buf's breaking change detector, which is more comprehensive than the Schema Registry's own compatibility checks and includes wire, source, and file-level compatibility analysis. The `Build` operation compiles the schema to verify that all type references resolve correctly and that the schema is valid Protobuf. The `Generate` operation is used by CI/CD pipelines to generate client stubs from schema definitions.

### ProtoCompilerPort

- **Port Name:** `ProtoCompilerPort`
- **Operations:**
  - `Compile(schema: ProtoFile, includes: list<ProtoFile>) -> CompilationResult`: Compiles a Protobuf schema file with its dependencies.
  - `ResolveReferences(schema: ProtoFile) -> list<ProtoFile>`: Resolves all import references transitively.
  - `ExtractDescriptors(schema: ProtoFile) -> FileDescriptorSet`: Extracts the FileDescriptorSet for a schema and its dependencies.
- **Technology:** protoc compiler (executed as a subprocess)
- **ACL Required:** No (internal tool, open-source)
- **Description:** The proto compiler port provides direct integration with the `protoc` compiler for Protobuf schema compilation and descriptor extraction. While the Buf CLI handles most schema validation tasks, the proto compiler port is used for scenarios that require direct protoc integration, such as extracting FileDescriptorSets for dynamic message serialization, compiling schemas for languages not supported by Buf's code generation, and generating descriptor metadata for the Schema Registry's schema browser UI. The port manages the protoc binary lifecycle, including version pinning and include path configuration for standard Google Protobuf well-known types. The port also resolves transitive import references, ensuring that all dependencies of a schema are available for compilation, even when they are defined in other packages or modules.
