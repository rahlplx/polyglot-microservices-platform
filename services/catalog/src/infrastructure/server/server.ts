/**
 * Combined gRPC + HTTP Server
 *
 * Manages the lifecycle of both gRPC and HTTP servers,
 * including graceful startup and shutdown with signal handling.
 */

import type { AppContainer } from '../di/container';
import { logConfigSummary } from '../config/config';
import type { AppConfig } from '../config/config';

// ---------------------------------------------------------------------------
// Server Lifecycle
// ---------------------------------------------------------------------------

export async function startServer(container: AppContainer, config: AppConfig): Promise<void> {
  const logger = container.otel.getLogger();

  // Log startup configuration
  logger.info(logConfigSummary(config), 'Starting Catalog service');

  // Start SPIFFE identity (non-fatal if it fails)
  if (config.spiffe.enabled) {
    try {
      await container.spiffe.start();
      logger.info({ spiffeId: container.spiffe.getSpiffeId() }, 'SPIFFE identity started');
    } catch (error) {
      logger.warn(
        { error: error instanceof Error ? error.message : String(error) },
        'SPIFFE identity failed to start, continuing without mTLS'
      );
    }
  }

  // Verify database connectivity
  const dbHealthy = await container.productRepository.ping();
  if (dbHealthy) {
    logger.info('Database connection verified');
  } else {
    logger.warn('Database connection failed — service may be degraded');
  }

  // Start gRPC server
  try {
    await container.grpcHandler.start();
  } catch (error) {
    logger.error(
      { error: error instanceof Error ? error.message : String(error) },
      'Failed to start gRPC server'
    );
    throw error;
  }

  // Start HTTP/REST server
  try {
    await container.restController.start();
  } catch (error) {
    logger.error(
      { error: error instanceof Error ? error.message : String(error) },
      'Failed to start HTTP server'
    );
    throw error;
  }

  logger.info(
    {
      httpPort: config.server.httpPort,
      grpcPort: config.server.grpcPort,
      spiffeEnabled: config.spiffe.enabled,
      otelEnabled: config.otel.enabled,
    },
    'Catalog service started successfully'
  );
}

export async function stopServer(container: AppContainer): Promise<void> {
  const logger = container.otel.getLogger();
  logger.info('Stopping Catalog service...');
  // The actual shutdown is handled by the DI container's shutdownContainer
  // This function is a convenience wrapper for the server layer
}
