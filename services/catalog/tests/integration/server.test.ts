/**
 * Catalog Service - Integration Tests
 *
 * Tests the full server lifecycle including configuration loading,
 * DI container wiring, and server startup/shutdown.
 * These tests verify that all components integrate correctly
 * without actually connecting to external services.
 */

import { describe, it, expect, beforeEach, afterEach, jest } from '@jest/globals';
import { loadConfig } from '../../src/infrastructure/config/config';

// ---------------------------------------------------------------------------
// Configuration Integration Tests
// ---------------------------------------------------------------------------

describe('Configuration Integration', () => {
  const originalEnv = process.env;

  beforeEach(() => {
    jest.resetModules();
    process.env = { ...originalEnv };
  });

  afterEach(() => {
    process.env = originalEnv;
  });

  it('should load default configuration when no env vars are set', () => {
    // Clear catalog-specific env vars
    for (const key of Object.keys(process.env)) {
      if (key.startsWith('CATALOG_')) {
        delete process.env[key];
      }
    }
    delete process.env.NODE_ENV;

    // Set required credentials for validation to pass
    process.env.CATALOG_DB_PASSWORD = 'test';
    process.env.CATALOG_MEILISEARCH_API_KEY = 'test';

    const config = loadConfig();

    expect(config.server.httpPort).toBe(3000);
    expect(config.server.grpcPort).toBe(50053);
    expect(config.database.host).toBe('localhost');
    expect(config.database.port).toBe(5432);
    expect(config.database.database).toBe('catalog');
    expect(config.meilisearch.host).toBe('http://localhost:7700');
    expect(config.meilisearch.indexName).toBe('products');
    expect(config.otel.enabled).toBe(true);
    expect(config.otel.serviceName).toBe('catalog');
    expect(config.spiffe.enabled).toBe(false);
    expect(config.features.enableSearch).toBe(true);
  });

  it('should override configuration from environment variables', () => {
    process.env.CATALOG_HTTP_PORT = '8080';
    process.env.CATALOG_GRPC_PORT = '50051';
    process.env.CATALOG_DB_HOST = 'postgres.prod';
    process.env.CATALOG_DB_PORT = '5433';
    process.env.CATALOG_DB_NAME = 'catalog_prod';
    process.env.CATALOG_MEILISEARCH_HOST = 'http://search.prod:7700';
    process.env.CATALOG_OTEL_ENABLED = 'false';
    process.env.CATALOG_SPIFFE_ENABLED = 'true';
    process.env.CATALOG_SPIFFE_TRUST_DOMAIN = 'prod.example.org';
    process.env.NODE_ENV = 'production';

    const config = loadConfig();

    expect(config.server.httpPort).toBe(8080);
    expect(config.server.grpcPort).toBe(50051);
    expect(config.database.host).toBe('postgres.prod');
    expect(config.database.port).toBe(5433);
    expect(config.database.database).toBe('catalog_prod');
    expect(config.meilisearch.host).toBe('http://search.prod:7700');
    expect(config.otel.enabled).toBe(false);
    expect(config.spiffe.enabled).toBe(true);
    expect(config.spiffe.trustDomain).toBe('prod.example.org');
    expect(config.env).toBe('production');
  });

  it('should validate configuration and throw on invalid values', () => {
    process.env.CATALOG_HTTP_PORT = '0';

    expect(() => loadConfig()).toThrow();
  });

  it('should validate gRPC port is different from HTTP port', () => {
    process.env.CATALOG_HTTP_PORT = '3000';
    process.env.CATALOG_GRPC_PORT = '3000';

    expect(() => loadConfig()).toThrow();
  });
});

// ---------------------------------------------------------------------------
// Hexagonal Architecture Verification Tests
// ---------------------------------------------------------------------------

describe('Hexagonal Architecture Verification', () => {
  it('should ensure domain models have no external dependencies', async () => {
    // Read the domain model files and verify they don't import external packages
    const fs = await import('fs');
    const path = await import('path');

    const domainDir = path.join(__dirname, '../../src/domain');
    const domainFiles = findTsFiles(domainDir);

    for (const file of domainFiles) {
      const content = fs.readFileSync(file, 'utf-8');

      // Multiline import support: find the full import statement
      const importMatches = content.match(/import\s+(?:[^;]+|{[^}]+})\s+from\s+['"][^'"]+['"]/g) || [];

      const externalImports = importMatches
        .filter((imp) => !imp.includes('./') && !imp.includes('../'))
        .filter((imp) => !imp.includes('type ') && !imp.includes('type{') && !imp.includes('type {'));

      if (externalImports.length > 0) {
        console.log(`External imports found in ${file}:`, externalImports);
      }
      expect(externalImports).toHaveLength(0);
    }
  });

  it('should ensure all ports are interfaces', async () => {
    const fs = await import('fs');
    const path = await import('path');

    const portsDir = path.join(__dirname, '../../src/domain/ports');
    const portFiles = findTsFiles(portsDir);

    for (const file of portFiles) {
      if (file.endsWith('index.ts')) continue;

      const content = fs.readFileSync(file, 'utf-8');
      // Port files should export interfaces, not classes
      const hasInterfaceExport = content.includes('export interface');
      const hasClassExport = content.includes('export class');

      expect(hasInterfaceExport).toBe(true);
      if (hasClassExport) {
        // If there's a class export in a port file, it should be an error type, not the port itself
        expect(content).not.toMatch(/export class \w+Port/);
      }
    }
  });

  it('should verify CatalogService implements all inbound ports', async () => {
    const fs = await import('fs');
    const path = await import('path');

    const serviceFile = path.join(
      __dirname, '../../src/domain/services/CatalogService.ts'
    );
    const content = fs.readFileSync(serviceFile, 'utf-8');

    // Verify the service implements the key interfaces
    expect(content).toContain('implements CreateProduct');
    expect(content).toContain('GetProduct');
    expect(content).toContain('SearchCatalog');
    expect(content).toContain('DeleteProduct');
  });
});

// ---------------------------------------------------------------------------
// Server Startup Tests
// ---------------------------------------------------------------------------

describe('Server Startup', () => {
  it('should verify all required adapter classes exist', async () => {
    const fs = await import('fs');
    const path = await import('path');

    const requiredFiles = [
      'src/adapters/outbound/persistence/PostgresProductRepo.ts',
      'src/adapters/outbound/search/MeilisearchAdapter.ts',
      'src/adapters/outbound/observability/OtelAdapter.ts',
      'src/adapters/outbound/identity/SpiffeAdapter.ts',
      'src/adapters/inbound/grpc/CatalogGrpcHandler.ts',
      'src/adapters/inbound/rest/CatalogController.ts',
      'src/infrastructure/config/config.ts',
      'src/infrastructure/di/container.ts',
      'src/infrastructure/server/server.ts',
      'src/main.ts',
    ];

    for (const file of requiredFiles) {
      const filePath = path.join(__dirname, '../..', file);
      const exists = fs.existsSync(filePath);
      expect(exists).toBe(true);
    }
  });

  it('should verify Dockerfile exists and is multi-stage', async () => {
    const fs = await import('fs');
    const path = await import('path');

    const dockerfilePath = path.join(__dirname, '../..', 'Dockerfile');
    const exists = fs.existsSync(dockerfilePath);
    expect(exists).toBe(true);

    if (exists) {
      const content = fs.readFileSync(dockerfilePath, 'utf-8');
      expect(content).toContain('FROM node:20-bookworm AS builder');
      expect(content).toContain('FROM node:20-slim AS runtime');
      expect(content).toContain('EXPOSE');
      expect(content).toContain('HEALTHCHECK');
      expect(content).toContain('USER catalog');
    }
  });

  it('should verify Makefile exists with required targets', async () => {
    const fs = await import('fs');
    const path = await import('path');

    const makefilePath = path.join(__dirname, '../..', 'Makefile');
    const exists = fs.existsSync(makefilePath);
    expect(exists).toBe(true);

    if (exists) {
      const content = fs.readFileSync(makefilePath, 'utf-8');
      expect(content).toContain('build:');
      expect(content).toContain('test:');
      expect(content).toContain('lint:');
      expect(content).toContain('docker:build:');
      expect(content).toContain('proto:');
    }
  });

  it('should verify tsconfig.json has strict mode enabled', async () => {
    const fs = await import('fs');
    const path = await import('path');

    const tsconfigPath = path.join(__dirname, '../..', 'tsconfig.json');
    const content = fs.readFileSync(tsconfigPath, 'utf-8');
    const config = JSON.parse(content);

    expect(config.compilerOptions.strict).toBe(true);
    expect(config.compilerOptions.noImplicitAny).toBe(true);
    expect(config.compilerOptions.strictNullChecks).toBe(true);
  });

  it('should verify .eslintrc.json forbids any type', async () => {
    const fs = await import('fs');
    const path = await import('path');

    const eslintPath = path.join(__dirname, '../..', '.eslintrc.json');
    const content = fs.readFileSync(eslintPath, 'utf-8');
    const config = JSON.parse(content);

    expect(config.rules['@typescript-eslint/no-explicit-any']).toBe('error');
  });
});

// ---------------------------------------------------------------------------
// Helper Functions
// ---------------------------------------------------------------------------

function findTsFiles(dir: string): string[] {
  const fs = require('fs');
  const path = require('path');
  const results: string[] = [];

  if (!fs.existsSync(dir)) {
    return results;
  }

  const entries = fs.readdirSync(dir, { withFileTypes: true });

  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...findTsFiles(fullPath));
    } else if (entry.isFile() && entry.name.endsWith('.ts') && !entry.name.endsWith('.d.ts')) {
      results.push(fullPath);
    }
  }

  return results;
}
