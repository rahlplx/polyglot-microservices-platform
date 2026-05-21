# Identity Service - Ports Definition

> Language: Rust | Role: SPIFFE/SPIRE integration, mTLS certificate rotation

## Inbound Ports (Driving / Use Case Interfaces)

### IssueSVIDPort

- **Port Name:** `IssueSVIDPort`
- **Input Type:** `IssueSVIDRequest` (workload_id: string, spiffe_id: string, ttl_seconds: int32, dns_names: list<string>, audience: list<string>)
- **Output Type:** `IssueSVIDResponse` (svid: X509SVID, bundle: X509Bundle, expires_at: timestamp, serial_number: string)
- **Error Types:** `WorkloadNotFoundError`, `SigningKeyUnavailableError`, `InvalidSPIFFEIDError`, `TTLExceededPolicyError`
- **Description:** Issues a new X.509 SVID (SPIFFE Verifiable Identity Document) for a requesting workload. This is the core operation of the Identity service and is called by every service in the mesh when it needs a fresh identity certificate. The port validates the requesting workload against the workload registry to ensure that only authorized workloads can obtain SVIDs with specific SPIFFE IDs. The issued certificate includes the workload's SPIFFE ID in the URI SAN field and any requested DNS names in the DNS SAN field. The TTL is capped by a global policy maximum (default: 72 hours) to limit the blast radius of a compromised SVID. The signing operation uses an in-memory CA key that is itself rotated on a configurable schedule, ensuring that the CA key material is never persisted to disk.

### VerifyWorkloadPort

- **Port Name:** `VerifyWorkloadPort`
- **Input Type:** `VerifyWorkloadRequest` (svid_chain: list<bytes>, expected_spiffe_id: string, expected_dns: optional<string>)
- **Output Type:** `VerifyWorkloadResponse` (valid: bool, spiffe_id: string, workload_attributes: map<string,string>, expires_at: timestamp, trust_domain: string)
- **Error Types:** `CertificateExpiredError`, `CertificateRevokedError`, `UntrustedChainError`, `SPIFFEIDMismatchError`
- **Description:** Verifies the identity of a workload by validating its X.509 SVID chain against the current trust bundle. This port is called by the Gateway service for every inbound mTLS connection and by services performing peer-to-peer mTLS verification. The verification process includes chain validation (ensuring the SVID chains to a trusted root), SPIFFE ID matching (confirming the presented SPIFFE ID matches the expected value), expiry checking, and revocation status checking via OCSP or CRL. If the SVID is valid, the response includes the workload's attributes from the workload registry, which can be used for authorization decisions. The port maintains an in-memory cache of recently verified SVIDs to reduce the computational cost of repeated chain validation.

### RotateCertificatePort

- **Port Name:** `RotateCertificatePort`
- **Input Type:** `RotateCertificateRequest` (current_serial: string, workload_id: string, reason: enum [EXPIRY, KEY_COMPROMISE, CA_ROTATION, PROACTIVE])
- **Output Type:** `RotateCertificateResponse` (new_svid: X509SVID, new_bundle: X509Bundle, old_serial_revoked: bool, rotation_id: string)
- **Error Types:** `CertificateNotFoundError`, `RotationNotRequiredError`, `CARotationInProgressError`, `ConcurrentRotationError`
- **Description:** Handles certificate rotation for workloads that need to replace their current SVID before it expires. This port supports multiple rotation triggers: proactive rotation (the workload initiates rotation well before expiry), expiry-driven rotation (automatically triggered when the SVID reaches a configurable rotation threshold, typically 50% of TTL), CA rotation (triggered when the CA key is rotated and existing SVIDs must be re-issued under the new CA), and key compromise rotation (emergency rotation when a private key is suspected to be compromised). The port ensures that the old certificate is atomically added to the revocation list before the new certificate is issued, preventing a window where both certificates are valid and the old one could be abused. Rotation events are logged for audit purposes and published as domain events.

### GetTrustBundlePort

- **Port Name:** `GetTrustBundlePort`
- **Input Type:** `GetTrustBundleRequest` (trust_domain: optional<string>, include_revoked: bool)
- **Output Type:** `GetTrustBundleResponse` (bundle: X509Bundle, root_cas: list<X509CA>, sequence_number: int64, expires_at: timestamp)
- **Error Types:** `TrustDomainNotFoundError`, `BundleNotReadyError`
- **Description:** Retrieves the current X.509 trust bundle for a given trust domain. This port is called by the Gateway service to bootstrap mTLS verification and by services that need to verify peer certificates locally without calling the Identity service on every request. The trust bundle includes all active root CA certificates and their intermediate chains. The response includes a sequence number that clients can use for conditional requests, fetching only updated bundles when the sequence number changes. This reduces the load on the Identity service while ensuring that all services have up-to-date trust material. The `include_revoked` flag is an administrative feature that returns the full CRL along with the bundle for debugging purposes.

### RevokeSVIDPort

- **Port Name:** `RevokeSVIDPort`
- **Input Type:** `RevokeSVIDRequest` (serial_number: string, reason: enum [KEY_COMPROMISE, CA_COMPROMISE, AFFILIATION_CHANGED, SUPERSEDED, CESSATION_OF_OPERATION, CERTIFICATE_HOLD, REMOVE_FROM_CRL, PRIVILEGE_WITHDRAWN, UNSPECIFIED], revocation_comment: optional<string>, revoked_by: string)
- **Output Type:** `RevokeSVIDResponse` (serial_number: string, revoked: bool, crl_updated: bool, affected_workloads: list<string>, revoked_at: timestamp)
- **Error Types:** `CertificateNotFoundError`, `AlreadyRevokedError`, `CARotationInProgressError`
- **Description:** Revokes a previously issued X.509 SVID, removing it from the set of trusted certificates and adding it to the Certificate Revocation List. This port is called when a workload is decommissioned, when a private key is suspected to be compromised, or when an administrator determines that a certificate should no longer be trusted. The port performs the revocation atomically: the certificate is marked as revoked in the certificate store, the CRL is updated, and the trust bundle sequence number is incremented, all within a single database transaction. The `affected_workloads` field in the response lists all workload IDs that were using the revoked SVID, enabling the caller to notify those workloads that they need to obtain a new SVID. The port also publishes an `identity.svid-revoked` domain event, which triggers the Gateway service to update its local CRL cache and ensures that the revoked certificate is immediately rejected at the edge. Emergency revocations (key compromise, CA compromise) bypass normal approval workflows and are processed immediately, while routine revocations (superseded, affiliation changed) may require approval from a security administrator depending on the configured policy.

## Outbound Ports (Driven / Infrastructure Interfaces)

### CertificateStorePort

- **Port Name:** `CertificateStorePort`
- **Operations:**
  - `StoreSVID(svid: X509SVID, private_key: bytes) -> void`: Persists an issued SVID and its encrypted private key.
  - `GetSVID(serial: string) -> optional<X509SVID>`: Retrieves a previously issued SVID by serial number.
  - `RevokeSVID(serial: string, reason: string) -> void`: Marks a SVID as revoked in the store.
  - `ListRevoked(sequence_gt: int64) -> list<RevokedSVID>`: Lists all SVIDs revoked after a given sequence number for CRL distribution.
  - `StoreBundle(bundle: X509Bundle) -> void`: Persists the current trust bundle.
  - `GetBundle(trust_domain: string) -> optional<X509Bundle>`: Retrieves the trust bundle for a domain.
- **Technology:** PostgreSQL (with pgcrypto for key encryption at rest)
- **ACL Required:** No (internal infrastructure)
- **Description:** The certificate store port manages persistent storage for all issued SVIDs, revocation records, and trust bundles. Private keys are encrypted using AES-256-GCM with a key derived from a master secret managed by the platform's secret store (Vault or Kubernetes Secrets). PostgreSQL's ACID guarantees ensure that revocation and issuance operations are atomic, preventing inconsistencies where a certificate is revoked but the new one is not yet issued. The store uses careful indexing on serial numbers and trust domains to ensure sub-millisecond lookup times even with millions of issued certificates.

### WorkloadRegistryPort

- **Port Name:** `WorkloadRegistryPort`
- **Operations:**
  - `RegisterWorkload(workload: WorkloadEntry) -> void`: Registers a new workload with its identity attributes.
  - `GetWorkload(workload_id: string) -> optional<WorkloadEntry>`: Retrieves a workload's registration by ID.
  - `GetWorkloadBySelector(selector: WorkloadSelector) -> list<WorkloadEntry>`: Finds workloads matching k8s labels, Unix UID, or SPIFFE ID patterns.
  - `UpdateWorkload(workload_id: string, entry: WorkloadEntry) -> void`: Updates a workload's registration.
  - `DeleteWorkload(workload_id: string) -> void`: Removes a workload registration and revokes its SVIDs.
- **Technology:** PostgreSQL (shared database, separate schema from certificate store)
- **ACL Required:** No (internal infrastructure)
- **Description:** The workload registry port manages the registration and lookup of workloads in the SPIFFE identity framework. Each workload entry includes its SPIFFE ID, Kubernetes pod selector (namespace, labels), Unix UID/GID constraints, and the set of TTL and DNS policies that apply. When a workload presents itself for SVID issuance, the registry is consulted to verify that the requesting entity matches the registered selector. This prevents a compromised pod from obtaining a SVID for a different service. The registry supports bulk operations for Kubernetes Mutating Webhook integrations that register entire deployments at once.
