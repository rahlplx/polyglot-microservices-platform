# Identity Service - Adapters Definition

> Language: Rust | Role: SPIFFE/SPIRE integration, mTLS certificate rotation

## Inbound Adapters

### gRPC Handler

- **Maps to:** `identity.v1.IdentityService`
- **RPC Methods:** `Issue`, `Verify`, `Rotate`, `GetTrustBundle`, `Revoke`
- **Description:** The gRPC handler adapter exposes the Identity service's five core RPCs. Each RPC maps directly to one of the inbound ports: `Issue` maps to `IssueSVIDPort`, `Verify` maps to `VerifyWorkloadPort`, `Rotate` maps to `RotateCertificatePort`, `GetTrustBundle` maps to `GetTrustBundlePort`, and `Revoke` maps to `RevokeSVIDPort`. The handler is implemented using the `tonic` crate for async gRPC in Rust, with interceptors for authentication (verifying the caller's own SVID), rate limiting, and OpenTelemetry tracing. The gRPC server enforces mTLS on its listener, requiring all callers to present a valid SVID. The SPIFFE Workload API endpoint is also served on a separate Unix domain socket, following the SPIFFE specification for workload API endpoints, which allows sidecar-less workload attestation. The handler performs input validation using prost-derived types and returns structured gRPC status codes for all error conditions.

### REST Controller

- **Maps to:** None (the Identity service does not expose a REST API)
- **Description:** The Identity service is exclusively a gRPC service and does not provide REST endpoints. All identity operations are performance-sensitive and benefit from the binary efficiency of gRPC/protobuf. The SPIFFE Workload API specification mandates a gRPC endpoint, and adding a REST translation layer would introduce unnecessary complexity and latency. Administrative operations such as workload registration and policy management are handled through the Kubernetes Mutating Webhook and Custom Resource Definitions rather than through a REST API, which aligns with the GitOps infrastructure management philosophy.

### Event Consumer

- **Maps to:** `com.company.workload.registered`, `com.company.workload.deregistered`
- **Description:** The Identity service consumes workload lifecycle events from Kubernetes via a Kafka topic populated by a Kubernetes event reflector. When a new workload is registered (pod creation event), the consumer calls the `WorkloadRegistryPort.RegisterWorkload` operation. When a workload is deregistered (pod deletion event), the consumer calls `WorkloadRegistryPort.DeleteWorkload` and triggers revocation of any outstanding SVIDs. The consumer is implemented using the `rdkafka` crate with a committed consumer group to ensure exactly-once processing. Dead letter events are forwarded to a dedicated `identity.events.dlq` topic for manual investigation. The consumer includes a backpressure mechanism that pauses consumption when the SVID issuance queue exceeds a configurable depth, preventing memory exhaustion during burst registrations.

## Outbound Adapters

### Persistence Adapter

- **Database:** PostgreSQL 16 with pgcrypto extension
- **ORM/Query Approach:** Custom SQLx queries with compile-time checked SQL (Rust sqlx crate)
- **Description:** The persistence adapter manages all database interactions for the Identity service. It uses the `sqlx` crate with compile-time SQL verification, ensuring that all queries are syntactically and semantically correct at build time. The adapter implements two separate schema namespaces within the same PostgreSQL cluster: `identity_certs` for certificate and revocation data, and `identity_workloads` for workload registration data. This separation allows independent schema evolution and different backup/retention policies. The certificate schema includes a custom index on the X.509 serial number for fast revocation lookups and a partial index on non-revoked certificates for active SVID queries. The workload schema includes a GIN index on the Kubernetes selector JSONB column for efficient selector matching. All write operations use serializable isolation level to prevent concurrent issuance of duplicate SPIFFE IDs.

### Messaging Adapter

- **Kafka Topics:**
  - **Produced:** `com.company.identity.svid-issued` (emitted after successful SVID issuance), `com.company.identity.svid-revoked` (emitted after revocation), `com.company.identity.bundle-updated` (emitted when the trust bundle changes)
  - **Consumed:** `com.company.workload.registered`, `com.company.workload.deregistered`
- **Serialization:** Protobuf (using the same message types defined in the gRPC contract for consistency)
- **Description:** The messaging adapter handles all Kafka interactions for the Identity service. Produced events are published using the transactional producer API to ensure exactly-once semantics, pairing the Kafka produce with the PostgreSQL commit in a two-phase transaction pattern. This guarantees that an SVID is never issued without the corresponding event being published, and vice versa. Consumed events are processed with manual offset commits after successful database writes. The adapter uses the `rdkafka` crate configured with idempotent production, compression (zstd), and a batch size optimized for the expected throughput of certificate lifecycle events.

### External Service Adapter

- **External Dependencies:** None (the Identity service does not call external services)
- **Behind ACL:** Not applicable
- **Description:** The Identity service is entirely self-contained and does not communicate with any external or third-party services. It generates its own CA key material in memory, issues certificates using its own signing infrastructure, and stores all data in the internal PostgreSQL cluster. This isolation is a deliberate security design decision: the Identity service is the root of trust for the entire service mesh, and any external dependency would expand the attack surface. The only inbound integration point is the Kubernetes API server (for the Mutating Webhook and CRD watching), which is handled via the workload lifecycle event consumer rather than direct API calls.

### Observability Adapter

- **OTel Instrumentation Points:**
  - **SVID Issuance Tracing:** Each `Issue` RPC creates a span capturing the workload ID, SPIFFE ID, requested TTL, and issuance latency. The span links to the certificate store write operation for end-to-end traceability.
  - **Verification Tracing:** Each `Verify` RPC creates a span capturing the presented SPIFFE ID, verification result, and chain depth. Failed verifications include the specific failure reason as a span event.
  - **Rotation Tracing:** Each `Rotate` RPC creates a span capturing the rotation trigger, old and new serial numbers, and the time taken for atomic revocation-and-issuance.
  - **Certificate Metrics:** Counter metrics for issued SVIDs (`identity.svid.issued_total` with labels: trust_domain, ttl_bucket), counter metrics for revocations (`identity.svid.revoked_total` with labels: reason), gauge metrics for active SVIDs (`identity.svid.active` with labels: trust_domain), and histogram metrics for issuance latency (`identity.svid.issuance_duration`).
  - **Workload Registry Metrics:** Gauge metrics for registered workloads (`identity.workload.registered` with labels: namespace), counter metrics for registration events (`identity.workload.events_total` with labels: event_type).
- **Description:** The observability adapter uses the `opentelemetry` Rust crate to export traces and metrics via OTLP. All sensitive fields (private keys, certificate chains) are excluded from trace attributes to prevent data leakage in observability backends. The adapter implements a custom sampling strategy that always samples revocation and rotation operations but applies a 10% sampling rate to routine verification operations to control trace volume. Structured logs are emitted using the `tracing` crate with a JSON formatter, and all log entries include the trace context for correlation.
