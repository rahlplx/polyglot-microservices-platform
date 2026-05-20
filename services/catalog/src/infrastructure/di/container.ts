/**
 * Dependency Injection Container
 *
 * Wires all adapters to the domain service. This is the composition root
 * where all dependencies are assembled following hexagonal architecture.
 * The domain core remains completely unaware of adapter implementations.
 */

import { v4 as uuidv4 } from 'uuid';
import { CatalogService } from '../../domain/services/CatalogService';
import { PostgresProductRepo } from '../../adapters/outbound/persistence/PostgresProductRepo';
import { MeilisearchAdapter } from '../../adapters/outbound/search/MeilisearchAdapter';
import { OtelAdapter } from '../../adapters/outbound/observability/OtelAdapter';
import { SpiffeAdapter } from '../../adapters/outbound/identity/SpiffeAdapter';
import { CatalogGrpcHandler } from '../../adapters/inbound/grpc/CatalogGrpcHandler';
import { CatalogController } from '../../adapters/inbound/rest/CatalogController';
import type { AppConfig } from '../config/config';

// ---------------------------------------------------------------------------
// Container Types
// ---------------------------------------------------------------------------

export interface AppContainer {
  readonly catalogService: CatalogService;
  readonly productRepository: PostgresProductRepo;
  readonly searchIndex: MeilisearchAdapter;
  readonly otel: OtelAdapter;
  readonly spiffe: SpiffeAdapter;
  readonly grpcHandler: CatalogGrpcHandler;
  readonly restController: CatalogController;
}

// ---------------------------------------------------------------------------
// Container Initialization
// ---------------------------------------------------------------------------

export async function createContainer(config: AppConfig): Promise<AppContainer> {
  // 1. Initialize observability first (needed by all other components)
  const otel = new OtelAdapter({
    serviceName: config.otel.serviceName,
    serviceVersion: config.otel.serviceVersion,
    otlpEndpoint: config.otel.otlpEndpoint,
    enabled: config.otel.enabled,
    traceEnabled: config.otel.traceEnabled,
    metricsEnabled: config.otel.metricsEnabled,
    sampleRate: config.otel.sampleRate,
  });
  await otel.initialize({
    serviceName: config.otel.serviceName,
    serviceVersion: config.otel.serviceVersion,
    otlpEndpoint: config.otel.otlpEndpoint,
    enabled: config.otel.enabled,
    traceEnabled: config.otel.traceEnabled,
    metricsEnabled: config.otel.metricsEnabled,
    sampleRate: config.otel.sampleRate,
  });

  const logger = otel.getLogger();

  // 2. Initialize outbound adapters (driven ports)
  logger.info('Initializing outbound adapters...');

  const productRepository = new PostgresProductRepo({
    host: config.database.host,
    port: config.database.port,
    database: config.database.database,
    user: config.database.user,
    password: config.database.password,
    max: config.database.maxPoolSize,
    idleTimeoutMillis: config.database.idleTimeoutMs,
    connectionTimeoutMillis: config.database.connectionTimeoutMs,
    ssl: config.database.sslEnabled ? { rejectUnauthorized: true } : undefined,
  });

  // Initialize database schema
  try {
    await productRepository.initializeSchema();
    logger.info('Database schema initialized');
  } catch (error) {
    logger.warn(
      { error: error instanceof Error ? error.message : String(error) },
      'Database schema initialization failed (may already exist)'
    );
  }

  const searchIndex = new MeilisearchAdapter({
    host: config.meilisearch.host,
    apiKey: config.meilisearch.apiKey,
    indexName: config.meilisearch.indexName,
  });

  // 3. Initialize SPIFFE identity adapter
  const spiffe = new SpiffeAdapter({
    enabled: config.spiffe.enabled,
    trustDomain: config.spiffe.trustDomain,
    workloadApiAddr: config.spiffe.workloadApiAddr,
    svidTtlSeconds: config.spiffe.svidTtlSeconds,
  });

  // 4. Wire domain service (inject outbound ports)
  logger.info('Initializing domain service...');

  const catalogService = new CatalogService({
    productRepository,
    searchIndex: config.features.enableSearch
      ? searchIndex
      : createNoOpSearchIndex(),
    generateId: () => uuidv4(),
  });

  // 5. Initialize inbound adapters (driving ports)
  logger.info('Initializing inbound adapters...');

  const protoPath = config.server.protoPath ?? 'catalog/v1/catalog.proto';

  const grpcHandler = new CatalogGrpcHandler(
    catalogService,
    otel,
    config.server.grpcPort,
    protoPath
  );

  const restController = new CatalogController(
    catalogService,
    otel,
    config.server.httpPort
  );

  logger.info('DI container initialized successfully');

  return {
    catalogService,
    productRepository,
    searchIndex,
    otel,
    spiffe,
    grpcHandler,
    restController,
  };
}

// ---------------------------------------------------------------------------
// No-Op Search Index (when search is disabled)
// ---------------------------------------------------------------------------

function createNoOpSearchIndex(): import('../../domain/ports/outbound/SearchIndex').SearchIndex {
  return {
    async index() { /* no-op */ },
    async bulkIndex() { /* no-op */ },
    async search() {
      return {
        results: [],
        totalCount: 0,
        nextPageToken: '',
        facets: {},
        suggestions: [],
      };
    },
    async delete() { /* no-op */ },
    async refresh() { /* no-op */ },
    async suggest() { return []; },
  };
}

// ---------------------------------------------------------------------------
// Container Shutdown
// ---------------------------------------------------------------------------

export async function shutdownContainer(container: AppContainer): Promise<void> {
  const logger = container.otel.getLogger();
  logger.info('Shutting down DI container...');

  // Stop inbound adapters first (stop accepting new requests)
  try {
    await container.grpcHandler.stop();
  } catch (error) {
    logger.warn({ error: error instanceof Error ? error.message : String(error) }, 'gRPC handler shutdown error');
  }

  try {
    await container.restController.stop();
  } catch (error) {
    logger.warn({ error: error instanceof Error ? error.message : String(error) }, 'REST controller shutdown error');
  }

  // Stop SPIFFE identity
  try {
    await container.spiffe.stop();
  } catch (error) {
    logger.warn({ error: error instanceof Error ? error.message : String(error) }, 'SPIFFE shutdown error');
  }

  // Close outbound connections
  try {
    await container.productRepository.close();
  } catch (error) {
    logger.warn({ error: error instanceof Error ? error.message : String(error) }, 'Database connection close error');
  }

  // Shutdown observability last
  try {
    await container.otel.shutdown();
  } catch (error) {
    logger.warn({ error: error instanceof Error ? error.message : String(error) }, 'OTel shutdown error');
  }

  logger.info('DI container shut down');
}
