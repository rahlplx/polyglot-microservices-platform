# Performance Budget

**Project Phase:** 2 (Design & Polyglot Architecture Mapping)
**Spec Item:** 2.7
**Owner:** Performance Lead
**Status:** Active

---

## 1. API Latency Targets

Latency budgets define the maximum acceptable response times for each service at the p50, p95, and p99 percentiles. These targets are derived from the end-user experience requirements, the computational complexity of each service, and the downstream dependencies that each service must coordinate with. Every target has been calibrated against industry benchmarks for microservice architectures and adjusted to reflect the specific technology choices documented in the Phase 2 design specification, including gRPC communication, SPIFFE/SPIRE identity, and saga-based orchestration patterns. The percentile breakdown ensures that the majority of requests are served quickly while still accounting for tail latency, which is the primary driver of user dissatisfaction in distributed systems.

| Service | p50 Target | p95 Target | p99 Target | Rationale |
|---------|-----------|-----------|-----------|-----------|
| Gateway | <10ms | <25ms | <50ms | Proxy overhead only, no business logic |
| Identity | <15ms | <50ms | <100ms | SPIRE SVID issuance + verification |
| Catalog | <50ms | <100ms | <200ms | Search queries, index lookups |
| Order | <100ms | <200ms | <300ms | Saga orchestration, multi-service calls |
| Payment | <200ms | <350ms | <500ms | External payment gateway + circuit breaker |
| Notification | <50ms | <100ms | <150ms | Async processing, template rendering |
| Analytics | <100ms | <300ms | <500ms | Time-series queries, aggregation |
| CDC Relay | N/A | N/A | <1000ms | CDC lag target (Debezium to Kafka) |
| Schema Registry | <20ms | <50ms | <100ms | Schema lookup and validation |

### Gateway (<10ms / <25ms / <50ms)

The API Gateway serves as the entry point for all external traffic and performs request routing, authentication token validation, rate limiting, and header transformation. Because it contains no business logic and acts purely as a proxy layer, the latency budget is extremely tight. The p50 target of under 10 milliseconds assumes Envoy or similar L7 proxy with connection pooling and keep-alive enabled, which eliminates TCP handshake overhead on repeated calls. The p95 target of under 25 milliseconds accounts for occasional TLS termination and JWT validation against the SPIRE identity layer. The p99 target of under 50 milliseconds provides headroom for rare events such as route cache misses, connection re-establishment after a backend restart, or brief spikes in concurrent connection count.

Contributing factors to Gateway latency include network round-trip time between the client and the gateway pod (typically sub-millisecond within the same Kubernetes cluster), TLS handshake cost on new connections, JWT/SVID validation overhead, and request header enrichment. OpenTelemetry will measure Gateway latency using server-side HTTP span duration with explicit attributes for `gateway.route`, `gateway.tls_handshake`, and `gateway.auth_check`. Alerts will fire when the p99 exceeds 50ms for two consecutive evaluation windows of 60 seconds each. When breached, the Gateway activates connection throttling, sheds non-critical header enrichment, and falls back to cached route tables rather than performing dynamic route lookups.

### Identity (<15ms / <50ms / <100ms)

The Identity service manages SPIRE SVID issuance, rotation, and verification across all workloads in the service mesh. The p50 target of under 15 milliseconds reflects the typical case where an SVID is already cached locally and verification requires only a signature check against the trust bundle. The p95 target of under 50 milliseconds accounts for SVID rotation events, which require a round-trip to the SPIRE server and trust bundle refresh. The p99 target of under 100 milliseconds handles cold-start scenarios where a pod must obtain its initial SVID, including the SPIRE agent registration handshake and the first JWT-SVID signing operation.

Latency contributors include SPIRE server round-trip time, trust bundle download and parsing, JWT-SVID signing operations, and X.509-SVID certificate chain validation. The service also performs workload API calls for attestation, which add variable latency depending on the attestation method (Kubernetes PSAT, Unix UID, etc.). OpenTelemetry measures Identity latency through custom spans for `identity.svid_issuance`, `identity.trust_bundle_refresh`, and `identity.workload_attestation`. Alerting thresholds trigger at 2x the p99 target (200ms) for a sustained period of 5 minutes. When targets are breached, the Identity service falls back to cached SVIDs and trust bundles, defers non-critical rotation events, and signals the Gateway to accept slightly older SVIDs with a configurable skew allowance.

### Catalog (<50ms / <100ms / <200ms)

The Catalog service handles product search, filtering, and retrieval operations. The p50 target of under 50 milliseconds assumes that the most common queries are served from an in-memory cache or a well-indexed database lookup. The p95 target of under 100 milliseconds accounts for complex search queries involving multiple filter combinations, sorting, and pagination. The p99 target of under 200 milliseconds provides headroom for cache misses that require full database scans, re-indexing operations running concurrently, or queries that hit a cold replica after a failover event.

Key latency factors include database query execution time, index lookup efficiency, cache hit ratio, and the cost of serializing large result sets into Protobuf responses. Network latency between the Catalog pod and the database is typically sub-millisecond within the same availability zone but can increase during cross-AZ failover. OpenTelemetry instruments the Catalog service with spans for `catalog.search`, `catalog.index_lookup`, and `catalog.cache_hit_or_miss`. Metrics include `catalog.query_duration`, `catalog.cache_hit_rate`, and `catalog.result_set_size`. Alerting fires when p99 exceeds 200ms for 3 consecutive minutes, triggering auto-scaling of read replicas, cache warming of the top 100 queries, and query plan analysis via the OTel-collected database client metrics.

### Order (<100ms / <200ms / <300ms)

The Order service orchestrates multi-step saga transactions across the Catalog, Payment, and Notification services. The p50 target of under 100 milliseconds represents a simple order creation that completes all saga steps without compensation. The p95 target of under 200 milliseconds accounts for orders that require retry on one or more downstream services or involve inventory reservation contention. The p99 target of under 300 milliseconds handles worst-case scenarios including saga compensation (rollback), payment gateway retries, and concurrent order conflicts that require optimistic locking resolution.

Latency contributors include saga orchestration overhead, downstream service call latency (which cascades from Payment and Catalog budgets), database transaction time for order state persistence, and the cost of publishing Outbox events to the CDC relay. The saga pattern inherently amplifies tail latency because each step depends on the previous step's completion. OpenTelemetry traces the full saga execution as a parent span with child spans for each step, tagged with `order.saga_step`, `order.compensation_required`, and `order.retry_count`. Alerting triggers at 2x p99 (600ms) sustained for 5 minutes. Breach responses include activating circuit breakers on slow downstream services, falling back to asynchronous order processing with user notification, and shedding low-priority order types during peak load.

### Payment (<200ms / <350ms / <500ms)

The Payment service integrates with external payment gateways, making it the most latency-variable service in the architecture. The p50 target of under 200 milliseconds assumes a warm connection to the payment provider with a cached token. The p95 target of under 350 milliseconds accounts for token refresh, 3DS challenge initiation, and retry on transient gateway errors. The p99 target of under 500 milliseconds handles full 3DS authentication flows, gateway rate limiting responses, and failover to a secondary payment provider.

External dependency latency dominates this budget, with the payment gateway response time being the largest single contributor. Network latency to external endpoints varies by provider and region, typically ranging from 50ms to 200ms. Circuit breaker state transitions add overhead during partial outage scenarios. OpenTelemetry instruments the Payment service with spans for `payment.gateway_request`, `payment.token_refresh`, `payment.3ds_challenge`, and `payment.circuit_breaker_state`. The circuit breaker pattern is critical here: after 5 consecutive failures or 50% error rate in a 10-second window, the circuit opens and all requests are fast-failed, returning a queued-for-retry response to the Order service saga. Alerting triggers at 2x p99 (1000ms) sustained for 3 minutes, which also escalates to the on-call engineer via PagerDuty.

### Notification (<50ms / <100ms / <150ms)

The Notification service processes asynchronous message delivery including email, SMS, and push notifications. The p50 target of under 50 milliseconds reflects the typical case where the service accepts a notification request, validates the payload, and enqueues it for delivery without performing the actual send synchronously. The p95 target of under 100 milliseconds accounts for template rendering with variable substitution, recipient list expansion, and priority queue insertion. The p99 target of under 150 milliseconds handles bulk notification requests, template cache misses, and delivery channel selection logic.

Latency contributors include template rendering engine performance, recipient lookup and deduplication, delivery channel routing decisions, and queue write latency. Because the service is primarily asynchronous, the latency budget focuses on acceptance latency rather than delivery latency, which is tracked as a separate metric. OpenTelemetry measures Notification acceptance latency with spans for `notification.accept`, `notification.template_render`, and `notification.enqueue`. Delivery latency is tracked as a separate gauge metric. Alerting triggers when p99 exceeds 150ms for 5 consecutive minutes. Breach responses include activating a simplified template renderer that skips variable substitution for non-critical notifications, shedding bulk notification requests to a dead-letter queue, and prioritizing transactional notifications over marketing notifications.

### Analytics (<100ms / <300ms / <500ms)

The Analytics service executes time-series queries, aggregation pipelines, and reporting workloads. The p50 target of under 100 milliseconds assumes a pre-computed materialized view or a simple time-range query hitting a warm cache. The p95 target of under 300 milliseconds accounts for ad-hoc aggregation queries that scan multiple time partitions. The p99 target of under 500 milliseconds handles complex cross-dimensional aggregations, large result set serialization, and concurrent query execution under load.

The primary latency factors are database query complexity, partition pruning efficiency, materialized view freshness, and result set size. Time-series databases like TimescaleDB or ClickHouse can achieve sub-100ms queries on well-partitioned data but degrade significantly on cross-partition scans. OpenTelemetry instruments Analytics with spans for `analytics.query_execution`, `analytics.partition_scan`, and `analytics.result_serialization`. Metrics include `analytics.query_duration`, `analytics.rows_scanned`, and `analytics.cache_hit_rate`. Alerting fires at 2x p99 (1000ms) sustained for 5 minutes. Breach responses include query cancellation for queries exceeding a 30-second timeout, automatic downgrade to approximate query results, and load shedding of ad-hoc queries in favor of scheduled report generation.

### CDC Relay (N/A / N/A / <1000ms)

The CDC Relay, implemented via Debezium connectors and Kafka, does not have traditional request-response latency targets. Instead, the budget is expressed as a lag target: the maximum acceptable delay between a database change event and its availability in the Kafka topic. The lag target of under 1000 milliseconds ensures that downstream consumers (Analytics, Notification triggers, Outbox pattern delivery) receive events within a second of the source transaction commit. This target is measured as the 99th percentile of `debezium.source.lag_ms`, which captures the time between the transaction commit timestamp and the Kafka produce timestamp.

Contributing factors to CDC lag include Debezium connector snapshot polling interval, database transaction log read latency, Kafka producer batching delay, and connector restart recovery time. During normal operation, lag should be well under 500ms. The 1000ms p99 target provides headroom for batch compaction events, connector configuration reloads, and brief Kafka broker leadership transitions. OpenTelemetry collects CDC lag as a gauge metric via the Debezium JMX exporter, correlated with Kafka consumer lag metrics. Alerting triggers when lag exceeds 5000ms (5 seconds) for 2 consecutive minutes, indicating a potential connector stall. Breach responses include reducing the connector snapshot polling interval, increasing the Kafka producer batch size, and alerting the database team to check for long-running transactions that block log advancement.

### Schema Registry (<20ms / <50ms / <100ms)

The Schema Registry serves schema lookup, validation, and compatibility check requests for all services in the architecture. The p50 target of under 20 milliseconds assumes a cached schema lookup, which is the common case since schemas change infrequently and clients cache aggressively. The p95 target of under 50 milliseconds accounts for compatibility checks that require comparing multiple schema versions. The p99 target of under 100 milliseconds handles cold-start cache misses, global schema ID allocation under high concurrency, and subject listing operations.

Latency is dominated by in-memory lookup time (sub-millisecond for cached entries), disk I/O for cache misses, and network latency between the client and the registry pod. Because the Schema Registry is lightweight and stateless (with persistence delegated to Kafka), its latency profile is extremely predictable. OpenTelemetry instruments the Schema Registry with spans for `schema.lookup`, `schema.compatibility_check`, and `schema.registration`. Metrics include `schema.cache_hit_rate` and `schema.registration_duration`. Alerting triggers at 2x p99 (200ms) sustained for 5 minutes. Breach responses are minimal since the registry rarely breaches targets, but include expanding the in-memory cache, pre-warming the cache on pod startup, and falling back to locally cached schema copies in client libraries.

---

## 2. Core Web Vitals (Web Dashboards)

Core Web Vitals are Google's user-centric performance metrics that quantify the real-world experience of web application users. For this project, any web-facing component including operational dashboards, API documentation portals, and administrative panels must meet the following targets. These targets are not aspirational guidelines; they are hard requirements that will be validated in CI using Lighthouse CI and Playwright-based performance tests, and monitored in production using Real User Monitoring (RUM) via the OTel browser SDK.

### Largest Contentful Paint (LCP): <2.5 seconds

LCP measures the render time of the largest content element visible in the viewport, which for dashboards is typically the primary data table or chart panel. The 2.5-second target requires that the initial dashboard render completes within this window, including HTML download, CSS parsing, JavaScript bundle execution, and the first API data fetch. To achieve this, dashboard frontends must implement code splitting (only load the visible chart library), server-side rendering for the initial shell, and API response caching at the Gateway layer. The primary contributors to LCP are JavaScript bundle size, API response time for dashboard data, and rendering complexity of chart components. OpenTelemetry browser SDK measures LCP as a custom metric, correlating it with backend trace data to identify whether LCP misses are caused by frontend rendering delays or backend API latency.

### First Input Delay (FID): <100 milliseconds

FID measures the time from a user's first interaction (click, tap, key press) to the time the browser begins processing event handlers. The 100-millisecond target ensures that the dashboard feels immediately responsive when a user clicks a filter, navigates to a different panel, or interacts with a chart. FID degradation is typically caused by long JavaScript tasks that block the main thread, such as large data processing, chart rendering, or synchronous API calls. Mitigations include breaking long tasks into smaller chunks using `requestIdleCallback`, deferring non-critical JavaScript execution, and implementing progressive data loading. The OTel browser SDK captures FID as a custom span, allowing correlation with specific user interactions and identification of blocking tasks.

### Cumulative Layout Shift (CLS): <0.1

CLS measures the sum of all unexpected layout shift scores that occur during the page's lifespan. A layout shift happens when visible elements move from one rendered position to another. The 0.1 target ensures that dashboard content does not jump or shift as data loads, images render, or dynamic content appears. Common causes of CLS in dashboards include charts that resize after data loads, tables that shift when column widths are calculated dynamically, and skeleton placeholders that do not match the final content dimensions. Mitigations include reserving explicit dimensions for all dynamic content areas, using CSS `aspect-ratio` for chart containers, and implementing content placeholders that match the final rendered size. CLS is measured continuously via the OTel browser SDK, and any shift exceeding 0.1 per page load triggers an alert for frontend investigation.

### Time to First Byte (TTFB): <200 milliseconds

TTFB measures the time from the browser's navigation request to the first byte of the response arriving. The 200-millisecond target for dashboard data APIs ensures that the backend responds quickly enough to not become the bottleneck for LCP. This target aligns with the Gateway p99 latency budget of 50ms plus the downstream service latency, leaving sufficient headroom. TTFB contributors include DNS resolution, TLS handshake, server processing time, and network round-trip. For dashboard-specific endpoints, TTFB can be optimized by implementing response caching at the Gateway, pre-computing aggregation queries, and using HTTP/2 server push for critical assets. OTel measures TTFB via browser performance API integration, correlating client-side TTFB with server-side span duration to identify whether delays originate in the network, the Gateway, or the downstream service.

---

## 3. OTel Collection Budgets

OpenTelemetry collection budgets define the volume, retention, and cost optimization strategy for each observability signal. The principle guiding these budgets is "observe everything that matters, sample what is routine, discard what is noise." This approach ensures that error conditions and performance anomalies are always captured with full fidelity, while routine successful operations are sampled to control storage costs and query performance. The budgets are calibrated for a production environment serving approximately 1,000 requests per second across all services, with seasonal peaks of up to 5,000 RPS during promotional events.

| Signal | Collection Rate | Retention | Storage Estimate (per month) | Cost Optimization |
|--------|---------------|-----------|------------------------------|-------------------|
| Metrics | 100% | 90 days | ~500 MB | Cheap, keep all |
| Traces (errors) | 100% | 30 days | ~2 GB | Keep all errors |
| Traces (slow) | 100% (p99) | 30 days | ~1 GB | Keep slow traces |
| Traces (normal) | 10% (tail-sampled) | 7 days | ~500 MB | Sample successful fast traces |
| Logs (ERROR/FATAL) | 100% | 30 days | ~1 GB | Keep all errors |
| Logs (WARN) | 50% | 14 days | ~2 GB | Sample warnings |
| Logs (INFO) | 10% | 7 days | ~500 MB | Sample info logs |
| Logs (DEBUG) | 0% (production) | N/A | N/A | Disabled in production |

### Metrics Collection (100% / 90 days / ~500 MB)

Metrics are the most cost-efficient observability signal because they are pre-aggregated numeric values with fixed cardinality. Every service exports metrics at 100% collection rate with no sampling, because metrics are small (typically 8 bytes per data point) and provide the foundational data for dashboards, alerting, and capacity planning. The 90-day retention period supports quarterly trend analysis and capacity forecasting. Storage is estimated at 500 MB per month based on approximately 5,000 metric time series with 15-second scrape intervals. Cost optimization is inherent because metrics are already aggregated; no additional sampling or reduction is needed. Prometheus remote-write sends metrics to a long-term storage backend (Thanos or Cortex) for cost-effective retention beyond the local Prometheus window.

### Traces - Errors (100% / 30 days / ~2 GB)

Error traces capture every request that results in a 5xx status code, a timeout, or an unhandled exception. These traces are retained at 100% because they are essential for debugging production incidents, understanding failure modes, and measuring error budgets. The 30-day retention period aligns with the typical incident investigation window and the SLO error budget calculation period. Storage is estimated at 2 GB per month based on an assumed 0.5% error rate across all services, with each error trace averaging 50 KB (including all spans, attributes, and events). The OTel Collector tail-sampling processor ensures that all error traces are captured by evaluating the `http.status_code >= 500` or `error = true` span attributes before making the sampling decision.

### Traces - Slow (100% p99 / 30 days / ~1 GB)

Slow traces capture requests that exceed the p99 latency threshold for their respective service. These traces are critical for understanding tail latency, identifying performance regressions, and validating that latency SLOs are being met. The tail-sampling processor evaluates each trace's root span duration against the service-specific p99 threshold and retains traces that exceed it. The 30-day retention period supports monthly performance review cycles and regression detection. Storage is estimated at 1 GB per month because slow traces represent only 1% of total traffic, but each trace tends to be larger than average due to deeper call stacks and more detailed span attributes. The combination of error traces and slow traces ensures that all anomalous behavior is captured without the cost of retaining every routine request.

### Traces - Normal (10% tail-sampled / 7 days / ~500 MB)

Normal traces are successful, fast requests that represent the baseline behavior of the system. These are sampled at 10% using tail-based sampling, which makes the sampling decision after the complete trace is assembled rather than at the head of the request. Tail-based sampling is essential because head-based sampling would miss traces that start fast but encounter errors downstream. The 10% rate provides statistically significant data for baseline performance analysis while reducing storage by 90% compared to full collection. The 7-day retention period is sufficient for weekly performance reviews and short-term trend analysis. Storage is estimated at 500 MB per month based on 10% of approximately 900 successful fast requests per second, with each trace averaging 20 KB.

### Logs - ERROR/FATAL (100% / 30 days / ~1 GB)

Error and fatal logs are never sampled because they represent conditions that require immediate investigation and remediation. Every ERROR and FATAL log entry is collected, indexed, and retained for 30 days to support incident investigation, root cause analysis, and compliance requirements. The OTel Log Collector pipelines all ERROR/FATAL logs to a dedicated Loki or Elasticsearch index with high-priority retention policies. Storage is estimated at 1 GB per month based on an assumed error rate that produces approximately 10,000 error log entries per day across all services, with each entry averaging 3 KB including stack traces and context attributes.

### Logs - WARN (50% / 14 days / ~2 GB)

Warning logs indicate potential issues that do not immediately impact functionality but may signal developing problems. Sampling at 50% reduces storage volume while maintaining sufficient data for trend analysis and early issue detection. The 14-day retention period is shorter than errors because warnings rarely require long-term investigation. Sampling is performed at the OTel Collector level using a deterministic hash of the log's trace ID, ensuring that all logs belonging to the same trace are either all kept or all dropped. Storage is estimated at 2 GB per month because warnings are more frequent than errors (approximately 100,000 per day) but each entry is smaller (averaging 1.5 KB without full stack traces).

### Logs - INFO (10% / 7 days / ~500 MB)

Info-level logs capture routine operational events such as request processing, state transitions, and configuration changes. Sampling at 10% provides sufficient data for operational visibility and audit trails without the cost of retaining every informational message. The 7-day retention period supports short-term debugging and operational review. Sampling uses the same deterministic trace ID hash as WARN logs, maintaining trace consistency across log levels. Storage is estimated at 500 MB per month based on approximately 1 million info log entries per day, sampled to 100,000, with each entry averaging 500 bytes.

### Logs - DEBUG (0% production / N/A / N/A)

Debug logs are completely disabled in production environments. This is a hard rule enforced by the OTel Collector configuration, which drops all DEBUG-level log entries before they reach any processing pipeline. During development and staging, DEBUG logs are collected at 100% with 1-day retention to support local debugging. In production, if a specific issue requires debug-level detail, the on-call engineer can temporarily enable DEBUG logging for a specific service via a feature flag, which automatically reverts to disabled after 30 minutes. This approach prevents debug log accumulation while providing an escape hatch for critical investigations.

---

## 4. Resource Budgets per Service

Resource budgets define the CPU and memory requests and limits for each service in the Kubernetes cluster. Requests represent the guaranteed minimum resources available to a pod, while limits represent the maximum resources a pod can consume before being throttled (CPU) or killed (memory). The ratio between requests and limits provides burst capacity for handling traffic spikes while ensuring predictable scheduling. All budgets are defined in Kubernetes resource units: CPU in millicores (100m = 0.1 CPU core) and memory in mebibytes (Mi). Replica counts define the minimum number of pods running at all times, with Horizontal Pod Autoscalers (HPA) configured to scale up based on CPU utilization and request rate metrics.

| Service | CPU Request | CPU Limit | Memory Request | Memory Limit | Replicas |
|---------|------------|-----------|---------------|-------------|----------|
| Gateway | 100m | 500m | 128Mi | 512Mi | 3 |
| Identity | 100m | 300m | 256Mi | 512Mi | 2 |
| Catalog | 200m | 1000m | 256Mi | 1Gi | 3 |
| Order | 500m | 2000m | 512Mi | 2Gi | 3 |
| Payment | 200m | 1000m | 256Mi | 1Gi | 2 |
| Notification | 100m | 500m | 256Mi | 512Mi | 2 |
| Analytics | 500m | 2000m | 1Gi | 4Gi | 2 |
| CDC Relay | 500m | 2000m | 1Gi | 4Gi | 1 |
| Analytics | 500m | 2000m | 1Gi | 4Gi | 2 |
| Schema Registry | 100m | 300m | 128Mi | 256Mi | 2 |

### Gateway (100m/500m CPU, 128Mi/512Mi Memory, 3 Replicas)

The Gateway has the lowest resource budget because it performs no business logic, no database queries, and no complex computation. Its primary functions are request routing, header transformation, rate limiting, and authentication token validation, all of which are I/O-bound operations that require minimal CPU and memory. The 100m CPU request is sufficient for idle state, while the 500m limit provides 5x burst capacity for traffic spikes. Memory is set conservatively at 128Mi request and 512Mi limit because the Gateway maintains minimal state: route tables, rate limit counters, and connection metadata. Three replicas ensure high availability across three availability zones and provide enough capacity to handle one replica failure without degrading performance. The HPA scales based on CPU utilization (target: 70%) and request rate (target: 1000 RPS per pod).

### Identity (100m/300m CPU, 256Mi/512Mi Memory, 2 Replicas)

The Identity service has a modest resource budget because SPIRE SVID operations are cryptographic computations that are fast but memory-intensive when handling multiple concurrent verification requests. The 256Mi memory request accounts for the SPIRE agent cache, trust bundle storage, and JWT validation state. Two replicas provide redundancy while keeping costs low, since Identity is rarely a bottleneck. The CPU limit of 300m is sufficient because cryptographic operations are brief spikes rather than sustained loads. If the Identity service becomes a bottleneck during a pod restart or trust bundle rotation event, the HPA will scale to a maximum of 4 replicas based on CPU utilization exceeding 80%.

### Catalog (200m/1000m CPU, 256Mi/1Gi Memory, 3 Replicas)

The Catalog service requires moderate CPU for query parsing, filtering, and result serialization, plus significant memory for caching popular queries and product data. The 256Mi memory request covers the baseline working set including connection pools, prepared statement caches, and the top-100 query result cache. The 1Gi limit allows for cache expansion during traffic peaks when more queries need to be cached. Three replicas provide read scalability and fault tolerance. The large CPU burst ratio (5x) accommodates occasional complex search queries that require significant computation. The HPA scales based on both CPU utilization and the `catalog.query_queue_depth` metric, adding replicas when the query backlog exceeds 50 pending requests.

### Order (500m/2000m CPU, 512Mi/2Gi Memory, 3 Replicas)

The Order service has the highest resource budget among application services because saga orchestration is both CPU and memory intensive. Each in-flight saga requires the service to maintain state for all steps, track timeouts, and handle compensation logic. The 512Mi memory request covers the baseline saga state machine, database connection pool, and Outbox event buffer. The 2Gi limit provides headroom for high-order-volume periods when many sagas are in-flight simultaneously. The 500m CPU request is the highest among services because saga orchestration involves sequential service calls, state transitions, and event publishing. Three replicas are required for both availability and to distribute saga load. The HPA scales aggressively based on `order.active_sagas` count, adding replicas when more than 100 sagas are active per pod.

### Payment (200m/1000m CPU, 256Mi/1Gi Memory, 2 Replicas)

The Payment service's resource budget is moderate because most of the processing time is spent waiting for external payment gateway responses rather than performing local computation. The 256Mi memory request covers the circuit breaker state, payment token cache, and retry queue. The 1Gi limit accommodates burst scenarios where many payment requests are queued while the circuit breaker is in the half-open state. Two replicas provide redundancy without over-provisioning, since payment processing is rate-limited by the external gateway's throughput capacity. The HPA scales based on `payment.queue_depth` and `payment.circuit_breaker_state`, adding replicas only when the circuit breaker opens and a queue backlog develops.

### Notification (100m/500m CPU, 256Mi/512Mi Memory, 2 Replicas)

The Notification service is primarily asynchronous and event-driven, which keeps its resource requirements low. The 256Mi memory request covers the template cache, recipient deduplication index, and delivery queue. The 512Mi limit is tight because notification processing does not require large in-memory data structures. The CPU budget is modest at 100m request and 500m limit, reflecting the lightweight nature of template rendering and queue writes. Two replicas ensure that notification processing continues during pod restarts. The HPA scales based on `notification.queue_depth`, adding replicas when the backlog exceeds 1,000 pending notifications.

### Analytics (500m/2000m CPU, 1Gi/4Gi Memory, 2 Replicas)

The Analytics service has one of the highest resource budgets because time-series query processing and aggregation pipelines are both compute and memory intensive. Large aggregation queries can consume significant CPU for sorting and grouping operations, while intermediate results and materialized view caches require substantial memory. The 1Gi memory request covers the query execution engine, connection pool, and materialized view cache. The 4Gi limit provides headroom for complex ad-hoc queries that build large intermediate result sets. Two replicas balance cost against availability, since Analytics is typically not on the critical path for user-facing requests. The HPA scales based on `analytics.active_queries` and CPU utilization, with a maximum of 4 replicas during reporting periods.

### CDC Relay (500m/2000m CPU, 1Gi/4Gi Memory, 1 Replica)

The CDC Relay (Debezium connectors) has a high resource budget because change data capture involves continuous database log reading, event transformation, and Kafka production. The 1Gi memory request covers the Debezium connector's in-memory event buffer, snapshot state, and Kafka producer buffer. The 4Gi limit provides headroom for large transaction events and connector restart recovery, which requires re-reading recent log entries. A single replica is specified because Debezium connectors maintain their own offset management and cannot run concurrently on the same connector. High availability is achieved through Kubernetes pod restart policies and standby connector configurations. If the CDC Relay pod fails, Kubernetes restarts it within 30 seconds, and the connector resumes from the last committed offset.

### Schema Registry (100m/300m CPU, 128Mi/256Mi Memory, 2 Replicas)

The Schema Registry has the lowest resource budget because schema operations are lightweight in-memory lookups that rarely require significant CPU or memory. The 128Mi memory request covers the in-memory schema cache, which typically holds fewer than 1,000 schemas totaling less than 10 MB. The 256Mi limit provides headroom for schema version history and compatibility check results. Two replicas provide redundancy for this critical infrastructure component, since all services depend on the Schema Registry for serialization and deserialization. The HPA is not configured for the Schema Registry because its load is predictable and scales with schema changes rather than request volume.

---

## 5. Performance Regression Detection

Performance regression detection is the systematic process of identifying when a system's latency, throughput, or resource utilization degrades beyond acceptable thresholds. This section defines the tooling, processes, and escalation procedures that ensure performance regressions are detected quickly, investigated thoroughly, and resolved before they impact users. The detection system operates at three levels: real-time production monitoring, CI benchmark comparison, and periodic chaos engineering validation.

### OTel Metrics to Prometheus Pipeline

All services export OTel metrics to the OTel Collector DaemonSet, which forwards them to the OTel Collector Gateway, which in turn writes them to Prometheus via remote-write. This pipeline ensures that every service emits consistent, structured metrics including request duration histograms (with p50/p95/p99 labels), error rate counters, and resource utilization gauges. Prometheus scrapes the OTel Collector Gateway at 15-second intervals, providing near-real-time visibility into service health. Recording rules pre-compute commonly queried percentiles to reduce query load on the Prometheus server during dashboard rendering.

### Grafana Dashboards with Percentile Panels

Each service has a dedicated Grafana dashboard displaying p50, p95, and p99 latency as line charts over configurable time windows (5 minutes, 1 hour, 24 hours, 7 days). Dashboards include overlay panels showing deployment events, configuration changes, and traffic shifts to help correlate latency spikes with their root causes. A global "Service Health Overview" dashboard aggregates the p99 of all services onto a single panel with traffic-light coloring: green (within budget), yellow (within 1.5x budget), and red (exceeding 2x budget). This dashboard is displayed on the team's status monitor and reviewed during daily standups.

### Automated Alerting with PagerDuty Integration

Alerting rules are defined in Prometheus AlertManager with the following escalation policy. When a service's p99 latency exceeds 2x its target for two consecutive evaluation windows of 60 seconds, a PagerDuty alert is triggered and assigned to the on-call engineer for that service. The alert includes the current p99 value, the target threshold, the duration of the breach, and a link to the relevant Grafana dashboard. If the alert is not acknowledged within 15 minutes, it escalates to the secondary on-call and the engineering manager. If the breach persists for more than 30 minutes, it escalates to the VP of Engineering. All alerts are tracked in a post-incident review log that feeds back into budget refinements.

### CI Benchmark Comparison

The `/benchmark` gstack skill runs in CI on every merge to the main branch and on a nightly schedule. It executes a standardized load test against the staging environment, collecting p50/p95/p99 latency metrics for all services. The results are compared against a baseline recorded in the previous successful benchmark run. If any service's p99 latency regresses by more than 20% compared to the baseline, the CI pipeline fails and blocks the merge. This 20% threshold was chosen because it is large enough to avoid false positives from normal variance but small enough to catch meaningful regressions before they compound. Benchmark results are stored in a time-series database for trend analysis and quarterly performance reviews.

### Chaos Engineering Game Day (Phase 6)

Chaos Engineering validation occurs during Phase 6 of the project lifecycle, where controlled failure injection tests the system's behavior under adverse conditions. Game Day exercises include simulating network latency spikes (200ms added to inter-service calls), pod kills (removing random replicas), CPU stress (consuming 80% of a service's CPU limit), and dependency outages (blocking the Payment gateway). During each exercise, the performance monitoring system is observed to verify that alerts fire within the expected time windows, circuit breakers activate correctly, and fallback behaviors maintain acceptable latency. The results of Game Day exercises are documented and used to refine latency targets, resource budgets, and alerting thresholds for the next operational cycle.

---

## Appendix: OTel Measurement and Alerting Summary

| Service | Span Name | Alert Metric | Alert Threshold | Escalation |
|---------|-----------|-------------|-----------------|------------|
| Gateway | `gateway.request` | `gateway.request_duration_p99` | >100ms (2x) | PagerDuty |
| Identity | `identity.verify` | `identity.verify_duration_p99` | >200ms (2x) | PagerDuty |
| Catalog | `catalog.search` | `catalog.search_duration_p99` | >400ms (2x) | PagerDuty |
| Order | `order.create` | `order.create_duration_p99` | >600ms (2x) | PagerDuty |
| Payment | `payment.process` | `payment.process_duration_p99` | >1000ms (2x) | PagerDuty |
| Notification | `notification.accept` | `notification.accept_duration_p99` | >300ms (2x) | Slack |
| Analytics | `analytics.query` | `analytics.query_duration_p99` | >1000ms (2x) | Slack |
| CDC Relay | `cdc.relay` | `cdc.source_lag_p99` | >5000ms | PagerDuty |
| Schema Registry | `schema.lookup` | `schema.lookup_duration_p99` | >200ms (2x) | Slack |
