# Security Design Document

**Project:** Comprehensive Solution Architecture -- "Best of Both Worlds" Vendor-Agnostic Enterprise Architecture
**Phase:** 2 (Design & Polyglot Architecture Mapping)
**Spec Item:** 2.8 -- Security Considerations Documented
**Author:** Security Architect
**Status:** COMPLETE

---

## 1. STRIDE Threat Model

The STRIDE threat model provides a systematic framework for identifying and categorizing security threats against the "Best of Both Worlds" architecture. Each threat category below is analyzed with specific attack scenarios targeting the polyglot microservice topology, hexagonal architecture boundaries, and the SPIFFE/SPIRE identity fabric that underpins zero-trust communication. The mitigations are designed to align with the project's core doctrines: Technology-Neutral (no proprietary security dependencies) and Efficiency First (automated verification, no manual security processes). Every threat is traced to an affected component from the Phase 2 service registry and mapped to a concrete, implementable mitigation with a defined verification method.

### STRIDE Threat Summary Table

| STRIDE Category | Threat | Affected Component | Mitigation |
|-----------------|--------|-------------------|------------|
| Spoofing | Service impersonation without identity verification | All services | SPIFFE/SPIRE workload identity with SVIDs |
| Tampering | Unauthorized modification of inter-service messages | All gRPC/REST communication | mTLS with certificate pinning, Protobuf schema validation |
| Repudiation | Denial of action by a service | Order, Payment services | OTel distributed tracing with W3C Trace Context, audit logs |
| Information Disclosure | Data leakage through misconfigured services | All services | Network policies, mTLS encryption, SPIFFE identity-based access |
| Denial of Service | Rate limit bypass or resource exhaustion | Gateway, Payment | API Gateway rate limiting, K8s resource quotas, bulkheads |
| Elevation of Privilege | Service accessing resources beyond its scope | All services | SPIFFE/SPIRE RBAC, K8s RBAC, least-privilege service accounts |

### 1.1 Spoofing -- Service Impersonation Without Identity Verification

**Threat Description:**
In a polyglot microservice architecture with nine independently deployed services, an attacker who gains access to the Kubernetes cluster network could impersonate any service by binding to its service port and accepting connections intended for the legitimate workload. Without cryptographic identity verification, the network layer provides no assurance that a gRPC or REST endpoint actually belongs to the claimed service. This is especially dangerous in the "Best of Both Worlds" architecture because services communicate across language boundaries (Go, Rust, Java, Python, Node.js), and each language runtime has different authentication defaults and configuration surface areas. A compromised pod in the `catalog` namespace could bind to the Order service port and intercept payment-related requests, or a malicious actor could deploy a rogue service that claims the Identity service's SPIFFE ID.

**Attack Vector:**
An adversary deploys a rogue pod or compromises an existing pod, then configures it to respond on the expected gRPC port of a high-value target service (e.g., Payment or Identity). The attacker does not need to exploit application-level vulnerabilities; they only need network reachability and the ability to listen on the expected port. In a Kubernetes cluster without workload identity, any pod can claim any network identity.

**Impact Assessment:** Critical

**Specific Mitigation Implementation:**
SPIFFE/SPIRE workload identity ensures every service possesses a cryptographically verifiable SVID (SPIFFE Verifiable Identity Document). When the Order service establishes a gRPC connection to the Payment service, both sides present their SVIDs during the mTLS handshake. The Payment service's SPIRE Agent validates that the caller's SVID matches the expected SPIFFE ID (`spiffe://<env>.company.com/order/order`) and that the SVID is signed by the trust bundle. If the SVID does not match or cannot be verified, the connection is rejected at the TLS layer -- before any application data is exchanged. This prevents impersonation even if an attacker has network access, because they cannot forge a valid SVID without compromising the SPIRE Server's signing key.

**Verification Method:**
Run a red-team exercise that deploys a rogue pod attempting to impersonate each service. Verify that all connection attempts are rejected at the mTLS handshake layer. Additionally, use SPIRE's entry validation API to confirm that every workload registration entry has the correct selectors (K8s namespace, service account, pod labels) and that no two entries share the same SPIFFE ID.

### 1.2 Tampering -- Unauthorized Modification of Inter-Service Messages

**Threat Description:**
Inter-service communication in this architecture uses both gRPC (Protobuf-encoded) and REST (JSON-encoded) protocols across nine polyglot services. An attacker with man-in-the-middle positioning on the cluster network could modify messages in transit -- for example, altering order amounts in a gRPC call from the Order service to the Payment service, or changing product prices in responses from the Catalog service. Even without network-level access, a compromised sidecar or misconfigured proxy could inject, modify, or replay messages between services. The hexagonal architecture's ACL sidecars are particularly sensitive to tampering because they sit at the boundary between the domain core and external systems, making them a high-value target for message manipulation.

**Attack Vector:**
An attacker performs ARP spoofing or compromises a K8s CNI plugin to position themselves as a man-in-the-middle between two services. Alternatively, a compromised node could run a transparent proxy that intercepts and modifies gRPC frames. The attacker modifies field values in transit -- for instance, changing the `amount` field in a Payment request or the `status` field in an Order response.

**Impact Assessment:** Critical

**Specific Mitigation Implementation:**
All inter-service communication is encrypted and authenticated using mTLS with SVID-based certificates. The mTLS handshake ensures both integrity (any tampering is detected via TLS MAC verification) and confidentiality (message contents are encrypted). Certificate pinning at the SPIRE Agent level ensures that only SVIDs signed by the cluster's SPIRE Server are accepted. Additionally, all gRPC messages are validated against their Protobuf schema definitions at the application layer, providing defense-in-depth against malformed or injected messages. The Protobuf schema validation catches any structural tampering that might bypass TLS (e.g., a replayed message with modified field tags). For REST endpoints, OpenAPI schema validation performs the same function for JSON payloads.

**Verification Method:**
Execute network-level tampering tests using a test proxy that modifies gRPC and REST messages in transit. Verify that the mTLS handshake rejects connections from untrusted certificates and that any message modification is detected by the TLS integrity check. Run Buf breaking checks in CI to ensure schema validation covers all message types. Perform a chaos engineering exercise that injects malformed Protobuf messages between services and confirms they are rejected by schema validation.

### 1.3 Repudiation -- Denial of Action by a Service

**Threat Description:**
In a distributed system processing financial transactions (orders, payments), repudiation threats arise when a service denies having performed an action -- for example, the Payment service claiming it never processed a charge, or the Order service denying it created an order. Without end-to-end distributed tracing and immutable audit logs, it becomes impossible to determine which service initiated a particular action, making dispute resolution and compliance investigations unreliable. The risk is amplified by the Outbox pattern and CDC relay, where asynchronous event propagation introduces temporal gaps between action and downstream processing, creating opportunities for services to plausibly deny involvement in a transaction chain.

**Attack Vector:**
A compromised or malfunctioning service deliberately omits or corrupts trace context headers in outgoing requests, breaking the distributed trace chain. This makes it impossible to correlate downstream actions (e.g., a payment charge) with the originating service (e.g., the Order service). Alternatively, an insider with access to logging infrastructure could selectively delete audit log entries to cover their tracks.

**Impact Assessment:** High

**Specific Mitigation Implementation:**
OpenTelemetry distributed tracing with W3C Trace Context propagation ensures every request carries a traceparent header that links it to the originating operation. The Order and Payment services are instrumented with OTel SDKs that automatically propagate trace context across gRPC and HTTP calls, creating an immutable chain of causation. All trace data is exported to Grafana Tempo with 30-day retention. In addition, the Order and Payment services write structured audit logs (JSON format) to Grafana Loki with 14-day retention, capturing every state transition with timestamp, trace ID, service identity (SPIFFE ID), and action type. The audit logs are append-only and stored in a separate namespace with restricted write-once access, preventing deletion even by cluster administrators.

**Verification Method:**
Simulate a repudiation scenario where a service attempts to deny an action. Use Grafana Tempo to trace the complete request chain from Gateway through Order to Payment, verifying that every hop has a valid traceparent header. Confirm that audit logs in Loki contain the SPIFFE ID of the calling service and the trace ID. Attempt to delete audit log entries and verify that the write-once access control prevents deletion. Validate SC-6 (100% trace coverage) by running an OTel coverage audit across all services.

### 1.4 Information Disclosure -- Data Leakage Through Misconfigured Services

**Threat Description:**
The architecture includes services that handle sensitive data at varying classification levels: the Payment service processes PCI-DSS-regulated cardholder data, the Identity service manages cryptographic keys and workload identities, and the Order service stores customer PII. A misconfigured service -- for example, one that exposes a debug endpoint, logs sensitive fields, or accepts connections from any network namespace -- could leak this data to unauthorized parties. The polyglot nature of the architecture amplifies this risk because each language runtime (Go, Rust, Java, Python, Node.js) has different default logging configurations, error handling behaviors, and network binding semantics, making it difficult to enforce consistent data protection policies across the service fleet.

**Attack Vector:**
An attacker exploits a misconfigured Catalog service that exposes an unauthenticated REST endpoint returning full product records including internal pricing metadata. Alternatively, the Notification service logs payment confirmation events that include truncated card numbers and transaction amounts to an unsecured logging endpoint. A third vector is a compromised developer workstation that has kubectl access and can port-forward directly to the Payment service's gRPC port, bypassing the API Gateway.

**Impact Assessment:** High

**Specific Mitigation Implementation:**
Kubernetes NetworkPolicies enforce a default-deny ingress/egress model, ensuring that no service can receive connections except from explicitly whitelisted sources. The Payment service only accepts connections from the Order service's SPIFFE ID, and the Identity service only accepts connections from the SPIRE Agent and the Gateway. All service-to-service communication is encrypted via mTLS, preventing passive network sniffing. SPIFFE identity-based access control ensures that even if an attacker gains network access, they cannot establish a connection without a valid SVID. At the application layer, OTel instrumentation is configured to redact sensitive fields (card numbers, PII) from trace spans and log entries. The API Gateway terminates external TLS (TLS 1.3) and validates SVIDs at ingress, preventing unauthorized external access to internal services.

**Verification Method:**
Run a network policy audit using a tool like Calico Enterprise or Cilium to verify that every namespace has a default-deny policy and that only explicitly permitted communication paths exist. Attempt to port-forward to each service from an unauthorized namespace and verify the connection is blocked. Inspect OTel trace spans and log entries to confirm no sensitive data is included. Perform a PCI-DSS compliance scan on the Payment service's network boundaries.

### 1.5 Denial of Service -- Rate Limit Bypass or Resource Exhaustion

**Threat Description:**
The Gateway service handles all external ingress traffic, and the Payment service processes high-value financial transactions. Both are prime targets for denial-of-service attacks. An attacker could overwhelm the Gateway with requests that bypass rate limiting (e.g., by distributing requests across many source IPs), or they could target the Payment service with computationally expensive operations (e.g., repeated payment authorization attempts) that consume CPU and memory resources, causing legitimate requests to fail. The Notification and Analytics services, which consume events from Kafka, are vulnerable to a different DoS vector: a flood of events could overwhelm downstream consumers, causing backpressure that cascades to the Order and Payment services through the Outbox pattern.

**Attack Vector:**
An attacker launches a distributed HTTP flood against the Gateway's REST endpoints, exceeding the configured rate limit per IP by distributing requests across a botnet. Alternatively, an attacker discovers an expensive query path in the Analytics service's gRPC API that causes high CPU utilization, and repeatedly invokes it. A third vector is poisoning the Kafka event bus with malformed events that cause the Notification service's consumers to crash in a loop, consuming resources without processing legitimate events.

**Impact Assessment:** High

**Specific Mitigation Implementation:**
The API Gateway enforces rate limiting at multiple levels: per-IP, per-SPIFFE-ID, per-endpoint, and global. Rates are configured to allow legitimate traffic while rejecting bursts that exceed the SLO-defined capacity. Kubernetes resource quotas (CPU, memory, pod count) prevent any single service from consuming all cluster resources, implementing the bulkhead pattern at the infrastructure level. The Payment service uses a dedicated resource pool with guaranteed CPU and memory reservations, ensuring that even under load, payment processing capacity is preserved. The Gateway implements load shedding for non-critical paths (e.g., analytics queries) when CPU utilization exceeds 80%, protecting critical-path requests (order creation, payment processing). For Kafka consumers, the CDC Relay and Notification services implement backpressure controls that pause event consumption when downstream processing falls behind, preventing cascade failures.

**Verification Method:**
Execute a load test that simulates a 10x traffic spike against the Gateway and verify that rate limiting rejects excess requests with HTTP 429 responses. Monitor Kubernetes resource utilization during the test and confirm that no service exceeds its resource quota. Simulate a Kafka event flood and verify that backpressure controls prevent cascade failures. Validate against the SLO definitions: Gateway 99.99% availability, Payment 99.99% success rate, even under attack conditions.

### 1.6 Elevation of Privilege -- Service Accessing Resources Beyond Its Scope

**Threat Description:**
In a zero-trust architecture, every service should only access the resources it needs to fulfill its function. A privilege elevation threat occurs when a service -- whether through misconfiguration, compromised credentials, or exploited vulnerability -- accesses resources belonging to another service or namespace. For example, the Catalog service should never access the Payment service's database, and the Notification service should never have permission to modify order state. The Kubernetes RBAC system and SPIFFE/SPIRE identity model provide the foundation for least-privilege access, but misconfigured roles, overly broad service account permissions, or shared secrets can create privilege escalation paths. The ACL sidecars, which sit at the boundary between services and external systems, are particularly sensitive because they hold credentials for third-party APIs and could be used as a stepping stone to access other services' resources.

**Attack Vector:**
An attacker compromises the Notification service and uses its service account token to query the Order service's database directly (if the database is not behind a network policy). Alternatively, an over-permissive Kubernetes RBAC role allows the Catalog service's service account to list secrets in the Payment namespace, enabling the attacker to extract database credentials. A third vector is exploiting a container escape vulnerability to gain access to the node's kubelet credentials, which have cluster-wide permissions by default.

**Impact Assessment:** Critical

**Specific Mitigation Implementation:**
SPIFFE/SPIRE RBAC policies define exactly which SPIFFE IDs are allowed to communicate with each service. The Order service's mTLS configuration only accepts connections from the Gateway, Catalog, and Payment SPIFFE IDs; all other identities are rejected at the TLS handshake layer. Kubernetes RBAC follows the same least-privilege principle: each service's service account has exactly the permissions it needs (e.g., the Catalog service account can only read/write the catalog database, not the order or payment databases). NetworkPolicies enforce network-level segmentation that prevents the Notification service from reaching the Payment service's database port, even if it has valid credentials. All ACL sidecar credentials are stored in Kubernetes Secrets with limited access, and the sidecar containers run with non-root users and read-only filesystems. Container images use distroless or scratch bases to minimize the attack surface for container escapes.

**Verification Method:**
Audit all Kubernetes RBAC roles and bindings to verify that no service account has permissions beyond its namespace and function. Test cross-namespace access by attempting to reach each service's database from every other service and verifying the connection is blocked by NetworkPolicies. Review SPIFFE/SPIRE registration entries to confirm that each service's SPIFFE ID has the correct selectors and that no service can obtain an SVID for another service's identity. Run a container escape test using a known vulnerability in a test environment and verify that the distroless base image prevents exploitation.

---

## 2. SPIFFE/SPIRE Identity Design

The SPIFFE/SPIRE identity framework is the cryptographic backbone of the "Best of Both Worlds" zero-trust architecture. Unlike traditional VPN-based perimeter security or service mesh sidecar identity, SPIFFE/SPIRE provides workload identity that is independent of the network topology, cloud provider, and service mesh implementation. This aligns directly with the project's Technology-Neutral doctrine: services identify themselves using open standards (SPIFFE specification) rather than proprietary cloud identity services (AWS IAM Roles for Service Accounts, GCP Workload Identity, Azure Managed Identities). The identity design below specifies trust domains for each environment, workload registration entries for all nine services, and the certificate rotation strategy that ensures continuous security without operational overhead.

### Trust Domains

Trust domains define the boundary of cryptographic trust for the architecture. Each environment (development, staging, production) operates its own independent trust domain, ensuring that identities issued in one environment are not valid in another. This separation prevents a compromised development SPIRE Server from issuing identities that are trusted in production, and it ensures that a service migrated from staging to production receives a fresh identity rather than carrying over staging credentials.

| Environment | Trust Domain | SPIRE Server | Notes |
|-------------|-------------|--------------|-------|
| Development | `spiffe://dev.company.com` | Single replica, no HA | 24-hour SVID TTL for developer convenience |
| Staging | `spiffe://staging.company.com` | 2 replicas, HA | Mirrors production topology |
| Production | `spiffe://prod.company.com` | 3 replicas, HA + DR | 1-hour SVID TTL for maximum security |

Cross-environment communication is not permitted at the identity layer. If a staging service needs to call a production API, it must route through the API Gateway, which terminates the staging mTLS connection and establishes a new production mTLS connection with its own SVID. This ensures clean trust boundary enforcement and prevents trust domain confusion attacks.

### Workload Registration Entries

Every service in the polyglot topology requires a SPIFFE/SPIRE registration entry that defines its identity, parent, and selectors. The registration entries below follow a consistent naming convention that encodes the environment, namespace, and service name into the SPIFFE ID. Selectors are based on Kubernetes-native attributes (namespace, service account, pod labels) rather than cloud-specific attributes, maintaining the Technology-Neutral mandate.

#### Gateway Service

- **SPIFFE ID:** `spiffe://<env>.company.com/gateway/gateway`
- **Parent ID:** `spiffe://<env>.company.com/ns/gateway/sa/gateway-sa`
- **Selectors:** `k8s:ns:gateway`, `k8s:sa:gateway-sa`, `k8s:pod-label:app:gateway`
- **TTL:** 1 hour (production), 24 hours (dev)

#### Identity Service

- **SPIFFE ID:** `spiffe://<env>.company.com/identity/identity`
- **Parent ID:** `spiffe://<env>.company.com/ns/identity/sa/identity-sa`
- **Selectors:** `k8s:ns:identity`, `k8s:sa:identity-sa`, `k8s:pod-label:app:identity`
- **TTL:** 1 hour (production), 24 hours (dev)

#### Catalog Service

- **SPIFFE ID:** `spiffe://<env>.company.com/catalog/catalog`
- **Parent ID:** `spiffe://<env>.company.com/ns/catalog/sa/catalog-sa`
- **Selectors:** `k8s:ns:catalog`, `k8s:sa:catalog-sa`, `k8s:pod-label:app:catalog`
- **TTL:** 1 hour (production), 24 hours (dev)

#### Order Service

- **SPIFFE ID:** `spiffe://<env>.company.com/order/order`
- **Parent ID:** `spiffe://<env>.company.com/ns/order/sa/order-sa`
- **Selectors:** `k8s:ns:order`, `k8s:sa:order-sa`, `k8s:pod-label:app:order`
- **TTL:** 1 hour (production), 24 hours (dev)

#### Payment Service

- **SPIFFE ID:** `spiffe://<env>.company.com/payment/payment`
- **Parent ID:** `spiffe://<env>.company.com/ns/payment/sa/payment-sa`
- **Selectors:** `k8s:ns:payment`, `k8s:sa:payment-sa`, `k8s:pod-label:app:payment`
- **TTL:** 1 hour (production), 24 hours (dev)

#### Notification Service

- **SPIFFE ID:** `spiffe://<env>.company.com/notification/notification`
- **Parent ID:** `spiffe://<env>.company.com/ns/notification/sa/notification-sa`
- **Selectors:** `k8s:ns:notification`, `k8s:sa:notification-sa`, `k8s:pod-label:app:notification`
- **TTL:** 1 hour (production), 24 hours (dev)

#### Analytics Service

- **SPIFFE ID:** `spiffe://<env>.company.com/analytics/analytics`
- **Parent ID:** `spiffe://<env>.company.com/ns/analytics/sa/analytics-sa`
- **Selectors:** `k8s:ns:analytics`, `k8s:sa:analytics-sa`, `k8s:pod-label:app:analytics`
- **TTL:** 1 hour (production), 24 hours (dev)

#### CDC Relay Service

- **SPIFFE ID:** `spiffe://<env>.company.com/cdc-relay/cdc-relay`
- **Parent ID:** `spiffe://<env>.company.com/ns/cdc-relay/sa/cdc-relay-sa`
- **Selectors:** `k8s:ns:cdc-relay`, `k8s:sa:cdc-relay-sa`, `k8s:pod-label:app:cdc-relay`
- **TTL:** 1 hour (production), 24 hours (dev)

#### Schema Registry Service

- **SPIFFE ID:** `spiffe://<env>.company.com/schema-registry/schema-registry`
- **Parent ID:** `spiffe://<env>.company.com/ns/schema-registry/sa/schema-registry-sa`
- **Selectors:** `k8s:ns:schema-registry`, `k8s:sa:schema-registry-sa`, `k8s:pod-label:app:schema-registry`
- **TTL:** 1 hour (production), 24 hours (dev)

### mTLS Certificate Rotation Strategy

The certificate rotation strategy balances security (short-lived certificates minimize the window of exploitation) with availability (services must never drop connections during rotation). The strategy is fully automated and requires no manual intervention, aligning with the Efficiency First doctrine.

**SVID TTL Configuration:**
Production SVIDs have a 1-hour time-to-live, meaning that every certificate is valid for a maximum of 60 minutes. This dramatically reduces the value of a stolen certificate -- even if an attacker extracts an SVID from a compromised pod, it becomes useless within an hour. Development environments use a 24-hour TTL to reduce the frequency of rotation events during debugging sessions, where developers may need to inspect certificate contents without time pressure.

**Automatic Rotation via SPIRE Agent:**
The SPIRE Agent runs as a DaemonSet on every node and watches the SVID store for approaching expiration. When an SVID reaches 50% of its TTL (30 minutes in production), the SPIRE Agent proactively fetches a new SVID from the SPIRE Server. The new SVID is stored alongside the old one, and the Agent updates the workload's credential cache. The application retrieves the new SVID on its next mTLS handshake without requiring a restart or connection termination.

**Grace Period and Overlap:**
There is a 5-minute overlap period between the old and new SVIDs, during which both certificates are valid. This overlap ensures that in-flight connections established with the old SVID can complete naturally, while new connections use the updated certificate. The 5-minute window is chosen to be longer than the maximum expected gRPC stream duration but short enough to limit the exposure of a compromised old SVID.

**Revocation via Bundle Rotation:**
If a service's identity is compromised (e.g., a pod is breached and its SVID is stolen), revocation is handled through SPIRE bundle rotation. The SPIRE Server rotates its root key and publishes a new trust bundle. All services fetch the updated trust bundle from the SPIRE Agent, and the old SVID is no longer trusted because it was signed by the previous root key. This process completes within one SVID TTL (1 hour in production) -- after which the compromised identity is completely invalidated.

**Bootstrap via K8s Projected Service Account Tokens:**
When a pod first starts, it does not yet have an SVID. The SPIRE Agent bootstraps the workload's identity using the Kubernetes projected service account token, which is mounted into the pod at `/var/run/secrets/kubernetes.io/serviceaccount`. The SPIRE Agent verifies the token's signature against the Kubernetes API Server's public key and uses the token's namespace and service account claims to look up the corresponding SPIFFE registration entry. If the claims match, the SPIRE Agent issues the first SVID. This bootstrap mechanism ensures that no manual certificate distribution is required and that the identity chain starts from a Kubernetes-native trust anchor.

---

## 3. Defense-in-Depth Layers

Defense-in-depth is the foundational security principle for the "Best of Both Worlds" architecture. Rather than relying on a single security boundary (e.g., a perimeter firewall), the architecture implements four distinct layers of protection, each independently effective. If one layer is breached, the remaining layers continue to provide protection. This approach directly supports the Technology-Neutral doctrine by ensuring that security is not dependent on any single vendor's technology. Each layer is implemented using open standards and cloud-agnostic tools, ensuring that the security posture is portable across cloud providers.

### Layer 1: Network (L3/L4)

The network layer is the outermost defense ring, controlling which services can communicate with each other at the IP and port level. Kubernetes NetworkPolicies provide the enforcement mechanism, implementing a default-deny model that blocks all ingress and egress traffic unless explicitly permitted. This approach is the network equivalent of the zero-trust identity model: just as no service is trusted without a valid SVID, no network path is open without an explicit policy.

**Default Deny All Ingress/Egress:**
Every namespace in the cluster has a default NetworkPolicy that denies all ingress and egress traffic. This policy is applied before any service is deployed and is enforced by the CNI plugin (Calico or Cilium, both cloud-agnostic options). New services cannot communicate with anything until a per-service policy is created, forcing explicit access control decisions at deployment time.

**Per-Service Allow Lists:**
Each service has a dedicated NetworkPolicy that specifies exactly which other services (identified by pod label selectors and namespace) are allowed to connect to it. For example, the Payment service's ingress policy allows connections only from pods with the label `app: order` in the `order` namespace and `app: gateway` in the `gateway` namespace. All other ingress traffic is dropped silently.

**Egress Controls:**
Egress traffic is restricted to prevent data exfiltration and limit the blast radius of a compromised service. Each service's egress policy allows connections only to: the SPIRE Server (for SVID rotation), the OTel Collector DaemonSet (for telemetry export), Kafka (for event publishing and consumption), and explicitly whitelisted external endpoints (e.g., the payment provider's API, the SMTP relay). No service has direct internet access. All external communication routes through the API Gateway or the ACL sidecar, which provides an additional inspection and enforcement point.

### Layer 2: Identity (L7)

The identity layer operates above the network layer, providing cryptographic assurance of service identity at the application protocol level. While Layer 1 controls which IP addresses can reach which ports, Layer 2 controls which identities can establish mTLS sessions. This dual-layer approach ensures that even if a NetworkPolicy is misconfigured (e.g., an overly broad ingress rule), the mTLS handshake will reject unauthorized connections because the caller lacks a valid SVID.

**SPIFFE/SPIRE: Every Service Has Cryptographic Identity:**
As detailed in Section 2, every service in the architecture possesses a SPIFFE ID backed by an SVID. The SVID is an X.509 certificate that encodes the service's identity in the Subject Alternative Name (SAN) field. The SPIRE Agent on each node manages the SVID lifecycle, including issuance, rotation, and distribution to workloads. Services retrieve their SVIDs from the SPIRE Agent's Workload API, which uses Unix domain socket authentication to ensure that only local processes on the same node can access the credentials.

**mTLS: All Service-to-Service Communication Encrypted and Authenticated:**
Every gRPC and HTTP connection between services is wrapped in mutual TLS. Both the client and server present their SVIDs during the handshake, and both validate the peer's certificate against the SPIRE trust bundle. This ensures that communication is both encrypted (preventing eavesdropping) and authenticated (preventing impersonation). The mTLS configuration is injected into each service via the SPIRE Agent's Workload API, with no application code changes required -- the SPIRE SDK handles certificate retrieval and rotation transparently.

**API Gateway: Validates SVIDs at Ingress, Terminates External TLS:**
The API Gateway serves as the trust boundary between the external internet and the internal service mesh. External clients connect using standard TLS 1.3 (server-authenticated only), while the Gateway validates the incoming request and then establishes an mTLS connection to the downstream service using its own SVID. The Gateway also performs SVID-based authorization, ensuring that only authenticated clients can access internal services. Rate limiting and request validation are enforced at this boundary, providing a chokepoint for external threats.

### Layer 3: Application

The application layer provides security controls within the service itself, protecting against vulnerabilities that bypass the network and identity layers. These controls are particularly important for the "Best of Both Worlds" architecture because they enforce the Anti-Corruption Layer (ACL) boundaries that prevent vendor lock-in, and they validate that all messages conform to the schema contracts that enable language-agnostic communication.

**ACL Enforcement: Pre-Commit Hooks Block Proprietary SDK Imports:**
The hexagonal architecture mandates that no proprietary SDK imports appear in the `domain/` or `adapters/inbound/` directories. This rule is enforced by pre-commit hooks (managed via Lefthook) that scan source files for vendor-specific package imports (e.g., `aws-sdk`, `azure-identity`, `google-cloud-*`). If a proprietary import is detected in a forbidden directory, the commit is rejected with a clear error message explaining which import violated the ACL and how to route the dependency through the ACL sidecar instead. This automated enforcement ensures that the Technology-Neutral mandate is maintained across all nine services and all five language runtimes, without relying on manual code review.

**Schema Validation: All Messages Validated Against Protobuf/OpenAPI Schemas:**
Every gRPC message received by a service is validated against its Protobuf schema definition. The Buf compiler generates validation code that enforces field types, ranges, and required fields at deserialization time. For REST endpoints, the OpenAPI schema (generated from Protobuf via `buf generate`) is used to validate request and response payloads. This validation catches malformed messages that might exploit parser differences between language runtimes, and it ensures that the dual-contract strategy (gRPC + OpenAPI) produces consistent behavior across all services.

**Input Sanitization: Protobuf Field Validation + Custom Validators:**
Beyond schema-level validation, each service implements custom validators for high-risk fields. For example, the Payment service validates that currency codes conform to ISO 4217, the Order service validates that shipping addresses match a standardized format, and the Catalog service sanitizes search queries to prevent injection attacks. These validators are implemented as middleware in the hexagonal architecture's inbound adapter layer, ensuring they execute before any domain logic is invoked.

### Layer 4: Supply Chain

The supply chain layer protects against threats introduced through the build and deployment pipeline. In a polyglot architecture with five different language runtimes and dozens of third-party dependencies, the supply chain attack surface is significant. This layer implements SLSA (Supply-chain Levels for Software Artifacts) provenance, SBOM (Software Bill of Materials) generation, schema-breaking change prevention, container image signing, and minimal base images to reduce the attack surface.

**SLSA Level 3: Build Provenance and Verified Builds:**
Every container image is built in a hardened CI pipeline that generates SLSA Level 3 provenance attestations. The provenance record captures the build environment, source commit, build configuration, and all dependencies used during the build. This attestation is stored alongside the image in the OCI registry and can be verified at deployment time to ensure that the image was built from the expected source and has not been tampered with. SLSA Level 3 requires hermetic builds (no network access during build), which prevents dependency confusion attacks and ensures reproducibility.

**SBOM Generation: Syft/Trivy for Every Container Image:**
An SBOM is generated for every container image using Syft, which produces a comprehensive list of all packages and their versions in SPDX format. The SBOM is stored as an OCI artifact attached to the image in the registry. Trivy scans the SBOM against known vulnerability databases (CVE, GHSA) and produces a vulnerability report. Images with Critical or High severity unpatched vulnerabilities are blocked from deployment by an admission controller (Kyverno or OPA Gatekeeper).

**Buf Breaking Checks: No Schema-Breaking Changes in CI:**
Schema evolution is a critical supply chain concern because a breaking change to a Protobuf definition can cause runtime failures across all services that consume that schema. The Buf CLI's `buf breaking` command runs in CI on every pull request and compares the proposed schema changes against the latest released version. If a breaking change is detected (e.g., removing a field, changing a field type, renaming a service method), the CI pipeline fails and the merge is blocked. This enforcement is essential for the dual-contract strategy because it ensures that OpenAPI specs derived from Protobuf remain backward-compatible.

**Container Signing: Cosign Signatures on All OCI Images:**
Every container image pushed to the OCI registry is signed using Cosign (Sigstore). The signature is generated using a keyless signing flow that binds the image digest to the CI pipeline's OIDC identity. At deployment time, a Kyverno admission controller verifies the Cosign signature before allowing the pod to be created. This prevents deployment of unsigned images (which could be attacker-injected) and ensures that only images built by the authorized CI pipeline are running in the cluster.

**Base Image: Distroless or Scratch for All Services:**
All container images use distroless or scratch base images, which contain only the application binary and its direct runtime dependencies (e.g., glibc, ca-certificates). This eliminates shell access, package managers, and other utilities that attackers commonly use after gaining initial access to a container. The reduced attack surface means fewer vulnerabilities to patch and fewer tools available for lateral movement. For compiled languages (Go, Rust), scratch images are used; for JVM-based services (Java/Kotlin), distroless-java is used; for interpreted languages (Python, Node.js), distroless-python and distroless-nodejs are used respectively.

---

## 4. OWASP Top 10 Mapping

The OWASP Top 10 (2021 edition) represents the most critical web application security risks. This section maps each category to the architectural controls implemented in the "Best of Both Worlds" design. The mapping demonstrates that the architecture addresses all ten categories through a combination of infrastructure-level controls (NetworkPolicies, mTLS, RBAC), application-level controls (schema validation, ACL enforcement, input sanitization), and process-level controls (SLSA provenance, GitOps drift detection, OTel observability). Each mapping is traced to the specific defense-in-depth layer that provides the primary mitigation.

### A01:2021 -- Broken Access Control

Broken access control occurs when users can act outside their intended permissions. In the microservice context, this means a service accessing data or operations that belong to another service. The architecture mitigates this through three complementary mechanisms: SPIFFE/SPIRE identity-based access control ensures that only services with the correct SVID can establish mTLS connections; Kubernetes RBAC restricts each service account to its own namespace and resources; and NetworkPolicies enforce network-level segmentation that blocks unauthorized communication paths. Together, these three controls create a layered access control model where breaking through one layer still leaves two more in place. The SPIFFE/SPIRE identity model is particularly important because it makes access control decisions based on cryptographic identity rather than network location, which is more robust against network-level attacks like ARP spoofing or IP address spoofing.

### A02:2021 -- Cryptographic Failures

Cryptographic failures occur when sensitive data is transmitted or stored without proper encryption, or when weak cryptographic algorithms are used. The architecture mandates mTLS for all inter-service communication, ensuring that no data is transmitted in plaintext within the cluster. At the external boundary, the API Gateway enforces TLS 1.3 for all client connections, which eliminates support for legacy protocols (TLS 1.0, 1.1) and weak cipher suites. The SPIFFE/SPIRE SVIDs use ECDSA P-256 for signing and AES-128-GCM for encryption, which are considered secure by current cryptographic standards. No service stores sensitive data (passwords, API keys, database credentials) in plaintext; all secrets are managed through Kubernetes Secrets with encryption at rest enabled on the etcd cluster. The Payment service additionally encrypts cardholder data at rest using AES-256, meeting PCI-DSS requirements.

### A03:2021 -- Injection

Injection attacks occur when untrusted data is sent to an interpreter as part of a command or query. The architecture's defense against injection is multi-layered. First, all gRPC messages are validated against Protobuf schemas, which enforce strict typing and reject malformed inputs at the deserialization layer. Second, all database access uses parameterized queries through ORM frameworks (Hibernate for Java, SQLAlchemy for Python, GORM for Go, Diesel for Rust, Prisma for Node.js), which prevent SQL injection by construction. Third, the REST API endpoints validate request payloads against OpenAPI schemas, which define allowed field types, patterns, and ranges. Fourth, the Catalog service's search functionality uses structured query builders rather than raw query strings, preventing NoSQL injection in the search backend. These controls collectively ensure that injection is prevented at the framework level, without requiring developers to remember manual sanitization for every input.

### A04:2021 -- Insecure Design

Insecure design refers to fundamental design flaws that cannot be fixed through better implementation. The architecture mitigates this through the hexagonal architecture's ACL boundaries, which enforce a separation between domain logic and infrastructure concerns. If a vendor-specific feature is discovered to have insecure design patterns, the ACL sidecar can be replaced without affecting the domain core, preserving the Reversibility principle (SC-1). The defense-in-depth approach ensures that no single design flaw can compromise the entire system, because each layer provides independent protection. The GitOps model (ArgoCD with 30-second reconciliation) ensures that any unauthorized configuration change is automatically reverted, preventing design-level misconfigurations from persisting. The Buf breaking checks in CI prevent design-level API changes that could introduce insecure interfaces.

### A05:2021 -- Security Misconfiguration

Security misconfiguration is the most common vulnerability in cloud-native applications, encompassing default credentials, unnecessary features enabled, overly permissive settings, and unpatched systems. The architecture mitigates this through GitOps declarative configuration, where all infrastructure and application configuration is defined in version-controlled YAML manifests. ArgoCD continuously monitors the cluster state against the Git repository and reverts any drift within 30 seconds (SC-9), ensuring that misconfigurations cannot persist. The default-deny NetworkPolicy model ensures that no service is accessible by default, requiring explicit configuration to open communication paths. Pre-commit hooks scan for common misconfigurations (e.g., containers running as root, hostPath mounts, privileged mode). The distroless base images eliminate unnecessary services and utilities that are commonly misconfigured.

### A06:2021 -- Vulnerable and Outdated Components

Vulnerable components are a significant risk in a polyglot architecture with five language runtimes and hundreds of transitive dependencies. The architecture mitigates this through three automated mechanisms: SLSA Level 3 provenance ensures that all dependencies are verified and recorded; SBOM generation (Syft) produces a complete inventory of every package in every container image; and automated vulnerability scanning (Trivy) checks the SBOM against known CVE databases on every build and on a nightly schedule. Images with unpatched Critical or High severity vulnerabilities are blocked from deployment by the Kyverno admission controller. The Renovate bot automatically creates pull requests for dependency updates, ensuring that components are kept current without relying on manual tracking. The distroless base images reduce the number of vulnerable components by excluding unnecessary packages.

### A07:2021 -- Identification and Authentication Failures

Authentication failures occur when an application does not properly verify the identity of users or services. The architecture eliminates password-based authentication entirely for service-to-service communication, replacing it with SPIFFE/SPIRE workload identity. Services authenticate using SVIDs (X.509 certificates) rather than shared secrets or API keys, which are vulnerable to leakage and rotation failures. The SPIRE Agent manages the entire certificate lifecycle (issuance, rotation, distribution) without human intervention, eliminating the risk of forgotten or stale credentials. For external users, the API Gateway enforces OIDC-based authentication with short-lived JWT tokens, which are validated against the Identity Provider's public keys on every request. Session management uses HTTP-only, Secure, SameSite cookies with 15-minute expiration, preventing session fixation and cross-site request forgery.

### A08:2021 -- Software and Data Integrity Failures

Software and data integrity failures occur when code or data is used without verifying its integrity, such as deploying unsigned container images or consuming events from untrusted sources. The architecture addresses this through SLSA provenance (verifying that images were built from the expected source), Cosign image signing (verifying that images have not been tampered with after build), and Buf breaking checks (preventing schema-breaking changes that could corrupt data integrity). For event-driven communication, CloudEvents envelopes include a `traceparent` header that links each event to its originating distributed trace, enabling integrity verification across the asynchronous processing chain. The CDC Relay validates checksums on replicated data, ensuring that data migrated between databases maintains its integrity during cloud portability operations.

### A09:2021 -- Security Logging and Monitoring Failures

Security logging and monitoring failures occur when security-relevant events are not logged, or when logs are not monitored to detect attacks. The architecture mandates 100% distributed trace coverage (SC-6) using OpenTelemetry with W3C Trace Context propagation across all services. Every request generates a trace that is exported to Grafana Tempo, and every service emits structured logs (JSON format) to Grafana Loki. SLO-driven alerting (SC-8: MTTD less than 1 minute) ensures that security anomalies are detected and escalated to PagerDuty within seconds. The tail-based sampling strategy ensures that error traces and slow traces are always retained, while normal traces are sampled at 10%, balancing cost and observability. Security-specific events (authentication failures, authorization denials, certificate rotation failures) are logged at WARN level and trigger dedicated alert rules.

### A10:2021 -- Server-Side Request Forgery (SSRF)

Server-Side Request Forgery occurs when a server can be tricked into making requests to unintended destinations. The architecture mitigates this through Kubernetes NetworkPolicy egress controls that prevent services from making outbound connections to any destination not explicitly whitelisted. No service has direct internet access; all external communication routes through the API Gateway or ACL sidecars, which validate the destination against an allow list. The egress policies permit connections only to the SPIRE Server, OTel Collector, Kafka, and explicitly whitelisted external endpoints. This prevents an attacker from exploiting a service vulnerability to make requests to internal metadata services (e.g., cloud provider instance metadata APIs) or to exfiltrate data to attacker-controlled endpoints. The ACL sidecars add an additional layer of SSRF protection by validating that all outbound requests conform to the expected schema and destination.

---

## 5. Incident Response Integration

Incident response in the "Best of Both Worlds" architecture is not a manual, ad-hoc process but a systematic, SLO-driven workflow integrated into the observability and GitOps infrastructure. The architecture's incident response capabilities are designed to meet the project's success criteria for detection speed (SC-8: MTTD less than 1 minute) and recovery speed (MTTR less than 15 minutes via ArgoCD rollback). Every incident is tracked end-to-end through the OTel observability stack, and the response process generates artifacts (runbooks, post-incident reports) that continuously improve the system's resilience. The following sections detail each phase of the incident response lifecycle and how it integrates with the architecture's security controls.

### Detection: MTTD Target Less Than 1 Minute (SC-8)

Detection speed is the foundation of effective incident response. The architecture achieves sub-minute MTTD through OpenTelemetry's comprehensive instrumentation and SLO-driven alerting. Every service exports RED metrics (Rate, Errors, Duration) to the OTel Collector Gateway, which fans out to Prometheus for metric storage and evaluation. Prometheus alert rules are configured to fire when SLO error budget consumption exceeds 50% (for critical services like Gateway, Order, Payment) or 30% (for supporting services like Catalog, Notification). When an alert fires, it is routed to PagerDuty via the Alertmanager, which enriches the alert with the affected service's SPIFFE ID, the current error budget status, and a deep link to the relevant Grafana dashboard. The tail-based sampling strategy ensures that error traces are always captured, providing immediate context for the on-call engineer.

The detection pipeline also includes anomaly detection for security incidents. The OTel Collector's filter processor logs unexpected authentication failures (mTLS handshake rejections), which are aggregated in Loki and monitored by Prometheus alert rules. A spike in SVID validation failures triggers a security-specific alert that initiates the incident response workflow. This integration between the observability stack and the security controls ensures that security incidents are detected with the same speed and reliability as availability incidents.

### Containment and Recovery: MTTR Target Less Than 15 Minutes

Once an incident is detected, the containment and recovery process leverages the GitOps infrastructure to minimize blast radius and restore service. ArgoCD's reconciliation loop (30-second interval) provides the primary recovery mechanism: reverting the Git repository to the last known-good configuration automatically redeploys the affected service to its previous state. For security incidents involving a compromised identity, the SPIRE Server's bundle rotation mechanism revokes the compromised SVID within one TTL (1 hour in production), while NetworkPolicies immediately isolate the affected pod by removing its egress permissions.

For more complex incidents that require manual investigation, the on-call engineer can use the OTel trace data in Grafana Tempo to trace the full request chain and identify the root cause. The trace context (W3C Trace Context) links logs in Loki to specific requests, enabling rapid correlation of symptoms across services. Once the root cause is identified, the engineer creates a fix in a feature branch, which is automatically validated by the CI pipeline (Buf breaking checks, contract tests, vulnerability scans) before being merged to the develop branch. ArgoCD then deploys the fix to the cluster.

### Runbook: Auto-Generated from OTel Trace Analysis

Runbooks are critical for consistent and rapid incident response, but manually maintained runbooks quickly become outdated. The architecture automates runbook generation using OTel trace analysis. When an incident is detected, a runbook generator queries Grafana Tempo for the affected trace pattern and produces a step-by-step response guide that includes the affected service, the request path, the error type, the SLO impact, and the recommended recovery action. The runbook is attached to the PagerDuty incident and is also stored in a version-controlled runbook repository for future reference.

The auto-generated runbooks follow a standardized template that includes: incident classification (availability, security, performance), affected components (service names, SPIFFE IDs, namespaces), impact assessment (SLO error budget consumed, affected user count), detection timeline (first alert timestamp, acknowledgment timestamp), containment steps (isolate, rollback, rotate), and verification steps (confirm SLO recovery, verify no residual impact). This template ensures that every incident receives a consistent level of documentation, regardless of the responding engineer's experience level.

### Post-Incident: SLO Error Budget Tracking and Blameless Retro

Post-incident review is a mandatory step in the incident response lifecycle. Every incident that consumes more than 10% of an SLO error budget triggers an automatic blameless retrospective. The retrospective is scheduled within 48 hours of incident resolution and includes participants from the affected service team, the SRE team, and the security team (if the incident had a security component).

The retrospective is driven by data from the observability stack. The SLO error budget tracking system (implemented in Grafana) provides a quantitative summary of the incident's impact: total error budget consumed, duration of SLO violation, and recovery time. The OTel trace data provides a causal chain that explains how the incident propagated through the system. The audit logs in Loki provide an immutable record of all actions taken during the incident, including who responded, what actions were taken, and what the outcomes were.

The retrospective follows a blameless format: the focus is on system improvements, not individual blame. Action items are created as GitHub issues with the `incident-follow-up` label and are tracked through the standard sprint planning process. Recurring incidents or near-misses are escalated to the architecture review board for consideration of systemic changes, such as adding new defense-in-depth layers or tightening NetworkPolicies. This continuous improvement loop ensures that the architecture's security posture improves with every incident.

### Incident Response Metrics and Targets

| Metric | Target | Measurement Method |
|--------|--------|--------------------|
| MTTD (Mean Time To Detect) | Less than 1 minute | PagerDuty alert timestamp minus incident start timestamp |
| MTTA (Mean Time To Acknowledge) | Less than 5 minutes | PagerDuty acknowledgment timestamp minus alert timestamp |
| MTTR (Mean Time To Resolve) | Less than 15 minutes | Service recovery timestamp minus alert timestamp |
| SLO Error Budget Consumed per Incident | Less than 10% | Grafana SLO dashboard calculation |
| Runbook Availability | 100% of P1/P2 incidents | Auto-generated runbook attached to PagerDuty incident |
| Post-Incident Retro Completion | 100% of budget-consuming incidents | Retro scheduled within 48 hours of resolution |
| ArgoCD Rollback Time | Less than 30 seconds | ArgoCD reconciliation timestamp minus Git revert timestamp |
| SPIRE Bundle Rotation Time | Less than 1 SVID TTL | Time from revocation command to bundle propagation |
