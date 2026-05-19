/**
 * Catalog Service - Entry Point
 *
 * Initializes configuration, dependency injection, and starts
 * the combined gRPC + HTTP server with graceful shutdown.
 */

import { loadConfig } from './infrastructure/config/config';
import { createContainer, shutdownContainer } from './infrastructure/di/container';
import { startServer } from './infrastructure/server/server';

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  // 1. Load configuration from environment
  const config = loadConfig();

  // 2. Create DI container (wires all adapters to domain service)
  const container = await createContainer(config);

  // 3. Set up graceful shutdown
  const shutdownSignals = ['SIGINT', 'SIGTERM', 'SIGQUIT'] as const;
  let isShuttingDown = false;

  const gracefulShutdown = async (signal: string): Promise<void> => {
    if (isShuttingDown) {
      return;
    }
    isShuttingDown = true;

    container.otel.getLogger().info({ signal }, 'Received shutdown signal');

    const shutdownTimeout = setTimeout(() => {
      container.otel.getLogger().error('Graceful shutdown timed out, forcing exit');
      process.exit(1);
    }, config.server.shutdownTimeoutMs);

    try {
      await shutdownContainer(container);
      clearTimeout(shutdownTimeout);
      container.otel.getLogger().info('Catalog service stopped gracefully');
      process.exit(0);
    } catch (error) {
      clearTimeout(shutdownTimeout);
      container.otel.getLogger().error(
        { error: error instanceof Error ? error.message : String(error) },
        'Error during graceful shutdown'
      );
      process.exit(1);
    }
  };

  for (const signal of shutdownSignals) {
    process.on(signal, () => {
      void gracefulShutdown(signal);
    });
  }

  // Handle uncaught errors
  process.on('uncaughtException', (error) => {
    container.otel.getLogger().fatal(
      { error: error.message, stack: error.stack },
      'Uncaught exception'
    );
    void gracefulShutdown('uncaughtException');
  });

  process.on('unhandledRejection', (reason) => {
    container.otel.getLogger().fatal(
      { reason: reason instanceof Error ? reason.message : String(reason) },
      'Unhandled promise rejection'
    );
    void gracefulShutdown('unhandledRejection');
  });

  // 4. Start the server (blocks until shutdown)
  try {
    await startServer(container, config);
  } catch (error) {
    container.otel.getLogger().fatal(
      { error: error instanceof Error ? error.message : String(error) },
      'Failed to start Catalog service'
    );
    await shutdownContainer(container);
    process.exit(1);
  }
}

// Run the service
main().catch((error: unknown) => {
  // eslint-disable-next-line no-console
  console.error('Fatal error starting Catalog service:', error);
  process.exit(1);
});
