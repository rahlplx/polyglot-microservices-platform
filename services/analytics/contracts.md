# Analytics Service - Contracts Definition

> Language: Python | Role: Dual interface (gRPC for queries, events for ingestion), metrics and trace analysis

## gRPC Contract

### Proto Package

- **Package Name:** `analytics.v1`
- **File:** `analytics/v1/analytics.proto`

### Service Definition

**Service Name:** `AnalyticsService`

| RPC Method | Request Type | Response Type | Streaming |
|---|---|---|---|
| `GetMetrics` | `GetMetricsRequest` | `GetMetricsResponse` | Unary |
| `Query` | `QueryTracesRequest` | `QueryTracesResponse` | Unary |
| `GetDashboard` | `GetDashboardRequest` | `GetDashboardResponse` | Unary |
| `GetReport` | `GetReportRequest` | `GetReportResponse` | Unary |

### RPC Details

**GetMetrics:**
Retrieves aggregated metric time series data. The request specifies one or more metric names, optional label selectors, a time range, a step interval for data point granularity, and an aggregation function. The response includes one TimeSeries per requested metric, each containing a list of timestamp-value pairs at the specified step interval. When the time range exceeds raw data retention, the service automatically falls back to pre-aggregated rollup tables, which may return data at a coarser resolution than requested.

**Query:**
Searches distributed traces based on various criteria. The request supports filtering by trace ID (direct lookup), service name, operation name, duration range, tags, and time range. The response includes the full span tree for each matching trace, with parent-child relationships preserved. The `sampled` flag indicates whether the result set represents a sample of all matching traces (when the total count exceeds the limit) or the complete set.

**GetDashboard:**
Retrieves a pre-configured dashboard with live data. The request specifies the dashboard ID, optional variables for dynamic customization, and the time range. The response includes the dashboard definition with all panels and the populated data for each panel, executing all panel queries in parallel for optimal performance.

**GetReport:**
Generates a pre-configured analytical report with configurable parameters, time range, and output format. The request specifies the report type (such as revenue summary, order funnel, or inventory velocity), dynamic parameters for filtering, the time range, and the desired output format (JSON, CSV, or PDF). The response includes the generated report data with curated insights suitable for business stakeholders.

### Key Message Types

```protobuf
message GetMetricsRequest {
  repeated string metric_names = 1;
  map<string, string> labels = 2;
  google.protobuf.Timestamp start_time = 3;
  google.protobuf.Timestamp end_time = 4;
  enum Step {
    MINUTE = 0;
    HOUR = 1;
    DAY = 2;
  }
  Step step = 5;
  enum Aggregation {
    AVG = 0;
    SUM = 1;
    MAX = 2;
    MIN = 3;
    P50 = 4;
    P95 = 5;
    P99 = 6;
  }
  Aggregation aggregation = 6;
}

message GetMetricsResponse {
  repeated TimeSeries series = 1;
  int64 total_points = 2;
  string resolution = 3;
}

message TimeSeries {
  string metric_name = 1;
  map<string, string> labels = 2;
  repeated DataPoint points = 3;
}

message DataPoint {
  google.protobuf.Timestamp timestamp = 1;
  double value = 2;
}

message QueryTracesRequest {
  optional string trace_id = 1;
  optional string service_name = 2;
  optional string operation_name = 3;
  optional int64 min_duration_ms = 4;
  optional int64 max_duration_ms = 5;
  map<string, string> tags = 6;
  google.protobuf.Timestamp start_time = 7;
  google.protobuf.Timestamp end_time = 8;
  int32 limit = 9;
}

message QueryTracesResponse {
  repeated Trace traces = 1;
  int64 total_count = 2;
  bool sampled = 3;
}

message Trace {
  string trace_id = 1;
  repeated Span spans = 2;
  google.protobuf.Timestamp start_time = 3;
  int64 duration_ms = 4;
  string root_service = 5;
  string root_operation = 6;
}

message Span {
  string trace_id = 1;
  string span_id = 2;
  optional string parent_span_id = 3;
  string operation_name = 4;
  string service_name = 5;
  google.protobuf.Timestamp start_time = 6;
  int64 duration_ms = 7;
  map<string, string> tags = 8;
  repeated SpanLink links = 9;
  SpanStatus status = 10;
}

enum SpanStatus {
  OK = 0;
  ERROR = 1;
  UNSET = 2;
}

message SpanLink {
  string trace_id = 1;
  string span_id = 2;
  string relationship = 3;
}
```

## OpenAPI Contract

### API Path Prefix

`/api/v1/analytics`

### Endpoints

| Method | Path | Request Body | Response | Auth Required |
|---|---|---|---|---|
| `POST` | `/api/v1/analytics/metrics/query` | `GetMetricsRequest` JSON | `GetMetricsResponse` JSON | Yes |
| `POST` | `/api/v1/analytics/traces/query` | `QueryTracesRequest` JSON | `QueryTracesResponse` JSON | Yes |
| `GET` | `/api/v1/analytics/dashboards` | None | Dashboard list | Yes |
| `GET` | `/api/v1/analytics/dashboards/{id}` | None | `GetDashboardResponse` JSON | Yes |
| `PUT` | `/api/v1/analytics/dashboards/{id}` | Dashboard config JSON | Updated dashboard | Yes (admin) |
| `GET` | `/api/v1/analytics/dependencies` | None (query params) | Dependency graph JSON | Yes |

### Endpoint Details

**POST /metrics/query:**
Executes a metric time series query. The request body is identical to the `GetMetricsRequest` protobuf message, serialized as JSON. The response includes one or more time series with data points at the requested step interval. Supports the `Accept: text/csv` header for CSV export of metric data (useful for spreadsheet analysis).

**POST /traces/query:**
Executes a trace search query. The request body is identical to the `QueryTracesRequest` protobuf message, serialized as JSON. The response includes matching traces with their full span trees. Supports the `Accept: application/json` and `Accept: application/zip` headers, where the ZIP format exports trace data in Jaeger-compatible JSON format for import into other trace analysis tools.

**GET /dashboards:**
Lists all available dashboards with their IDs, names, and descriptions. Supports `?tag=operations` query parameter for filtering by tag.

**GET /dashboards/{id}:**
Retrieves a dashboard with live data. Supports `?start=2024-01-01T00:00:00Z&end=2024-01-02T00:00:00Z` query parameters for the time range, and `?var_service=catalog` for variable substitution. The response includes the dashboard definition and the populated data for all panels.

**GET /dependencies:**
Retrieves the service dependency graph derived from trace data. Supports `?start=...&end=...` query parameters for the time range and `?format=dot` for Graphviz DOT format output. The graph shows service-to-service edges with latency percentiles and error rates.

### Authentication Requirements

- All endpoints require authentication via JWT token or mTLS with SPIFFE SVID
- Read operations (GET) require the `analytics:read` scope
- Write operations (PUT) require the `analytics:admin` scope
- Internal service-to-service calls use mTLS with SPIFFE SVID verification
- Rate limiting is applied per client ID with generous limits for dashboard refresh cycles

## Event Contracts

### CloudEvents Type Prefix

`com.company.analytics.`

### Consumed Event Types

The Analytics service consumes all domain events from every service in the system. The following table summarizes the primary consumed topics and their analytical purpose:

| Consumed Topic Pattern | Analytical Purpose |
|---|---|
| `com.company.order.*` | Order funnel metrics, conversion rates, fulfillment latency |
| `com.company.payment.*` | Payment success rates, refund rates, revenue tracking |
| `com.company.catalog.*` | Catalog growth, inventory velocity, stockout rates |
| `com.company.notification.*` | Delivery rates, open rates, channel effectiveness |
| `com.company.identity.*` | Certificate lifecycle, SVID issuance rates, rotation patterns |
| `com.company.gateway.*` | Request routing metrics, rate limit violations |

### Produced Event Types

| Event Type | Payload Schema | Consumer Services |
|---|---|---|
| `com.company.analytics.alert.triggered` | `AlertTriggeredEvent` | Notification |

### Event Details

**AlertTriggeredEvent:**
Emitted when a configured alert threshold is crossed. The payload includes the alert name, severity level (INFO, WARNING, CRITICAL), the metric value that triggered the alert, the threshold, the time window, and a list of suggested actions. The Notification service consumes this event to dispatch on-call alerts via the appropriate channel (PagerDuty webhook, Slack message, or SMS based on severity and on-call configuration). Alert rules are configured through the dashboard API and stored in PostgreSQL, with support for static thresholds, anomaly detection (using statistical process control), and rate-of-change alerts (triggering when a metric changes too rapidly, even if it is within absolute bounds).
