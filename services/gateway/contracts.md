# Gateway Service — Contract Definitions

**Language:** Go
**Communication:** gRPC proxy + REST pass-through

---

## gRPC Contract

**Proto Package:** `gateway.v1`
**Service Name:** `GatewayService`

### RPC Methods

| Method | Request | Response | Description |
|--------|---------|----------|-------------|
| `Route` | `RouteRequest` | `RouteResponse` | Route incoming request to target upstream service |
| `Health` | `HealthCheckRequest` | `HealthCheckResponse` | Return gateway and downstream health status |
| `GetRateLimit` | `RateLimitRequest` | `RateLimitResponse` | Query rate limit status for a client and route |
| `GetRouteConfig` | `RouteConfigRequest` | `RouteConfigResponse` | Return current route configuration for a service |

### Key Message Types

```
message RouteRequest {
  string method = 1;          // HTTP method (GET, POST, etc.)
  string path = 2;            // Request path
  map<string, string> headers = 3;  // Request headers
  bytes body = 4;             // Request body (binary-safe)
  string trace_context = 5;   // W3C Trace Context (extracted from headers)
}

message RouteResponse {
  uint32 status = 1;          // HTTP status code
  map<string, string> headers = 2;  // Response headers
  bytes body = 3;             // Response body
  string upstream_service = 4;  // Name of upstream service that handled request
}

message HealthCheckResponse {
  enum ServingStatus {
    UNKNOWN = 0;
    SERVING = 1;
    NOT_SERVING = 2;
    DEGRADED = 3;
  }
  ServingStatus status = 1;
  int64 uptime_seconds = 2;
  repeated DownstreamHealth downstream = 3;
}
```

---

## OpenAPI Contract

**API Path Prefix:** `/api/v1/gateway`
**Authentication:** SPIFFE/SPIRE mTLS (internal), API Key + OAuth2 (external)

### Endpoints

| Method | Path | Request | Response | Auth |
|--------|------|---------|----------|------|
| GET | `/api/v1/gateway/health` | - | `HealthCheckResponse` | None (public) |
| GET | `/api/v1/gateway/rate-limit/{clientId}` | Query params: `route`, `window` | `RateLimitResponse` | mTLS |
| GET | `/api/v1/gateway/routes/{service}` | - | `RouteConfigResponse` | mTLS |
| ANY | `/api/v1/gateway/{path}` | Full HTTP request | Proxied response | API Key + mTLS |

### Authentication Requirements

- **External clients:** API Key in `X-API-Key` header + OAuth2 Bearer token for authenticated endpoints
- **Internal services:** SPIFFE/SPIRE mTLS with SVID validation at gateway ingress
- **Health endpoint:** Unauthenticated (required by load balancers and K8s probes)

---

## Event Contracts

**CloudEvents Type Prefix:** None (Gateway does not produce events)

The Gateway service is purely synchronous and does not publish CloudEvents. All observability data (traces, metrics, logs) flows through the OTel Collector pipeline rather than through CloudEvents.
