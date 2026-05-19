/**
 * Catalog gRPC Handler (Inbound Adapter)
 *
 * Implements the catalog.v1.CatalogService gRPC service definition.
 * Maps gRPC requests to domain use case calls and domain responses
 * back to gRPC protocol buffer messages.
 *
 * Uses @grpc/grpc-js with proto-loader for dynamic proto loading.
 */
import {
  Server,
  ServerCredentials,
  loadPackageDefinition,
  type ServerUnaryCall,
  type sendUnaryData,
  type UntypedServiceImplementation,
  status as grpcStatus,
} from '@grpc/grpc-js';
import { loadSync } from '@grpc/proto-loader';
import type { CatalogService } from '../../../domain/services/CatalogService';
import { OtelAdapter } from '../../outbound/observability/OtelAdapter';
import { ProductStatus, DeleteReason } from '../../../domain/models';
import { SortBy } from '../../../domain/ports/inbound/SearchCatalog';
import type { Product } from '../../../domain/models';

// gRPC reflection support
// To enable reflection, install grpc-reflection package and add:
//   import { addReflection } from 'grpc-reflection';
// Then after server.addService(), call:
//   addReflection(this.server);
// This requires the compiled proto file descriptors to be available.

// ---------------------------------------------------------------------------
// Proto Package Loading
// ---------------------------------------------------------------------------

interface ProtoPackage {
  catalog: {
    v1: {
      CatalogService: {
        service: Record<string, { path: string; requestStream: boolean; responseStream: boolean }>;
      };
    };
  };
}

function loadProtoDefinition(protoPath: string): ProtoPackage {
  const packageDef = loadSync(protoPath, {
    keepCase: true,
    longs: String,
    enums: String,
    defaults: true,
    oneofs: true,
    includeDirs: [
      `${process.cwd()}/schemas/proto`,
      `${process.cwd()}/../../schemas/proto`,
    ],
  });
  return loadPackageDefinition(packageDef) as unknown as ProtoPackage;
}

// ---------------------------------------------------------------------------
// gRPC Message Mappers
// ---------------------------------------------------------------------------

function productToGrpc(product: Product): Record<string, unknown> {
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
    status: productStatusToGrpc(product.status),
    created_at: product.createdAt.toISOString(),
    updated_at: product.updatedAt.toISOString(),
  };
}

function productStatusToGrpc(status: ProductStatus): number {
  const mapping: Record<string, number> = {
    [ProductStatus.UNSPECIFIED]: 0,
    [ProductStatus.ACTIVE]: 1,
    [ProductStatus.INACTIVE]: 2,
    [ProductStatus.DISCONTINUED]: 3,
  };
  return mapping[status] ?? 0;
}

// ---------------------------------------------------------------------------
// Handler Implementation
// ---------------------------------------------------------------------------

export class CatalogGrpcHandler {
  private readonly catalogService: CatalogService;
  private readonly otel: OtelAdapter;
  private readonly server: Server;
  private readonly grpcPort: number;

  constructor(
    catalogService: CatalogService,
    otel: OtelAdapter,
    grpcPort: number,
    protoPath: string
  ) {
    this.catalogService = catalogService;
    this.otel = otel;
    this.grpcPort = grpcPort;
    this.server = new Server();

    // Load proto and register service
    const pkg = loadProtoDefinition(protoPath);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const serviceDef = pkg.catalog.v1.CatalogService.service as any;

    const implementation: UntypedServiceImplementation = {
      CreateProduct: this.createProduct.bind(this),
      GetProduct: this.getProduct.bind(this),
      UpdateProduct: this.updateProduct.bind(this),
      DeleteProduct: this.deleteProduct.bind(this),
      SearchProducts: this.searchProducts.bind(this),
      ListProducts: this.listProducts.bind(this),
    };

    this.server.addService(serviceDef, implementation);
  }

  // -------------------------------------------------------------------------
  // Server Lifecycle
  // -------------------------------------------------------------------------

  async start(): Promise<void> {
    return new Promise((resolve) => {
      this.server.bindAsync(
        `0.0.0.0:${this.grpcPort}`,
        ServerCredentials.createInsecure(),
        (error) => {
          if (error) {
            this.otel.getLogger().error({ error: error.message }, 'gRPC server bind failed');
            throw error;
          }

          // Enable gRPC reflection for service discovery (e.g., grpcurl)
          try {
            // eslint-disable-next-line @typescript-eslint/no-require-imports
            const { addReflection } = require('grpc-reflection') as { addReflection: (server: Server) => void };
            addReflection(this.server);
            this.otel.getLogger().info('gRPC reflection enabled');
          } catch {
            // grpc-reflection package not installed; reflection disabled
            this.otel.getLogger().warn('grpc-reflection package not installed; gRPC reflection disabled');
          }

          this.server.start();
          this.otel.getLogger().info({ port: this.grpcPort }, 'gRPC server started');
          resolve();
        }
      );
    });
  }

  async stop(): Promise<void> {
    return new Promise((resolve) => {
      this.server.tryShutdown((error) => {
        if (error) {
          this.otel.getLogger().warn({ error: error.message }, 'gRPC server shutdown error');
        }
        resolve();
      });
    });
  }

  // -------------------------------------------------------------------------
  // RPC Handlers
  // -------------------------------------------------------------------------

  private async createProduct(
    call: ServerUnaryCall<Record<string, unknown>, Record<string, unknown>>,
    callback: sendUnaryData<Record<string, unknown>>
  ): Promise<void> {
    const span = this.otel.startSpan('catalog.grpc.CreateProduct');

    try {
      const request = call.request;
      const price = request.price as Record<string, unknown> | undefined;

      const result = await this.catalogService.createProduct({
        name: request.name as string,
        description: (request.description as string) ?? '',
        price: {
          currencyCode: (price?.currency_code as string) ?? 'USD',
          units: (price?.units as number) ?? 0,
          nanos: (price?.nanos as number) ?? 0,
        },
        category: request.category as string,
        tags: (request.tags as string[]) ?? [],
        initialQuantity: (request.initial_quantity as number) ?? 0,
      });

      this.otel.recordCrudOperation('create', 'success');
      this.otel.endSpan(span);

      callback(null, { product: productToGrpc(result.product) });
    } catch (error) {
      this.otel.recordCrudOperation('create', 'error');
      this.otel.endSpan(span, error instanceof Error ? error : new Error(String(error)));
      const code = this.mapErrorToGrpcCode(error);
      const message = error instanceof Error ? error.message : String(error);
      callback({ code, message });
    }
  }

  private async getProduct(
    call: ServerUnaryCall<Record<string, unknown>, Record<string, unknown>>,
    callback: sendUnaryData<Record<string, unknown>>
  ): Promise<void> {
    const span = this.otel.startSpan('catalog.grpc.GetProduct');

    try {
      const productId = call.request.product_id as string;
      const result = await this.catalogService.getProduct({ productId });

      this.otel.recordCrudOperation('get', 'success');
      this.otel.endSpan(span);

      callback(null, { product: productToGrpc(result.product) });
    } catch (error) {
      this.otel.recordCrudOperation('get', 'error');
      this.otel.endSpan(span, error instanceof Error ? error : new Error(String(error)));
      const code = this.mapErrorToGrpcCode(error);
      const message = error instanceof Error ? error.message : String(error);
      callback({ code, message });
    }
  }

  private async updateProduct(
    call: ServerUnaryCall<Record<string, unknown>, Record<string, unknown>>,
    callback: sendUnaryData<Record<string, unknown>>
  ): Promise<void> {
    const span = this.otel.startSpan('catalog.grpc.UpdateProduct');

    try {
      const request = call.request;
      const productId = request.product_id as string;
      const price = request.price as Record<string, unknown> | undefined;

      const changes: Record<string, unknown> = {};
      if (request.name !== undefined) changes.name = request.name;
      if (request.description !== undefined) changes.description = request.description;
      if (price) {
        changes.price = {
          currencyCode: (price.currency_code as string) ?? 'USD',
          units: (price.units as number) ?? 0,
          nanos: (price.nanos as number) ?? 0,
        };
      }
      if (request.category !== undefined) changes.category = request.category;
      if (request.tags !== undefined) changes.tags = request.tags;
      if (request.quantity_adjustment !== undefined) {
        changes.quantityAdjustment = request.quantity_adjustment;
      }

      const updated = await this.catalogService.updateProduct(productId, changes);

      this.otel.recordCrudOperation('update', 'success');
      this.otel.endSpan(span);

      callback(null, { product: productToGrpc(updated) });
    } catch (error) {
      this.otel.recordCrudOperation('update', 'error');
      this.otel.endSpan(span, error instanceof Error ? error : new Error(String(error)));
      const code = this.mapErrorToGrpcCode(error);
      const message = error instanceof Error ? error.message : String(error);
      callback({ code, message });
    }
  }

  private async deleteProduct(
    call: ServerUnaryCall<Record<string, unknown>, Record<string, unknown>>,
    callback: sendUnaryData<Record<string, unknown>>
  ): Promise<void> {
    const span = this.otel.startSpan('catalog.grpc.DeleteProduct');

    try {
      const request = call.request;
      const result = await this.catalogService.deleteProduct({
        productId: request.product_id as string,
        reason: (request.reason as DeleteReason) ?? DeleteReason.ADMIN_ACTION,
        hardDelete: (request.hard_delete as boolean) ?? false,
        replacementProductId: request.replacement_product_id as string | undefined,
      });

      this.otel.recordCrudOperation('delete', 'success');
      this.otel.endSpan(span);

      callback(null, {
        deleted: result.deleted,
        replacement_product_id: result.replacementRedirect ?? '',
      });
    } catch (error) {
      this.otel.recordCrudOperation('delete', 'error');
      this.otel.endSpan(span, error instanceof Error ? error : new Error(String(error)));
      const code = this.mapErrorToGrpcCode(error);
      const message = error instanceof Error ? error.message : String(error);
      callback({ code, message });
    }
  }

  private async searchProducts(
    call: ServerUnaryCall<Record<string, unknown>, Record<string, unknown>>,
    callback: sendUnaryData<Record<string, unknown>>
  ): Promise<void> {
    const span = this.otel.startSpan('catalog.grpc.SearchProducts');
    const startTime = Date.now();

    try {
      const request = call.request;
      const minPrice = request.min_price as Record<string, unknown> | undefined;
      const maxPrice = request.max_price as Record<string, unknown> | undefined;
      const pagination = request.pagination as Record<string, unknown> | undefined;

      const result = await this.catalogService.searchCatalog({
        query: (request.query as string) ?? '',
        filters: {
          categories: (request.category_filters as string[]) ?? [],
          tags: (request.tag_filters as string[]) ?? [],
          priceRange: minPrice && maxPrice ? {
            min: {
              currencyCode: (minPrice.currency_code as string) ?? 'USD',
              units: (minPrice.units as number) ?? 0,
              nanos: (minPrice.nanos as number) ?? 0,
            },
            max: {
              currencyCode: (maxPrice.currency_code as string) ?? 'USD',
              units: (maxPrice.units as number) ?? 0,
              nanos: (maxPrice.nanos as number) ?? 0,
            },
          } : undefined,
          inStockOnly: (request.in_stock_only as boolean) ?? false,
        },
        pageSize: (pagination?.page_size as number) ?? 20,
        pageToken: (pagination?.cursor as string) ?? '',
        sortBy: this.mapSortField(
          (request.sort_field as string) ?? 'relevance',
          (request.sort_order as string) ?? 'desc'
        ),
        facetFields: [],
      });

      const durationMs = Date.now() - startTime;
      this.otel.recordSearchDuration('search', result.results.length, durationMs);
      this.otel.endSpan(span);

      const grpcProducts = result.results.map((item) => ({
        product_id: item.productId,
        name: item.name,
        description: item.descriptionSnippet,
        price: item.price,
        category: '',
        tags: [],
        available_quantity: 0,
        status: productStatusToGrpc(ProductStatus.ACTIVE),
      }));

      callback(null, {
        products: grpcProducts,
        total_matches: result.totalCount,
        pagination: {
          next_cursor: result.nextPageToken,
          total_count: result.totalCount,
          has_more: result.nextPageToken !== '',
        },
      });
    } catch (error) {
      const durationMs = Date.now() - startTime;
      this.otel.recordSearchDuration('search', 0, durationMs);
      this.otel.endSpan(span, error instanceof Error ? error : new Error(String(error)));
      const code = this.mapErrorToGrpcCode(error);
      const message = error instanceof Error ? error.message : String(error);
      callback({ code, message });
    }
  }

  private async listProducts(
    call: ServerUnaryCall<Record<string, unknown>, Record<string, unknown>>,
    callback: sendUnaryData<Record<string, unknown>>
  ): Promise<void> {
    const span = this.otel.startSpan('catalog.grpc.ListProducts');

    try {
      const request = call.request;
      const pagination = request.pagination as Record<string, unknown> | undefined;

      const result = await this.catalogService.listProducts({
        category: request.category_filter as string | undefined,
        status: request.status_filter as string | undefined,
        cursor: (pagination?.cursor as string) ?? undefined,
        pageSize: (pagination?.page_size as number) ?? 20,
      });

      this.otel.endSpan(span);

      callback(null, {
        products: result.products.map(productToGrpc),
        pagination: {
          next_cursor: result.nextCursor,
          total_count: result.totalCount,
          has_more: result.hasMore,
        },
      });
    } catch (error) {
      this.otel.endSpan(span, error instanceof Error ? error : new Error(String(error)));
      const code = this.mapErrorToGrpcCode(error);
      const message = error instanceof Error ? error.message : String(error);
      callback({ code, message });
    }
  }

  // -------------------------------------------------------------------------
  // Error Mapping
  // -------------------------------------------------------------------------

  private mapErrorToGrpcCode(error: unknown): number {
    if (error instanceof Error) {
      const code = (error as { code?: string }).code;
      switch (code) {
        case 'PRODUCT_NOT_FOUND':
          return grpcStatus.NOT_FOUND;
        case 'DUPLICATE_SKU':
          return grpcStatus.ALREADY_EXISTS;
        case 'INSUFFICIENT_STOCK':
          return grpcStatus.FAILED_PRECONDITION;
        case 'PRODUCT_HAS_ACTIVE_ORDERS':
          return grpcStatus.FAILED_PRECONDITION;
        case 'DELETE_NOT_AUTHORIZED':
          return grpcStatus.PERMISSION_DENIED;
        case 'PRODUCT_VALIDATION_ERROR':
        case 'INVALID_QUERY':
          return grpcStatus.INVALID_ARGUMENT;
        case 'SEARCH_INDEX_UNAVAILABLE':
          return grpcStatus.UNAVAILABLE;
        default:
          return grpcStatus.INTERNAL;
      }
    }
    return grpcStatus.INTERNAL;
  }

  private mapSortField(field: string, order: string): SortBy {
    switch (field) {
      case 'price':
        return order === 'asc' ? SortBy.PRICE_ASC : SortBy.PRICE_DESC;
      case 'name':
        return SortBy.RELEVANCE;
      case 'created_at':
        return SortBy.CREATED_AT;
      case 'relevance':
      default:
        return SortBy.RELEVANCE;
    }
  }
}
