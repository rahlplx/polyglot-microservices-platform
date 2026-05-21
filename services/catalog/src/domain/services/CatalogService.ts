/**
 * CatalogService - Domain Service
 *
 * Implements all inbound use case ports by orchestrating domain logic
 * and delegating I/O to outbound ports (repository, search index).
 *
 * This is the application core — it contains business rules but
 * NO infrastructure concerns. All I/O goes through injected ports.
 *
 * Domain core has ZERO external dependencies.
 */
import type { CreateProduct, CreateProductRequest, CreateProductResponse } from '../ports/inbound/CreateProduct';
import type { GetProduct, GetProductRequest, GetProductResponse } from '../ports/inbound/GetProduct';
import type {
  SearchCatalog,
  SearchCatalogRequest,
  SearchCatalogResponse,
  ProductSummary,
} from '../ports/inbound/SearchCatalog';
import type { DeleteProduct, DeleteProductRequest, DeleteProductResponse } from '../ports/inbound/DeleteProduct';
import type { ProductRepository } from '../ports/outbound/ProductRepository';
import type { SearchIndex } from '../ports/outbound/SearchIndex';
import {
  Product,
  Money,
  ProductStatus,
  ProductNotFoundError,
  ProductHasActiveOrdersError,
  SearchIndexUnavailableError,
  InvalidQueryError,
} from '../models';

// ---------------------------------------------------------------------------
// Service Dependencies
// ---------------------------------------------------------------------------

export interface CatalogServiceDeps {
  readonly productRepository: ProductRepository;
  readonly searchIndex: SearchIndex;
  readonly generateId: () => string;
}

// ---------------------------------------------------------------------------
// CatalogService Implementation
// ---------------------------------------------------------------------------

export class CatalogService implements CreateProduct, GetProduct, SearchCatalog, DeleteProduct {
  private readonly repository: ProductRepository;
  private readonly searchIndex: SearchIndex;
  private readonly generateId: () => string;

  constructor(deps: CatalogServiceDeps) {
    this.repository = deps.productRepository;
    this.searchIndex = deps.searchIndex;
    this.generateId = deps.generateId;
  }

  // -------------------------------------------------------------------------
  // CreateProduct Use Case
  // -------------------------------------------------------------------------

  async execute(request: CreateProductRequest): Promise<CreateProductResponse>;
  async execute(request: GetProductRequest): Promise<GetProductResponse>;
  async execute(request: SearchCatalogRequest): Promise<SearchCatalogResponse>;
  async execute(request: DeleteProductRequest): Promise<DeleteProductResponse>;
  async execute(request: CreateProductRequest | GetProductRequest | SearchCatalogRequest | DeleteProductRequest): Promise<CreateProductResponse | GetProductResponse | SearchCatalogResponse | DeleteProductResponse> {
    if ('name' in request && 'price' in request && 'initialQuantity' in request) {
      return this.createProduct(request as CreateProductRequest);
    }
    if ('productId' in request && !('filters' in request) && !('reason' in request) && !('hardDelete' in request)) {
      return this.getProduct(request as GetProductRequest);
    }
    if ('filters' in request) {
      return this.searchCatalog(request as SearchCatalogRequest);
    }
    if ('reason' in request && 'hardDelete' in request) {
      return this.deleteProduct(request as DeleteProductRequest);
    }
    throw new Error('Unknown request type');
  }

  async createProduct(request: CreateProductRequest): Promise<CreateProductResponse> {
    // Build Money value object from raw input
    const price = Money.create(
      request.price.currencyCode,
      request.price.units,
      request.price.nanos
    );

    // Create domain entity with validation
    const productId = this.generateId();
    const product = Product.create({
      productId,
      name: request.name,
      description: request.description,
      price,
      category: request.category,
      tags: request.tags,
      initialQuantity: request.initialQuantity,
    });

    // Persist via outbound port
    const saved = await this.repository.save(product);

    // Index for search (non-blocking — failure does not block creation)
    try {
      await this.searchIndex.index(saved);
    } catch {
      // Search indexing failure is non-fatal; the product is persisted.
      // A background reconciliation job will pick it up later.
    }

    return { product: saved };
  }

  // -------------------------------------------------------------------------
  // GetProduct Use Case
  // -------------------------------------------------------------------------

  async getProduct(request: GetProductRequest): Promise<GetProductResponse> {
    const product = await this.repository.findById(request.productId);

    if (!product) {
      throw new ProductNotFoundError(request.productId);
    }

    // Suspended products should not be visible to external callers
    if (product.status === ProductStatus.INACTIVE) {
      throw new ProductNotFoundError(request.productId);
    }

    return { product };
  }

  // -------------------------------------------------------------------------
  // SearchCatalog Use Case
  // -------------------------------------------------------------------------

  async searchCatalog(request: SearchCatalogRequest): Promise<SearchCatalogResponse> {
    // Validate query
    if (request.query.length > 1000) {
      throw new InvalidQueryError(
        `Search query exceeds maximum length of 1000 characters (got ${request.query.length}).`
      );
    }

    if (request.pageSize < 1 || request.pageSize > 100) {
      throw new InvalidQueryError(
        `Page size must be between 1 and 100, got ${request.pageSize}.`
      );
    }

    try {
      const result = await this.searchIndex.search({
        query: request.query,
        filters: request.filters,
        pageSize: request.pageSize,
        pageToken: request.pageToken,
        sortBy: request.sortBy,
        facetFields: request.facetFields,
      });

      const summaries: ProductSummary[] = result.results.map((item) => ({
        productId: item.productId,
        name: item.name,
        descriptionSnippet: item.descriptionSnippet,
        price: item.price,
        relevanceScore: item.relevanceScore,
      }));

      return {
        results: summaries,
        totalCount: result.totalCount,
        nextPageToken: result.nextPageToken,
        facets: result.facets,
        suggestions: result.suggestions,
      };
    } catch (error) {
      // If search index is unavailable, attempt PostgreSQL fallback
      if (error instanceof SearchIndexUnavailableError) {
        return this.fallbackSearch(request);
      }
      throw error;
    }
  }

  // -------------------------------------------------------------------------
  // DeleteProduct Use Case
  // -------------------------------------------------------------------------

  async deleteProduct(request: DeleteProductRequest): Promise<DeleteProductResponse> {
    // Verify product exists
    const product = await this.repository.findById(request.productId, true);
    if (!product) {
      throw new ProductNotFoundError(request.productId);
    }

    const now = new Date();

    if (request.hardDelete) {
      // Safety check: cannot hard-delete with active orders
      const hasOrders = await this.repository.hasActiveOrders(request.productId);
      if (hasOrders) {
        throw new ProductHasActiveOrdersError(request.productId);
      }

      await this.repository.hardDelete(request.productId);

      // Remove from search index
      try {
        await this.searchIndex.delete(request.productId);
      } catch {
        // Non-fatal: index will be reconciled later
      }

      return {
        productId: request.productId,
        deleted: true,
        hardDeleted: true,
        deletedAt: now,
      };
    }

    // Soft delete: mark as discontinued
    product.softDelete();
    await this.repository.save(product);

    // Update search index to reflect discontinued status
    try {
      await this.searchIndex.index(product);
    } catch {
      // Non-fatal: index will be reconciled later
    }

    return {
      productId: request.productId,
      deleted: true,
      hardDeleted: false,
      replacementRedirect: request.replacementProductId,
      deletedAt: now,
    };
  }

  // -------------------------------------------------------------------------
  // UpdateProduct (additional convenience method)
  // -------------------------------------------------------------------------

  async updateProduct(
    productId: string,
    changes: {
      name?: string;
      description?: string;
      price?: { currencyCode: string; units: number; nanos: number };
      category?: string;
      tags?: string[];
      quantityAdjustment?: number;
    }
  ): Promise<Product> {
    const product = await this.repository.findById(productId);
    if (!product) {
      throw new ProductNotFoundError(productId);
    }

    const updateInput: {
      name?: string;
      description?: string;
      price?: Money;
      category?: string;
      tags?: string[];
      quantityAdjustment?: number;
    } = {};

    if (changes.price) {
      updateInput.price = Money.create(
        changes.price.currencyCode,
        changes.price.units,
        changes.price.nanos
      );
    }

    Object.assign(updateInput, {
      name: changes.name,
      description: changes.description,
      category: changes.category,
      tags: changes.tags,
      quantityAdjustment: changes.quantityAdjustment,
    });

    // Remove undefined keys to avoid overwriting with undefined
    const filteredInput = Object.fromEntries(
      Object.entries(updateInput).filter(([, v]) => v !== undefined)
    );

    product.update(filteredInput as Parameters<typeof product.update>[0]);

    const saved = await this.repository.save(product);

    // Update search index
    try {
      await this.searchIndex.index(saved);
    } catch {
      // Non-fatal
    }

    return saved;
  }

  // -------------------------------------------------------------------------
  // ListProducts (convenience method)
  // -------------------------------------------------------------------------

  async listProducts(filter: {
    category?: string;
    status?: string;
    cursor?: string;
    pageSize: number;
  }): Promise<{
    products: Product[];
    nextCursor: string;
    totalCount: number;
    hasMore: boolean;
  }> {
    const result = await this.repository.list(filter);
    return {
      products: result.items,
      nextCursor: result.nextCursor,
      totalCount: result.totalCount,
      hasMore: result.hasMore,
    };
  }

  // -------------------------------------------------------------------------
  // Adjust Inventory
  // -------------------------------------------------------------------------

  async adjustInventory(
    productId: string,
    delta: number,
    reason: string
  ): Promise<{ newQuantity: number; previousQuantity: number }> {
    const product = await this.repository.findById(productId);
    if (!product) {
      throw new ProductNotFoundError(productId);
    }

    const previousQuantity = product.availableQuantity;
    product.adjustInventory(delta, reason);

    await this.repository.save(product);

    return {
      newQuantity: product.availableQuantity,
      previousQuantity,
    };
  }

  // -------------------------------------------------------------------------
  // Private: PostgreSQL fallback search when search index is unavailable
  // -------------------------------------------------------------------------

  private async fallbackSearch(
    request: SearchCatalogRequest
  ): Promise<SearchCatalogResponse> {
    // Degraded mode: use database list with category filter only
    const result = await this.repository.list({
      category: request.filters.categories?.[0],
      status: ProductStatus.ACTIVE,
      cursor: request.pageToken,
      pageSize: request.pageSize,
    });

    const summaries: ProductSummary[] = result.items.map((product) => ({
      productId: product.productId,
      name: product.name,
      descriptionSnippet:
        product.description.length > 200
          ? product.description.slice(0, 200) + '...'
          : product.description,
      price: {
        currencyCode: product.price.currencyCode,
        units: product.price.units,
        nanos: product.price.nanos,
      },
      relevanceScore: 0, // No relevance scoring in fallback mode
    }));

    return {
      results: summaries,
      totalCount: result.totalCount,
      nextPageToken: result.nextCursor,
      facets: {},
      suggestions: [],
    };
  }
}
