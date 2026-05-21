# Gateway Service — Adapter Definitions

**Language:** Go
**Communication:** gRPC proxy + REST pass-through

---

## Inbound Adapters

### gRPC Handler
- **Maps to:** `gateway.v1.GatewayService`
- **RPCs:** `Route`, `Health`, `GetRateLimit`, `GetRouteConfig`
- **Description:** Accepts gRPC-HTTP2 requests on the gateway port. Implements the GatewayService proto definition by delegating to the RouteRequestPort and HealthCheckPort. The gRPC handler is the primary protocol for internal service-to-gateway communication, providing strong typing and binary protocol efficiency.

### REST Controller
- **Maps to:** `/api/v1/gateway/*`
- **Endpoints:**
  - `GET /health` → HealthCheckPort
  - `GET /rate-limit/{clientId}` → GetRateLimitPort
  - `GET /routes/{service}` → GetRouteConfigPort
  - `ANY /{path}` → RouteRequestPort (catch-all proxy)
- **Description:** Provides HTTP/REST access to gateway functionality for external clients that do not support gRPC. The catch-all proxy handler translates HTTP requests into internal RouteRequest calls, preserving headers and body content while adding observability context (W3C Trace Context injection).

### Event Consumer
- **Consumes from:** None (Gateway does not consume CloudEvents)
- **Description:** The Gateway service is purely request-driven. It does not subscribe to any event topics, as its role is synchronous ingress routing rather than asynchronous event processing.

---

## Outbound Adapters

### Persistence Adapter
- **Technology:** Redis (rate limit counters) + etcd (route configuration)
- **ORM/Query:** go-redis client + client-go for etcd
- **Description:** Stores rate limit counters in Redis using atomic INCR operations with TTL expiration. Route configuration is stored in etcd, which is already part of the Kubernetes control plane, avoiding additional infrastructure. Configuration changes are watched via etcd watchers for hot-reload without restart.

### Messaging Adapter
- **Technology:** None (Gateway does not produce events)
- **Description:** The Gateway service does not publish events to Kafka. It is a stateless request proxy that forwards traffic and returns responses synchronously. Any event publishing related to gateway activity (e.g., access logs) is handled by the OTel Collector downstream.

### External Service Adapter
- **Technology:** gRPC client connections to upstream services
- **ACL Required:** No (all upstream services are internal, using SPIFFE/SPIRE mTLS)
- **Description:** Maintains a connection pool to each upstream service. Connections are established using SPIFFE/SPIRE mTLS with automatic certificate rotation. Circuit breaker patterns (via resilience4j-go) protect against upstream failures, with fallback responses returned when circuit breakers are open.

### Observability Adapter
- **Technology:** OpenTelemetry Go SDK
- **Instrumentation Points:**
  - HTTP/gRPC server middleware (request duration, error rate, active connections)
  - Upstream client middleware (per-service latency, error rate, circuit breaker state)
  - Rate limiter metrics (limit hits, current counters, policy evaluations)
- **Description:** Instruments all gateway operations with OTel spans, metrics, and logs. Each proxied request creates a parent span with child spans for upstream calls, enabling end-to-end distributed tracing from client to service and back.
