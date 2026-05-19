# Gateway Service — Port Definitions

**Language:** Go
**Communication:** gRPC proxy + REST pass-through
**Responsibility:** Ingress routing, rate limiting, request dispatching

---

## Inbound Ports (Driving / Use Case Interfaces)

### RouteRequestPort
- **Input:** `RouteRequest { method, path, headers, body }`
- **Output:** `RouteResponse { status, headers, body, upstream_service }`
- **Errors:** `RouteNotFound`, `RateLimitExceeded`, `UpstreamUnavailable`
- **Description:** Core routing port that accepts incoming HTTP/gRPC requests, resolves the target service using route configuration, applies rate limiting policies, and forwards the request to the appropriate upstream service. This is the primary entry point for all external traffic entering the system.

### HealthCheckPort
- **Input:** `HealthCheckRequest {}`
- **Output:** `HealthCheckResponse { status, uptime, downstream_health[] }`
- **Errors:** None (always returns a response)
- **Description:** Provides liveness and readiness probe responses for Kubernetes health checks. Aggregates downstream service health status to provide a complete picture of system availability. Used by load balancers and ArgoCD to determine routing and deployment readiness.

### GetRateLimitPort
- **Input:** `RateLimitRequest { client_id, route, window_seconds }`
- **Output:** `RateLimitResponse { allowed, remaining, reset_at, policy }`
- **Errors:** `InvalidClient`, `PolicyNotFound`
- **Description:** Queries the current rate limit status for a given client and route combination. Returns whether the request is allowed, how many remaining requests are in the current window, and when the limit resets. This port enables both enforcement and observability of rate limiting policies.

### GetRouteConfigPort
- **Input:** `RouteConfigRequest { service_name, version }`
- **Output:** `RouteConfigResponse { routes[], middleware[], timeout_ms }`
- **Errors:** `ServiceNotFound`, `VersionNotFound`
- **Description:** Retrieves the current routing configuration for a specific service and version. Returns the full route table including path patterns, middleware chains (auth, rate limit, mTLS validation), and timeout settings. Used by the admin API and ArgoCD for configuration verification.

---

## Outbound Ports (Driven / Infrastructure Interfaces)

### ServiceDiscoveryPort
- **Operations:** `Resolve(service_name) → endpoints[]`, `Watch(service_name) → stream<endpoint_change>`
- **Technology:** Kubernetes Service Discovery + DNS
- **ACL Required:** No (internal K8s service discovery is vendor-agnostic)
- **Description:** Resolves service endpoints using Kubernetes DNS and watches for endpoint changes. The gateway uses this port to discover available upstream instances without hardcoding service addresses, enabling dynamic routing as services scale up or down.

### RateLimitStorePort
- **Operations:** `Increment(key, window) → count`, `Get(key) → limit_status`, `Reset(key) → void`
- **Technology:** Redis (in-memory, configurable)
- **ACL Required:** No (Redis is open-source and interchangeable)
- **Description:** Persists rate limit counters using a sliding window algorithm. The store must support atomic increment operations and TTL-based expiration. Redis is the default implementation but any key-value store with atomic operations can be substituted.

### IdentityClientPort
- **Operations:** `ValidateSVID(svid) → identity`, `GetTrustBundle() → bundle`
- **Technology:** SPIRE Agent Workload API
- **ACL Required:** No (SPIFFE/SPIRE is a CNCF open standard)
- **Description:** Validates incoming SPIFFE Verifiable Identity Documents (SVIDs) at the gateway ingress. The gateway uses this port to verify that incoming requests from internal services carry valid mTLS certificates issued by the SPIRE trust domain. This is the first layer of zero-trust authentication.
