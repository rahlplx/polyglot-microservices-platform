/**
 * Configuration Module
 *
 * Reads configuration from environment variables with sensible defaults.
 * All config values are validated at startup time.
 * Supports feature flags for gradual rollout.
 */

import { z, type ZodError } from 'zod';

// ---------------------------------------------------------------------------
// Configuration Schemas
// ---------------------------------------------------------------------------

const ServerConfigSchema = z.object({
  httpPort: z.number().int().min(1).max(65535).default(3000),
  grpcPort: z.number().int().min(1).max(65535).default(50053),
  shutdownTimeoutMs: z.number().int().positive().default(15000),
});

const DatabaseConfigSchema = z.object({
  host: z.string().min(1).default('localhost'),
  port: z.number().int().min(1).max(65535).default(5432),
  database: z.string().min(1).default('catalog'),
  user: z.string().min(1).default('catalog'),
  // SECURITY: The database password MUST be provided via the CATALOG_DB_PASSWORD
  // environment variable. No default is provided to prevent hardcoded credentials
  // from leaking into source control.
  password: z.string().min(1),
  maxPoolSize: z.number().int().positive().default(20),
  idleTimeoutMs: z.number().int().positive().default(30000),
  connectionTimeoutMs: z.number().int().positive().default(5000),
  sslEnabled: z.boolean().default(false),
});

const MeilisearchConfigSchema = z.object({
  host: z.string().min(1).default('http://localhost:7700'),
  // SECURITY: The Meilisearch API key MUST be provided via the CATALOG_MEILISEARCH_API_KEY
  // environment variable. No default is provided to prevent hardcoded secrets
  // from leaking into source control.
  apiKey: z.string().min(1),
  indexName: z.string().min(1).default('products'),
});

const OtelConfigSchema = z.object({
  enabled: z.boolean().default(true),
  serviceName: z.string().min(1).default('catalog'),
  serviceVersion: z.string().min(1).default('0.1.0'),
  otlpEndpoint: z.string().min(1).default('http://localhost:4317'),
  traceEnabled: z.boolean().default(true),
  metricsEnabled: z.boolean().default(true),
  sampleRate: z.number().min(0).max(1).default(0.1),
  exportIntervalMs: z.number().int().positive().default(15000),
  exportTimeoutMs: z.number().int().positive().default(5000),
});

const SpiffeConfigSchema = z.object({
  enabled: z.boolean().default(false),
  trustDomain: z.string().min(1).default('example.org'),
  workloadApiAddr: z.string().min(1).default('unix:///tmp/spire-agent/public/api.sock'),
  svidTtlSeconds: z.number().int().positive().default(3600),
});

const FeatureFlagsSchema = z.object({
  enableSearch: z.boolean().default(true),
  enableSoftDelete: z.boolean().default(true),
  enableInventoryTracking: z.boolean().default(true),
  enableFallbackSearch: z.boolean().default(true),
});

const AppConfigSchema = z.object({
  env: z.enum(['development', 'staging', 'production', 'test']).default('development'),
  server: ServerConfigSchema,
  database: DatabaseConfigSchema,
  meilisearch: MeilisearchConfigSchema,
  otel: OtelConfigSchema,
  spiffe: SpiffeConfigSchema,
  features: FeatureFlagsSchema,
});

// ---------------------------------------------------------------------------
// Derived Types
// ---------------------------------------------------------------------------

export type AppConfig = z.infer<typeof AppConfigSchema>;
export type ServerConfig = z.infer<typeof ServerConfigSchema>;
export type DatabaseConfig = z.infer<typeof DatabaseConfigSchema>;
export type MeilisearchConfigType = z.infer<typeof MeilisearchConfigSchema>;
export type OtelConfigType = z.infer<typeof OtelConfigSchema>;
export type SpiffeConfigType = z.infer<typeof SpiffeConfigSchema>;
export type FeatureFlags = z.infer<typeof FeatureFlagsSchema>;

// ---------------------------------------------------------------------------
// Environment Variable Parsing Helpers
// ---------------------------------------------------------------------------

function envString(key: string, defaultValue: string): string {
  const value = process.env[key];
  return value !== undefined && value !== '' ? value : defaultValue;
}

function envInt(key: string, defaultValue: number): number {
  const value = process.env[key];
  if (value !== undefined && value !== '') {
    const parsed = parseInt(value, 10);
    if (!isNaN(parsed)) {
      return parsed;
    }
  }
  return defaultValue;
}

function envBool(key: string, defaultValue: boolean): boolean {
  const value = process.env[key];
  if (value !== undefined && value !== '') {
    return value === 'true' || value === '1';
  }
  return defaultValue;
}

function envFloat(key: string, defaultValue: number): number {
  const value = process.env[key];
  if (value !== undefined && value !== '') {
    const parsed = parseFloat(value);
    if (!isNaN(parsed)) {
      return parsed;
    }
  }
  return defaultValue;
}

// ---------------------------------------------------------------------------
// Load Configuration
// ---------------------------------------------------------------------------

export function loadConfig(): AppConfig {
  const rawConfig: AppConfig = {
    env: envString('NODE_ENV', 'development') as AppConfig['env'],
    server: {
      httpPort: envInt('CATALOG_HTTP_PORT', 3000),
      grpcPort: envInt('CATALOG_GRPC_PORT', 50053),
      shutdownTimeoutMs: envInt('CATALOG_SHUTDOWN_TIMEOUT_MS', 15000),
    },
    database: {
      host: envString('CATALOG_DB_HOST', 'localhost'),
      port: envInt('CATALOG_DB_PORT', 5432),
      database: envString('CATALOG_DB_NAME', 'catalog'),
      user: envString('CATALOG_DB_USER', 'catalog'),
      // SECURITY: No default password — must be set via CATALOG_DB_PASSWORD env var
      password: envString('CATALOG_DB_PASSWORD', ''),
      maxPoolSize: envInt('CATALOG_DB_POOL_SIZE', 20),
      idleTimeoutMs: envInt('CATALOG_DB_IDLE_TIMEOUT_MS', 30000),
      connectionTimeoutMs: envInt('CATALOG_DB_CONNECT_TIMEOUT_MS', 5000),
      sslEnabled: envBool('CATALOG_DB_SSL', false),
    },
    meilisearch: {
      host: envString('CATALOG_MEILISEARCH_HOST', 'http://localhost:7700'),
      // SECURITY: No default API key — must be set via CATALOG_MEILISEARCH_API_KEY env var
      apiKey: envString('CATALOG_MEILISEARCH_API_KEY', ''),
      indexName: envString('CATALOG_MEILISEARCH_INDEX', 'products'),
    },
    otel: {
      enabled: envBool('CATALOG_OTEL_ENABLED', true),
      serviceName: envString('CATALOG_OTEL_SERVICE_NAME', 'catalog'),
      serviceVersion: envString('CATALOG_OTEL_SERVICE_VERSION', '0.1.0'),
      otlpEndpoint: envString('CATALOG_OTEL_ENDPOINT', 'http://localhost:4317'),
      traceEnabled: envBool('CATALOG_OTEL_TRACE_ENABLED', true),
      metricsEnabled: envBool('CATALOG_OTEL_METRICS_ENABLED', true),
      sampleRate: envFloat('CATALOG_OTEL_SAMPLE_RATE', 0.1),
      exportIntervalMs: envInt('CATALOG_OTEL_EXPORT_INTERVAL_MS', 15000),
      exportTimeoutMs: envInt('CATALOG_OTEL_EXPORT_TIMEOUT_MS', 5000),
    },
    spiffe: {
      enabled: envBool('CATALOG_SPIFFE_ENABLED', false),
      trustDomain: envString('CATALOG_SPIFFE_TRUST_DOMAIN', 'example.org'),
      workloadApiAddr: envString('CATALOG_SPIFFE_WORKLOAD_API', 'unix:///tmp/spire-agent/public/api.sock'),
      svidTtlSeconds: envInt('CATALOG_SPIFFE_SVID_TTL', 3600),
    },
    features: {
      enableSearch: envBool('CATALOG_FEATURE_SEARCH', true),
      enableSoftDelete: envBool('CATALOG_FEATURE_SOFT_DELETE', true),
      enableInventoryTracking: envBool('CATALOG_FEATURE_INVENTORY', true),
      enableFallbackSearch: envBool('CATALOG_FEATURE_FALLBACK_SEARCH', true),
    },
  };

  return validateConfig(rawConfig);
}

function validateConfig(config: AppConfig): AppConfig {
  // SECURITY: Check for missing credentials before schema validation so we can
  // produce a clear, actionable error message instead of a generic Zod error.
  const missingCredentials: string[] = [];
  if (!config.database.password) {
    missingCredentials.push(
      'database.password — set CATALOG_DB_PASSWORD environment variable'
    );
  }
  if (!config.meilisearch.apiKey) {
    missingCredentials.push(
      'meilisearch.apiKey — set CATALOG_MEILISEARCH_API_KEY environment variable'
    );
  }
  if (missingCredentials.length > 0) {
    throw new Error(
      `Missing required credentials. The following MUST be provided via environment variables:\n${missingCredentials.map((m) => `  - ${m}`).join('\n')}`
    );
  }

  try {
    return AppConfigSchema.parse(config);
  } catch (error) {
    const zodError = error as ZodError;
    const issues = zodError.errors.map(
      (e) => `  - ${e.path.join('.')}: ${e.message}`
    );
    throw new Error(
      `Configuration validation failed:\n${issues.join('\n')}`
    );
  }
}

// ---------------------------------------------------------------------------
// Log Configuration (for startup diagnostics)
// ---------------------------------------------------------------------------

export function logConfigSummary(config: AppConfig): Record<string, unknown> {
  return {
    env: config.env,
    httpPort: config.server.httpPort,
    grpcPort: config.server.grpcPort,
    dbHost: config.database.host,
    dbPort: config.database.port,
    dbName: config.database.database,
    dbSsl: config.database.sslEnabled,
    meilisearchHost: config.meilisearch.host,
    otelEnabled: config.otel.enabled,
    otelEndpoint: config.otel.otlpEndpoint,
    spiffeEnabled: config.spiffe.enabled,
    features: config.features,
  };
}
