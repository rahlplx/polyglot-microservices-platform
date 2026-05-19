/**
 * OpenTelemetry Observability Adapter
 *
 * Implements OTel instrumentation for the Catalog service using
 * @opentelemetry/api and @opentelemetry/sdk-node. Provides tracing,
 * metrics, and structured logging with trace context injection.
 */
import type { Tracer, Span, Attributes, Counter, Histogram } from '@opentelemetry/api';
import { trace, metrics, context, propagation, SpanStatusCode, SpanKind } from '@opentelemetry/api';
import type { NodeSDK } from '@opentelemetry/sdk-node';
import pino, { type Logger } from 'pino';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export interface OtelConfig {
  readonly serviceName: string;
  readonly serviceVersion: string;
  readonly otlpEndpoint: string;
  readonly enabled: boolean;
  readonly traceEnabled: boolean;
  readonly metricsEnabled: boolean;
  readonly sampleRate: number;
}

// ---------------------------------------------------------------------------
// OTel Adapter
// ---------------------------------------------------------------------------

export class OtelAdapter {
  private readonly logger: Logger;
  private readonly serviceName: string;
  private sdk: NodeSDK | null = null;

  // Metrics
  private crudCounter: Counter | null = null;
  private searchDurationHistogram: Histogram | null = null;
  private inventoryUpdateCounter: Counter | null = null;

  constructor(config: OtelConfig) {
    this.serviceName = config.serviceName;

    this.logger = pino({
      name: config.serviceName,
      level: process.env.LOG_LEVEL ?? 'info',
      formatters: {
        level(label: string) {
          return { level: label };
        },
        log(object: Record<string, unknown>) {
          // Inject trace context into log entries for correlation
          const span = trace.getActiveSpan();
          if (span) {
            const ctx = span.spanContext();
            return {
              ...object,
              trace_id: ctx.traceId,
              span_id: ctx.spanId,
            };
          }
          return object;
        },
      },
    });

    if (config.enabled) {
      this.initializeMetrics();
    }
  }

  // -------------------------------------------------------------------------
  // Initialization
  // -------------------------------------------------------------------------

  async initialize(config: OtelConfig): Promise<void> {
    if (!config.enabled) {
      this.logger.info('OpenTelemetry is disabled');
      return;
    }

    try {
      // Dynamic import to avoid loading OTel SDK when disabled
      const { NodeSDK } = await import('@opentelemetry/sdk-node');
      const { OTLPTraceExporter } = await import('@opentelemetry/exporter-trace-otlp-grpc');
      const { OTLPMetricExporter } = await import('@opentelemetry/exporter-metrics-otlp-grpc');
      const { PeriodicExportingMetricReader } = await import('@opentelemetry/sdk-metrics');
      const { Resource } = await import('@opentelemetry/resources');
      const { SEMRESATTRS_SERVICE_NAME, SEMRESATTRS_SERVICE_VERSION } = await import('@opentelemetry/semantic-conventions');

      const traceExporter = config.traceEnabled
        ? new OTLPTraceExporter({ url: config.otlpEndpoint })
        : undefined;

      const metricReader = config.metricsEnabled
        ? new PeriodicExportingMetricReader({
            exporter: new OTLPMetricExporter({ url: config.otlpEndpoint }),
            exportIntervalMillis: 15000,
            exportTimeoutMillis: 5000,
          })
        : undefined;

      const resource = new Resource({
        [SEMRESATTRS_SERVICE_NAME]: config.serviceName,
        [SEMRESATTRS_SERVICE_VERSION]: config.serviceVersion,
      });

      const sdkConfig: Record<string, unknown> = {
        resource,
        traceExporter,
        instrumentations: [],
      };

      if (metricReader) {
        // Type assertion needed due to conflicting @opentelemetry/sdk-metrics versions
        // between @opentelemetry/sdk-node and direct dependency
        sdkConfig.metricReader = metricReader;
      }

      this.sdk = new NodeSDK(sdkConfig);

      this.sdk.start();
      this.logger.info({ otlpEndpoint: config.otlpEndpoint }, 'OpenTelemetry SDK initialized');
    } catch (error) {
      this.logger.error(
        { error: error instanceof Error ? error.message : String(error) },
        'Failed to initialize OpenTelemetry SDK'
      );
    }
  }

  // -------------------------------------------------------------------------
  // Tracing
  // -------------------------------------------------------------------------

  getTracer(): Tracer {
    return trace.getTracer(this.serviceName, '0.1.0');
  }

  startSpan(
    name: string,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes?: Attributes
  ): Span {
    const tracer = this.getTracer();
    return tracer.startSpan(name, { kind, attributes });
  }

  endSpan(span: Span, error?: Error): void {
    if (error) {
      span.setStatus({ code: SpanStatusCode.ERROR, message: error.message });
      span.recordException(error);
    }
    span.end();
  }

  // -------------------------------------------------------------------------
  // Metrics
  // -------------------------------------------------------------------------

  private initializeMetrics(): void {
    const meter = metrics.getMeter(this.serviceName, '0.1.0');

    this.crudCounter = meter.createCounter('catalog.crud.operations_total', {
      description: 'Total number of CRUD operations on the catalog',
    });

    this.searchDurationHistogram = meter.createHistogram('catalog.search.duration', {
      description: 'Duration of search operations in milliseconds',
      unit: 'ms',
    });

    this.inventoryUpdateCounter = meter.createCounter('catalog.inventory.updates_total', {
      description: 'Total number of inventory update operations',
    });
  }

  recordCrudOperation(operation: string, result: string): void {
    this.crudCounter?.add(1, { operation, result });
  }

  recordSearchDuration(queryType: string, resultCount: number, durationMs: number): void {
    this.searchDurationHistogram?.record(durationMs, {
      query_type: queryType,
      result_count: String(resultCount),
    });
  }

  recordInventoryUpdate(reason: string): void {
    this.inventoryUpdateCounter?.add(1, { reason });
  }

  // -------------------------------------------------------------------------
  // Propagation
  // -------------------------------------------------------------------------

  injectTraceContext(carrier: Record<string, string>): void {
    propagation.inject(context.active(), carrier);
  }

  // -------------------------------------------------------------------------
  // Logging
  // -------------------------------------------------------------------------

  getLogger(): Logger {
    return this.logger;
  }

  // -------------------------------------------------------------------------
  // Shutdown
  // -------------------------------------------------------------------------

  async shutdown(): Promise<void> {
    if (this.sdk) {
      try {
        await this.sdk.shutdown();
        this.logger.info('OpenTelemetry SDK shut down successfully');
      } catch (error) {
        this.logger.error(
          { error: error instanceof Error ? error.message : String(error) },
          'Error shutting down OpenTelemetry SDK'
        );
      }
    }
  }
}
