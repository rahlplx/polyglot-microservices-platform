# Identity Service - Contracts Definition

> Language: Rust | Role: SPIFFE/SPIRE integration, mTLS certificate rotation

## gRPC Contract

### Proto Package

- **Package Name:** `identity.v1`
- **File:** `identity/v1/identity.proto`

### Service Definition

**Service Name:** `IdentityService`

| RPC Method | Request Type | Response Type | Streaming |
|---|---|---|---|
| `Issue` | `IssueSVIDRequest` | `IssueSVIDResponse` | Unary |
| `Verify` | `VerifyWorkloadRequest` | `VerifyWorkloadResponse` | Unary |
| `Rotate` | `RotateCertificateRequest` | `RotateCertificateResponse` | Unary |
| `GetTrustBundle` | `GetTrustBundleRequest` | `GetTrustBundleResponse` | Unary |
| `Revoke` | `RevokeSVIDRequest` | `RevokeSVIDResponse` | Unary |

### RPC Details

**Issue:**
Issues a new X.509 SVID for a workload. The request specifies the workload ID, desired SPIFFE ID, TTL, DNS names, and audience. The service validates the workload against the registry, generates a key pair, creates a CSR, signs it with the in-memory CA, and returns the SVID along with the current trust bundle. The private key is included in the response (encrypted with a workload-specific key) and is never persisted in plaintext.

**Verify:**
Verifies a presented X.509 SVID chain against the trust bundle. The request includes the raw certificate chain bytes and the expected SPIFFE ID. The service performs full chain validation, SPIFFE ID matching, expiry checking, and revocation status verification. The response includes the verified SPIFFE ID and workload attributes.

**Rotate:**
Rotates an existing SVID by revoking the old certificate and issuing a new one atomically. The request specifies the current serial number, workload ID, and rotation reason. The service ensures that the old certificate is added to the CRL before the new SVID is returned, preventing a window where both certificates are valid.

**GetTrustBundle:**
Returns the current X.509 trust bundle for the specified trust domain. The bundle includes all active root CA certificates and intermediate chains. Clients can use the sequence number for conditional fetching, only downloading the bundle when it has changed.

**Revoke:**
Revokes a previously issued X.509 SVID by adding it to the Certificate Revocation List and incrementing the trust bundle sequence number. The request specifies the serial number of the certificate to revoke, the revocation reason, and the identity of the revoker. The service performs the revocation atomically: the certificate is marked as revoked, the CRL is updated, and the trust bundle sequence number is incremented, all within a single database transaction. The response confirms the revocation and lists any workloads that were using the revoked SVID so they can be notified to obtain a replacement certificate. Emergency revocations for key compromise are processed immediately without approval workflows.

### Key Message Types

```protobuf
message IssueSVIDRequest {
  string workload_id = 1;
  string spiffe_id = 2;
  int32 ttl_seconds = 3;
  repeated string dns_names = 4;
  repeated string audience = 5;
}

message IssueSVIDResponse {
  X509SVID svid = 1;
  X509Bundle bundle = 2;
  google.protobuf.Timestamp expires_at = 3;
  string serial_number = 4;
}

message VerifyWorkloadRequest {
  repeated bytes svid_chain = 1;
  string expected_spiffe_id = 2;
  optional string expected_dns = 3;
}

message VerifyWorkloadResponse {
  bool valid = 1;
  string spiffe_id = 2;
  map<string, string> workload_attributes = 3;
  google.protobuf.Timestamp expires_at = 4;
  string trust_domain = 5;
}

message RotateCertificateRequest {
  string current_serial = 1;
  string workload_id = 2;
  enum RotationReason {
    EXPIRY = 0;
    KEY_COMPROMISE = 1;
    CA_ROTATION = 2;
    PROACTIVE = 3;
  }
  RotationReason reason = 3;
}

message RotateCertificateResponse {
  X509SVID new_svid = 1;
  X509Bundle new_bundle = 2;
  bool old_serial_revoked = 3;
  string rotation_id = 4;
}

message GetTrustBundleRequest {
  optional string trust_domain = 1;
  bool include_revoked = 2;
}

message GetTrustBundleResponse {
  X509Bundle bundle = 1;
  repeated X509CA root_cas = 2;
  int64 sequence_number = 3;
  google.protobuf.Timestamp expires_at = 4;
}

message RevokeSVIDRequest {
  string serial_number = 1;
  enum RevocationReason {
    KEY_COMPROMISE = 0;
    CA_COMPROMISE = 1;
    AFFILIATION_CHANGED = 2;
    SUPERSEDED = 3;
    CESSATION_OF_OPERATION = 4;
    CERTIFICATE_HOLD = 5;
    REMOVE_FROM_CRL = 6;
    PRIVILEGE_WITHDRAWN = 7;
    UNSPECIFIED = 8;
  }
  RevocationReason reason = 2;
  optional string revocation_comment = 3;
  string revoked_by = 4;
}

message RevokeSVIDResponse {
  string serial_number = 1;
  bool revoked = 2;
  bool crl_updated = 3;
  repeated string affected_workloads = 4;
  google.protobuf.Timestamp revoked_at = 5;
}

message X509SVID {
  bytes cert_chain = 1;      // DER-encoded certificate chain
  bytes private_key = 2;     // Encrypted private key (PKCS8)
  string spiffe_id = 3;
}

message X509Bundle {
  repeated bytes ca_certs = 1;  // DER-encoded CA certificates
  string trust_domain = 2;
  int64 sequence_number = 3;
}

message X509CA {
  bytes cert = 1;
  google.protobuf.Timestamp not_before = 2;
  google.protobuf.Timestamp not_after = 3;
}
```

## OpenAPI Contract

The Identity service does not expose a REST API. All operations are available exclusively through the gRPC interface defined above. The SPIFFE Workload API is also served on a Unix domain socket at `/run/spire/sockets/agent.sock` following the SPIFFE specification, which is a gRPC endpoint rather than REST.

Administrative operations for workload registration are handled through Kubernetes Custom Resource Definitions (CRDs) rather than a REST API:

| CRD | Purpose |
|---|---|
| `SPIFFEID` | Defines a SPIFFE ID and its associated workload selector |
| `TrustBundle` | Configures trust domain relationships and bundle refresh |
| `Federation` | Manages cross-trust-domain federation rules |

These CRDs are watched by the Identity service's Kubernetes controller and reconciled into the workload registry and trust store.

## Event Contracts

### CloudEvents Type Prefix

`com.company.identity.`

### Event Types

| Event Type | Payload Schema | Consumer Services |
|---|---|---|
| `com.company.identity.svid-issued` | `SVIDIssuedEvent` | Analytics, CDC Relay |
| `com.company.identity.svid-revoked` | `SVIDRevokedEvent` | Analytics, Gateway, CDC Relay |
| `com.company.identity.bundle-updated` | `BundleUpdatedEvent` | Gateway, Analytics |

### Event Details

**SVIDIssuedEvent:**
Emitted after a new SVID has been successfully issued and persisted. The payload includes the workload ID, SPIFFE ID, serial number, expiry timestamp, and the trust domain. This event is consumed by the Analytics service for certificate lifecycle monitoring and by the CDC Relay for replication to downstream analytics stores. The event is produced transactionally with the database write, ensuring at-least-once delivery.

**SVIDRevokedEvent:**
Emitted after a certificate has been revoked. The payload includes the serial number, workload ID, revocation reason, and revocation timestamp. The Gateway service consumes this event to update its local CRL cache, ensuring that revoked certificates are immediately rejected at the edge. The Analytics service uses this event for security auditing and anomaly detection. The CDC Relay replicates revocation events to ensure that all data stores have a consistent view of the revocation state.

**BundleUpdatedEvent:**
Emitted when the trust bundle is updated due to CA rotation or federation changes. The payload includes the new sequence number and the trust domain. The Gateway service consumes this event to refresh its cached trust bundle, ensuring that mTLS verification uses the latest root CA certificates. This event is critical for zero-downtime CA rotation, as it signals to all verifiers that they must fetch the updated bundle before the old CA certificates expire.
