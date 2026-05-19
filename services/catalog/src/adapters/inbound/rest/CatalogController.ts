/**
 * Catalog REST Controller (Inbound Adapter)
 *
 * Implements the REST/HTTP API for the Catalog service using Fastify.
 * Maps HTTP requests to domain use case calls and domain responses
 * back to JSON with proper HTTP status codes.
 *
 * OpenAPI spec is auto-generated via @fastify/swagger.
 */
import Fastify, {
  type FastifyInstance,
  type FastifyRequest,
  type FastifyReply,
} from 'fastify';
import cors from '@fastify/cors';
import swagger from '@fastify/swagger';
import swaggerUi from '@fastify/swagger-ui';
import type { CatalogService } from '../../../domain/services/CatalogService';
import { OtelAdapter } from '../../outbound/observability/OtelAdapter';
import {
  Money,
  ProductNotFoundError,
  DuplicateSKUError,
  InsufficientStockError,
  ProductHasActiveOrdersError,
  DeleteNotAuthorizedError,
  SearchIndexUnavailableError,
  InvalidQueryError,
  ProductValidationError,
  DeleteReason,
} from '../../../domain/models';
import { SortBy } from '../../../domain/ports/inbound/SearchCatalog';

// ---------------------------------------------------------------------------
// Request/Response Schemas
// ---------------------------------------------------------------------------

const MoneySchema = {
  type: 'object',
  required: ['currency_code', 'units', 'nanos'],
  properties: {
    currency_code: { type: 'string', minLength: 3, maxLength: 3, description: 'ISO 4217 currency code' },
    units: { type: 'integer', description: 'Whole units (e.g., dollars)' },
    nanos: { type: 'integer', minimum: -999999999, maximum: 999999999, description: 'Nano units (10^-9). Same sign as units.' },
  },
};

const ProductSchema = {
  type: 'object',
  properties: {
    product_id: { type: 'string' },
    name: { type: 'string' },
    description: { type: 'string' },
    price: MoneySchema,
    category: { type: 'string' },
    tags: { type: 'array', items: { type: 'string' } },
    available_quantity: { type: 'integer' },
    status: { type: 'string', enum: ['ACTIVE', 'INACTIVE', 'DISCONTINUED'] },
    created_at: { type: 'string', format: 'date-time' },
    updated_at: { type: 'string', format: 'date-time' },
  },
};

// ---------------------------------------------------------------------------
// Controller Implementation
// ---------------------------------------------------------------------------

export class CatalogController {
  private readonly catalogService: CatalogService;
  private readonly otel: OtelAdapter;
  private readonly httpPort: number;
  private fastify: FastifyInstance | null = null;

  constructor(
    catalogService: CatalogService,
    otel: OtelAdapter,
    httpPort: number
  ) {
    this.catalogService = catalogService;
    this.otel = otel;
    this.httpPort = httpPort;
  }

  // -------------------------------------------------------------------------
  // Server Lifecycle
  // -------------------------------------------------------------------------

  async start(): Promise<void> {
    this.fastify = Fastify({
      logger: false, // We use pino via OtelAdapter
      ignoreTrailingSlash: true,
      bodyLimit: 10 * 1024 * 1024, // 10MB
    });

    // Register plugins
    await this.fastify.register(cors, {
      origin: true,
      methods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
      allowedHeaders: ['Content-Type', 'Authorization', 'X-Request-ID'],
    });

    await this.fastify.register(swagger, {
      openapi: {
        openapi: '3.1.0',
        info: {
          title: 'Catalog Service API',
          description: 'Product catalog CRUD and search operations',
          version: '0.1.0',
        },
        servers: [
          { url: '/api/v1/catalog', description: 'Catalog Service' },
        ],
      },
    });

    await this.fastify.register(swaggerUi, {
      routePrefix: '/api/docs',
      uiConfig: { docExpansion: 'list' },
    });

    // Register routes
    this.registerRoutes();

    // Start listening
    await this.fastify.listen({ port: this.httpPort, host: '0.0.0.0' });
    this.otel.getLogger().info({ port: this.httpPort }, 'HTTP server started');
  }

  async stop(): Promise<void> {
    if (this.fastify) {
      await this.fastify.close();
      this.otel.getLogger().info('HTTP server stopped');
    }
  }

  getFastify(): FastifyInstance | null {
    return this.fastify;
  }

  // -------------------------------------------------------------------------
  // Route Registration
  // -------------------------------------------------------------------------

  private registerRoutes(): void {
    if (!this.fastify) return;

    // Health check
    this.fastify.get('/healthz', async (_request: FastifyRequest, reply: FastifyReply) => {
      reply.send({ status: 'ok', timestamp: new Date().toISOString() });
    });

    // API v1 routes
    this.fastify.register(async (app) => {
      // GET /api/v1/catalog/products/:id
      app.get<{ Params: { id: string } }>(
        '/products/:id',
        {
          schema: {
            params: {
              type: 'object',
              required: ['id'],
              properties: { id: { type: 'string' } },
            },
            response: { 200: ProductSchema },
          },
        },
        async (request, reply) => this.handleGetProduct(request, reply)
      );

      // GET /api/v1/catalog/products
      app.get(
        '/products',
        {
          schema: {
            querystring: {
              type: 'object',
              properties: {
                q: { type: 'string' },
                category: { type: 'string' },
                tag: { type: 'string' },
                min_price: { type: 'number' },
                max_price: { type: 'number' },
                in_stock: { type: 'boolean' },
                page_size: { type: 'integer', minimum: 1, maximum: 100, default: 20 },
                page_token: { type: 'string' },
                sort: { type: 'string', enum: ['relevance', 'price_asc', 'price_desc', 'created_at'] },
              },
            },
          },
        },
        async (request, reply) => this.handleSearchProducts(request, reply)
      );

      // POST /api/v1/catalog/products
      app.post(
        '/products',
        {
          schema: {
            body: {
              type: 'object',
              required: ['name', 'price', 'category'],
              properties: {
                name: { type: 'string', minLength: 1, maxLength: 500 },
                description: { type: 'string' },
                price: MoneySchema,
                category: { type: 'string', minLength: 1 },
                tags: { type: 'array', items: { type: 'string' } },
                initial_quantity: { type: 'integer', minimum: 0, default: 0 },
              },
            },
            response: { 201: ProductSchema },
          },
        },
        async (request, reply) => this.handleCreateProduct(request, reply)
      );

      // PATCH /api/v1/catalog/products/:id
      app.patch<{ Params: { id: string } }>(
        '/products/:id',
        {
          schema: {
            params: {
              type: 'object',
              required: ['id'],
              properties: { id: { type: 'string' } },
            },
            body: {
              type: 'object',
              properties: {
                name: { type: 'string' },
                description: { type: 'string' },
                price: MoneySchema,
                category: { type: 'string' },
                tags: { type: 'array', items: { type: 'string' } },
                quantity_adjustment: { type: 'integer' },
              },
            },
            response: { 200: ProductSchema },
          },
        },
        async (request, reply) => this.handleUpdateProduct(request, reply)
      );

      // PATCH /api/v1/catalog/products/:id/inventory
      app.patch<{ Params: { id: string } }>(
        '/products/:id/inventory',
        {
          schema: {
            params: {
              type: 'object',
              required: ['id'],
              properties: { id: { type: 'string' } },
            },
            body: {
              type: 'object',
              required: ['quantity_delta', 'reason'],
              properties: {
                quantity_delta: { type: 'integer' },
                reason: {
                  type: 'string',
                  enum: ['SALE', 'RESTOCK', 'ADJUSTMENT', 'RETURN'],
                },
                reference_id: { type: 'string' },
              },
            },
          },
        },
        async (request, reply) => this.handleAdjustInventory(request, reply)
      );

      // DELETE /api/v1/catalog/products/:id
      app.delete<{ Params: { id: string } }>(
        '/products/:id',
        {
          schema: {
            params: {
              type: 'object',
              required: ['id'],
              properties: { id: { type: 'string' } },
            },
            querystring: {
              type: 'object',
              properties: {
                hard_delete: { type: 'boolean', default: false },
                reason: { type: 'string' },
                replacement_product_id: { type: 'string' },
              },
            },
          },
        },
        async (request, reply) => this.handleDeleteProduct(request, reply)
      );
    }, { prefix: '/api/v1/catalog' });
  }

  // -------------------------------------------------------------------------
  // Route Handlers
  // -------------------------------------------------------------------------

  private async handleGetProduct(
    request: FastifyRequest<{ Params: { id: string } }>,
    reply: FastifyReply
  ): Promise<void> {
    const span = this.otel.startSpan('catalog.http.GetProduct');

    try {
      const result = await this.catalogService.getProduct({
        productId: request.params.id,
      });

      this.otel.recordCrudOperation('get', 'success');
      this.otel.endSpan(span);

      reply.send(this.formatProductResponse(result.product));
    } catch (error) {
      this.otel.recordCrudOperation('get', 'error');
      this.otel.endSpan(span, error instanceof Error ? error : undefined);
      this.sendError(reply, error);
    }
  }

  private async handleSearchProducts(
    request: FastifyRequest,
    reply: FastifyReply
  ): Promise<void> {
    const span = this.otel.startSpan('catalog.http.SearchProducts');
    const startTime = Date.now();

    try {
      const query = request.query as Record<string, unknown>;
      const sortBy = this.mapSortParam(
        (query.sort as string) ?? 'relevance'
      );

      const result = await this.catalogService.searchCatalog({
        query: (query.q as string) ?? '',
        filters: {
          categories: query.category
            ? [query.category as string]
            : undefined,
          tags: query.tag ? [query.tag as string] : undefined,
          priceRange: query.min_price && query.max_price ? {
            min: { currencyCode: 'USD', units: Money.fromDecimal('USD', String(query.min_price)).units, nanos: Money.fromDecimal('USD', String(query.min_price)).nanos },
            max: { currencyCode: 'USD', units: Money.fromDecimal('USD', String(query.max_price)).units, nanos: Money.fromDecimal('USD', String(query.max_price)).nanos },
          } : undefined,
          inStockOnly: (query.in_stock as boolean) ?? false,
        },
        pageSize: (query.page_size as number) ?? 20,
        pageToken: (query.page_token as string) ?? '',
        sortBy,
        facetFields: [],
      });

      const durationMs = Date.now() - startTime;
      this.otel.recordSearchDuration('search', result.results.length, durationMs);
      this.otel.endSpan(span);

      reply.send({
        results: result.results,
        total_count: result.totalCount,
        next_page_token: result.nextPageToken,
        facets: result.facets,
        suggestions: result.suggestions,
      });
    } catch (error) {
      const durationMs = Date.now() - startTime;
      this.otel.recordSearchDuration('search', 0, durationMs);
      this.otel.endSpan(span, error instanceof Error ? error : undefined);
      this.sendError(reply, error);
    }
  }

  private async handleCreateProduct(
    request: FastifyRequest,
    reply: FastifyReply
  ): Promise<void> {
    const span = this.otel.startSpan('catalog.http.CreateProduct');

    try {
      const body = request.body as Record<string, unknown>;
      const price = body.price as Record<string, unknown> | undefined;

      const result = await this.catalogService.createProduct({
        name: body.name as string,
        description: (body.description as string) ?? '',
        price: {
          currencyCode: (price?.currency_code as string) ?? 'USD',
          units: (price?.units as number) ?? 0,
          nanos: (price?.nanos as number) ?? 0,
        },
        category: body.category as string,
        tags: (body.tags as string[]) ?? [],
        initialQuantity: (body.initial_quantity as number) ?? 0,
      });

      this.otel.recordCrudOperation('create', 'success');
      this.otel.endSpan(span);

      reply.code(201).send(this.formatProductResponse(result.product));
    } catch (error) {
      this.otel.recordCrudOperation('create', 'error');
      this.otel.endSpan(span, error instanceof Error ? error : undefined);
      this.sendError(reply, error);
    }
  }

  private async handleUpdateProduct(
    request: FastifyRequest<{ Params: { id: string } }>,
    reply: FastifyReply
  ): Promise<void> {
    const span = this.otel.startSpan('catalog.http.UpdateProduct');

    try {
      const body = request.body as Record<string, unknown>;
      const productId = request.params.id;
      const price = body.price as Record<string, unknown> | undefined;

      const changes: Record<string, unknown> = {};
      if (body.name !== undefined) changes.name = body.name;
      if (body.description !== undefined) changes.description = body.description;
      if (price) {
        changes.price = {
          currencyCode: (price.currency_code as string) ?? 'USD',
          units: (price.units as number) ?? 0,
          nanos: (price.nanos as number) ?? 0,
        };
      }
      if (body.category !== undefined) changes.category = body.category;
      if (body.tags !== undefined) changes.tags = body.tags;
      if (body.quantity_adjustment !== undefined) {
        changes.quantityAdjustment = body.quantity_adjustment;
      }

      const updated = await this.catalogService.updateProduct(productId, changes);

      this.otel.recordCrudOperation('update', 'success');
      this.otel.endSpan(span);

      reply.send(this.formatProductResponse(updated));
    } catch (error) {
      this.otel.recordCrudOperation('update', 'error');
      this.otel.endSpan(span, error instanceof Error ? error : undefined);
      this.sendError(reply, error);
    }
  }

  private async handleAdjustInventory(
    request: FastifyRequest<{ Params: { id: string } }>,
    reply: FastifyReply
  ): Promise<void> {
    const span = this.otel.startSpan('catalog.http.AdjustInventory');

    try {
      const body = request.body as Record<string, unknown>;
      const productId = request.params.id;
      const delta = body.quantity_delta as number;
      const reason = body.reason as string;

      const result = await this.catalogService.adjustInventory(productId, delta, reason);

      this.otel.recordInventoryUpdate(reason);
      this.otel.endSpan(span);

      reply.send({
        product_id: productId,
        new_quantity: result.newQuantity,
        previous_quantity: result.previousQuantity,
        updated_at: new Date().toISOString(),
      });
    } catch (error) {
      this.otel.endSpan(span, error instanceof Error ? error : undefined);
      this.sendError(reply, error);
    }
  }

  private async handleDeleteProduct(
    request: FastifyRequest<{ Params: { id: string } }>,
    reply: FastifyReply
  ): Promise<void> {
    const span = this.otel.startSpan('catalog.http.DeleteProduct');

    try {
      const query = request.query as Record<string, unknown>;
      const productId = request.params.id;

      const result = await this.catalogService.deleteProduct({
        productId,
        reason: (query.reason as DeleteReason) ?? DeleteReason.ADMIN_ACTION,
        hardDelete: (query.hard_delete as boolean) ?? false,
        replacementProductId: query.replacement_product_id as string | undefined,
      });

      this.otel.recordCrudOperation('delete', 'success');
      this.otel.endSpan(span);

      if (result.hardDeleted) {
        reply.code(204).send();
      } else {
        reply.send({
          product_id: result.productId,
          deleted: result.deleted,
          hard_deleted: result.hardDeleted,
          replacement_redirect: result.replacementRedirect,
          deleted_at: result.deletedAt.toISOString(),
        });
      }
    } catch (error) {
      this.otel.recordCrudOperation('delete', 'error');
      this.otel.endSpan(span, error instanceof Error ? error : undefined);
      this.sendError(reply, error);
    }
  }

  // -------------------------------------------------------------------------
  // Response Formatting
  // -------------------------------------------------------------------------

  private formatProductResponse(product: {
    productId: string;
    name: string;
    description: string;
    price: { currencyCode: string; units: number; nanos: number };
    category: string;
    tags: ReadonlyArray<string>;
    availableQuantity: number;
    status: string;
    createdAt: Date;
    updatedAt: Date;
  }): Record<string, unknown> {
    return {
      product_id: product.productId,
      name: product.name,
      description: product.description,
      price: {
        currency_code: product.price.currencyCode,
        units: product.price.units,
        nanos: product.price.nanos,
      },
      category: product.category,
      tags: [...product.tags],
      available_quantity: product.availableQuantity,
      status: product.status,
      created_at: product.createdAt.toISOString(),
      updated_at: product.updatedAt.toISOString(),
    };
  }

  private sendError(reply: FastifyReply, error: unknown): void {
    if (error instanceof ProductNotFoundError) {
      reply.code(404).send({
        type: 'https://errors.catalog.service/product-not-found',
        title: 'Product Not Found',
        status: 404,
        detail: error.message,
        error_code: 'PRODUCT_NOT_FOUND',
      });
      return;
    }

    if (error instanceof DuplicateSKUError) {
      reply.code(409).send({
        type: 'https://errors.catalog.service/duplicate-sku',
        title: 'Duplicate SKU',
        status: 409,
        detail: error.message,
        error_code: 'DUPLICATE_SKU',
      });
      return;
    }

    if (error instanceof InsufficientStockError) {
      reply.code(422).send({
        type: 'https://errors.catalog.service/insufficient-stock',
        title: 'Insufficient Stock',
        status: 422,
        detail: error.message,
        error_code: 'INSUFFICIENT_STOCK',
      });
      return;
    }

    if (error instanceof ProductHasActiveOrdersError) {
      reply.code(409).send({
        type: 'https://errors.catalog.service/active-orders',
        title: 'Product Has Active Orders',
        status: 409,
        detail: error.message,
        error_code: 'PRODUCT_HAS_ACTIVE_ORDERS',
      });
      return;
    }

    if (error instanceof DeleteNotAuthorizedError) {
      reply.code(403).send({
        type: 'https://errors.catalog.service/delete-not-authorized',
        title: 'Delete Not Authorized',
        status: 403,
        detail: error.message,
        error_code: 'DELETE_NOT_AUTHORIZED',
      });
      return;
    }

    if (error instanceof ProductValidationError) {
      reply.code(422).send({
        type: 'https://errors.catalog.service/validation-error',
        title: 'Validation Error',
        status: 422,
        detail: error.message,
        error_code: 'PRODUCT_VALIDATION_ERROR',
      });
      return;
    }

    if (error instanceof InvalidQueryError) {
      reply.code(400).send({
        type: 'https://errors.catalog.service/invalid-query',
        title: 'Invalid Query',
        status: 400,
        detail: error.message,
        error_code: 'INVALID_QUERY',
      });
      return;
    }

    if (error instanceof SearchIndexUnavailableError) {
      reply.code(503).send({
        type: 'https://errors.catalog.service/search-unavailable',
        title: 'Search Index Unavailable',
        status: 503,
        detail: error.message,
        error_code: 'SEARCH_INDEX_UNAVAILABLE',
      });
      return;
    }

    // Unknown error — internal server error
    reply.code(500).send({
      type: 'https://errors.catalog.service/internal-error',
      title: 'Internal Server Error',
      status: 500,
      detail: 'An unexpected error occurred',
      error_code: 'INTERNAL',
    });
  }

  private mapSortParam(sort: string): SortBy {
    switch (sort) {
      case 'price_asc': return SortBy.PRICE_ASC;
      case 'price_desc': return SortBy.PRICE_DESC;
      case 'created_at': return SortBy.CREATED_AT;
      case 'relevance':
      default:
        return SortBy.RELEVANCE;
    }
  }
}
