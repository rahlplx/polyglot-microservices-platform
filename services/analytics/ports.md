# Analytics Service - Ports Definition

> Language: Python | Role: Dual interface (gRPC for queries, events for ingestion), metrics and trace analysis

## Inbound Ports (Driving / Use Case Interfaces)

### GetMetricsPort

- **Port Name:** `GetMetricsPort`
- **Input Type:** `GetMetricsRequest` (metric_names: list<string>, labels: map<string,string>, start_time: timestamp, end_time: timestamp, step: enum [MINUTE, HOUR, DAY], aggregation: enum [AVG, SUM, MAX, MIN, P50, P95, P99])
- **Output Type:** `GetMetricsResponse` (series: list<TimeSeries>, total_points: int64, resolution: string)
- **Error Types:** `MetricNotFoundError`, `InvalidTimeRangeError`, `AggregationNotSupportedError`
- **Description:** Retrieves aggregated metric time series data for dashboarding and alerting. The port supports querying multiple metric names in a single request, with optional label selectors for dimensional filtering (e.g., filtering by service name, endpoint, or status code). The time range is specified with start and end timestamps, and the step parameter controls the granularity of the returned data points. Aggregation functions determine how raw data points within each step interval are combined: AVG for average values, SUM for totals, MAX/MIN for peak/trough analysis, and percentile calculations (P50, P95, P99) for latency analysis. The port queries the time series database (ClickHouse) with optimized queries that leverage the database's columnar storage and merge tree engine for sub-second response times on typical dashboard queries. When the requested time range exceeds the retention period for raw data, the port automatically falls back to pre-aggregated rollup tables, trading granularity for performance.

### QueryTracesPort

- **Port Name:** `QueryTracesPort`
- **Input Type:** `QueryTracesRequest` (trace_id: optional<string>, service_name: optional<string>, operation_name: optional<string>, min_duration_ms: optional<int64>, max_duration_ms: optional<int64>, tags: map<string,string>, start_time: timestamp, end_time: timestamp, limit: int32)
- **Output Type:** `QueryTracesResponse` (traces: list<Trace>, total_count: int64, sampled: bool)
- **Error Types:** `TraceStorageUnavailableError`, `QueryTooBroadError`
- **Description:** Queries distributed traces for debugging and performance analysis. The port supports multiple query modes: direct trace lookup by trace ID (returns a single trace with all spans), service-based search (returns all traces involving a specific service within a time range), and operation-based search (returns all traces for a specific RPC or HTTP endpoint). Tag-based filtering allows searching for traces with specific attributes, such as error status, high latency, or specific customer IDs. The response includes the full span tree for each matching trace, with parent-child relationships and span attributes. The port includes a safeguard against overly broad queries that would scan too much data: if the estimated scan size exceeds a configurable threshold, a `QueryTooBroadError` is returned with suggestions for narrowing the query. Trace data is stored in ClickHouse with a specialized schema optimized for trace ID lookup and time-range scans.

### GetDashboardPort

- **Port Name:** `GetDashboardPort`
- **Input Type:** `GetDashboardRequest` (dashboard_id: string, variables: map<string,string>, time_range: TimeRange)
- **Output Type:** `GetDashboardResponse` (dashboard: Dashboard, panels: list<Panel>, data: map<string, TimeSeries>, rendered_at: timestamp)
- **Error Types:** `DashboardNotFoundError`, `VariableValidationError`, `DataFetchError`
- **Description:** Retrieves a pre-configured dashboard with live data. Dashboards are defined as configuration objects that specify a set of panels, each panel containing a metric query, visualization type, and display options. The `variables` parameter allows dynamic customization of dashboard queries (e.g., selecting a specific service, environment, or customer segment). The port executes all panel queries in parallel, aggregates the results, and returns the dashboard definition along with the populated data. This port powers the operational dashboard UI that provides real-time visibility into system health, business metrics, and SLA compliance. Dashboards are stored in PostgreSQL as JSON configuration objects, and the port caches rendered dashboard data for 30 seconds to reduce database load during frequent refresh cycles.

### GetReportPort

- **Port Name:** `GetReportPort`
- **Input Type:** `GetReportRequest` (report_type: enum [REVENUE_SUMMARY, ORDER_FUNNEL, INVENTORY_VELOCITY, PAYMENT_HEALTH, NOTIFICATION_EFFECTIVENESS, SERVICE_SLA, CUSTOMER_LIFETIME_VALUE], parameters: map<string,string>, time_range: TimeRange, format: enum [JSON, CSV, PDF], granularity: enum [HOURLY, DAILY, WEEKLY, MONTHLY])
- **Output Type:** `GetReportResponse` (report_id: string, report_type: string, generated_at: timestamp, data: ReportData, parameters: map<string,string>, time_range: TimeRange, format: string)
- **Error Types:** `ReportTypeNotFoundError`, `InsufficientDataError`, `ReportGenerationTimeoutError`
- **Description:** Generates a pre-configured analytical report with configurable parameters, time range, and output format. Reports are predefined analytical templates that encapsulate complex multi-metric queries into a single, well-structured output suitable for business stakeholders who need curated insights rather than raw time series data. Each report type includes a specific set of metrics, dimensions, and visualizations that are relevant to a particular business domain: revenue summary reports aggregate payment data into daily and monthly revenue figures with breakdowns by payment method and currency; order funnel reports track conversion rates from order creation through completion with drop-off analysis at each stage; inventory velocity reports analyze stock turnover rates and stockout frequency by product category. The `parameters` map allows dynamic customization of report queries, such as filtering by product category, customer segment, or geographic region. The `format` parameter controls the output format: JSON for programmatic consumption, CSV for spreadsheet analysis, and PDF for executive presentations. Report generation is asynchronous for large time ranges, with the port returning a report ID that can be polled for completion status. Generated reports are cached for 5 minutes to support repeated downloads without regenerating the underlying data.

## Outbound Ports (Driven / Infrastructure Interfaces)

### TimeSeriesDBPort

- **Port Name:** `TimeSeriesDBPort`
- **Operations:**
  - `Write(series: list<DataPoint>) -> void`: Writes metric data points to the time series database.
  - `Query(query: TimeSeriesQuery) -> list<TimeSeries>`: Executes a time series query with aggregation.
  - `CreateRollup(metric_name: string, interval: string) -> void`: Creates a pre-aggregated rollup table for a metric.
  - `GetRetentionPolicies() -> list<RetentionPolicy>`: Retrieves current data retention policies.
- **Technology:** ClickHouse (columnar OLAP database)
- **ACL Required:** No (internal infrastructure)
- **Description:** The time series database port manages all interactions with ClickHouse for metric storage and querying. ClickHouse was chosen for its exceptional query performance on time series aggregations, supporting billions of data points with sub-second query latency. The port uses ClickHouse's MergeTree engine for raw metric data and Materialized Views for automatic rollup aggregation. Data points are written in batches of 10,000 using the ClickHouse HTTP INSERT protocol for maximum throughput. Query execution uses ClickHouse's query cache and optimized aggregation functions (quantile, avg, sum) for efficient time-range scans. The port implements tiered retention: raw data is retained for 7 days, 1-minute rollups for 30 days, 1-hour rollups for 90 days, and 1-day rollups for 1 year, balancing storage cost against analytical granularity.

### TraceStoragePort

- **Port Name:** `TraceStoragePort`
- **Operations:**
  - `WriteSpans(spans: list<Span>) -> void`: Writes trace spans to the storage backend.
  - `GetTrace(trace_id: string) -> optional<Trace>`: Retrieves a complete trace by ID.
  - `QueryTraces(query: TraceQuery) -> list<Trace>`: Searches traces with filters.
  - `GetDependencies(start_time: timestamp, end_time: timestamp) -> DependencyGraph`: Retrieves the service dependency graph.
- **Technology:** ClickHouse (shared cluster, separate database from metrics)
- **ACL Required:** No (internal infrastructure)
- **Description:** The trace storage port manages all interactions with ClickHouse for distributed trace data. Spans are written in batches using a specialized ClickHouse table schema that encodes the span's trace ID, span ID, parent span ID, operation name, service name, start time, duration, and tags as columns. This columnar layout enables efficient filtering by service name, operation name, and tags without scanning the entire span payload. The dependency graph operation aggregates span data to derive the service-to-service communication topology, showing which services call which other services and the latency distributions of those calls. This graph is used for system topology visualization and for identifying critical path bottlenecks. Trace data is retained for 7 days in raw form and for 90 days in aggregated form (service-level latency percentiles and error rates).

### EventConsumerPort

- **Port Name:** `EventConsumerPort`
- **Operations:**
  - `Subscribe(topics: list<string>, handler: EventHandler) -> void`: Subscribes to domain event topics.
  - `Process(event: DomainEvent) -> ProcessingResult`: Processes a single domain event into analytics records.
- **Technology:** Apache Kafka (consuming all domain event topics)
- **ACL Required:** No (internal infrastructure)
- **Description:** The event consumer port handles ingestion of all domain events from the Kafka event backbone into the analytics data store. The port subscribes to every domain event topic and transforms each event into one or more analytics records: metric data points (for real-time dashboarding), trace context links (for correlating business events with infrastructure traces), and fact table rows (for historical reporting and trend analysis). The transformation logic is pluggable: each event type has a registered transformer that maps the event payload to the appropriate analytics schema. The port implements exactly-once processing using Kafka's transactional consumer API with idempotent writes to ClickHouse. The consumer supports parallel processing with a configurable concurrency limit to handle burst event volumes during peak traffic periods.
