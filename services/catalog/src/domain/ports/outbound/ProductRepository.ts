/**
 * ProductRepository Outbound Port (Driven)
 *
 * Defines the interface for persisting and retrieving Product aggregates.
 * This is a driven port — adapters on the outbound side implement this interface.
 *
 * Domain core has ZERO external dependencies.
 */
import type { Product } from '../../models';

export interface ProductRow {
  readonly product_id: string;
  readonly name: string;
  readonly description: string;
  readonly currency_code: string;
  readonly price_units: number;
  readonly price_nanos: number;
  readonly category: string;
  readonly tags: string[];
  readonly available_quantity: number;
  readonly status: string;
  readonly created_at: Date;
  readonly updated_at: Date;
  readonly deleted_at: Date | null;
  readonly replacement_product_id: string | null;
}

export interface PaginatedResult<T> {
  readonly items: T[];
  readonly nextCursor: string;
  readonly totalCount: number;
  readonly hasMore: boolean;
}

export interface ListProductsFilter {
  readonly category?: string;
  readonly status?: string;
  readonly cursor?: string;
  readonly pageSize: number;
}

export interface ProductRepository {
  /**
   * Find a product by its unique ID.
   * Returns null if not found or soft-deleted (unless includeDeleted is true).
   */
  findById(productId: string, includeDeleted?: boolean): Promise<Product | null>;

  /**
   * Find products by a list of IDs (batch retrieval).
   */
  findByIds(productIds: string[]): Promise<Product[]>;

  /**
   * Save a product (create or update).
   * Returns the persisted product with any database-generated fields.
   */
  save(product: Product): Promise<Product>;

  /**
   * Soft-delete a product by marking it as discontinued.
   */
  softDelete(productId: string, replacementProductId?: string): Promise<boolean>;

  /**
   * Hard-delete a product permanently from the database.
   */
  hardDelete(productId: string): Promise<boolean>;

  /**
   * List products with pagination and optional filtering.
   */
  list(filter: ListProductsFilter): Promise<PaginatedResult<Product>>;

  /**
   * Check if a product has any active orders (for hard-delete safety).
   */
  hasActiveOrders(productId: string): Promise<boolean>;

  /**
   * Atomically adjust inventory levels.
   * Returns the new quantity, or throws if insufficient stock.
   */
  adjustInventory(productId: string, delta: number): Promise<number>;
}
