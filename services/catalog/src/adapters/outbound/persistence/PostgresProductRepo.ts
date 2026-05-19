/**
 * PostgreSQL Product Repository Adapter
 *
 * Implements the ProductRepository outbound port using node-postgres (pg).
 * Maps between domain entities and database rows.
 */
import type { Pool, PoolConfig, QueryResult } from 'pg';
import { Pool as PgPool } from 'pg';
import type { ProductRepository, PaginatedResult, ListProductsFilter } from '../../../domain/ports/outbound/ProductRepository';
import { Product, ProductStatus, Money } from '../../../domain/models';
import type { ProductProps } from '../../../domain/models/Product';

// ---------------------------------------------------------------------------
// Row type matching the database schema
// ---------------------------------------------------------------------------

interface ProductRow {
  product_id: string;
  name: string;
  description: string;
  currency_code: string;
  price_units: number;
  price_nanos: number;
  category: string;
  tags: string[];     // PostgreSQL text[] column
  available_quantity: number;
  status: string;
  created_at: Date;
  updated_at: Date;
  deleted_at: Date | null;
  replacement_product_id: string | null;
}

// ---------------------------------------------------------------------------
// Adapter Implementation
// ---------------------------------------------------------------------------

export class PostgresProductRepo implements ProductRepository {
  private readonly pool: Pool;

  constructor(poolConfig: PoolConfig) {
    this.pool = new PgPool(poolConfig);
  }

  // -------------------------------------------------------------------------
  // Public API
  // -------------------------------------------------------------------------

  async findById(productId: string, includeDeleted = false): Promise<Product | null> {
    const sql = includeDeleted
      ? 'SELECT * FROM products WHERE product_id = $1'
      : 'SELECT * FROM products WHERE product_id = $1 AND deleted_at IS NULL AND status != $2';

    const params = includeDeleted
      ? [productId]
      : [productId, ProductStatus.DISCONTINUED];

    const result: QueryResult<ProductRow> = await this.pool.query(sql, params);

    if (result.rows.length === 0) {
      return null;
    }

    return this.toDomain(result.rows[0]);
  }

  async findByIds(productIds: string[]): Promise<Product[]> {
    if (productIds.length === 0) {
      return [];
    }

    const placeholders = productIds.map((_, i) => `$${i + 1}`).join(', ');
    const sql = `SELECT * FROM products WHERE product_id IN (${placeholders}) AND deleted_at IS NULL`;
    const result: QueryResult<ProductRow> = await this.pool.query(sql, productIds);

    return result.rows.map((row) => this.toDomain(row));
  }

  async save(product: Product): Promise<Product> {
    const existing = await this.findByIdRaw(product.productId);

    if (existing) {
      return this.update(product);
    }
    return this.insert(product);
  }

  async softDelete(productId: string, replacementProductId?: string): Promise<boolean> {
    const sql = `
      UPDATE products
      SET status = $1, deleted_at = NOW(), updated_at = NOW(), replacement_product_id = $2
      WHERE product_id = $3 AND deleted_at IS NULL
    `;
    const result = await this.pool.query(sql, [
      ProductStatus.DISCONTINUED,
      replacementProductId ?? null,
      productId,
    ]);
    return result.rowCount !== null && result.rowCount > 0;
  }

  async hardDelete(productId: string): Promise<boolean> {
    const sql = 'DELETE FROM products WHERE product_id = $1';
    const result = await this.pool.query(sql, [productId]);
    return result.rowCount !== null && result.rowCount > 0;
  }

  async list(filter: ListProductsFilter): Promise<PaginatedResult<Product>> {
    const conditions: string[] = ['deleted_at IS NULL'];
    const params: unknown[] = [];
    let paramIdx = 1;

    if (filter.category) {
      conditions.push(`category = $${paramIdx++}`);
      params.push(filter.category);
    }

    if (filter.status) {
      conditions.push(`status = $${paramIdx++}`);
      params.push(filter.status);
    }

    if (filter.cursor) {
      conditions.push(`created_at < (SELECT created_at FROM products WHERE product_id = $${paramIdx++})`);
      params.push(filter.cursor);
    }

    const whereClause = conditions.join(' AND ');
    const limit = filter.pageSize + 1; // +1 to check hasMore

    const sql = `
      SELECT * FROM products
      WHERE ${whereClause}
      ORDER BY created_at DESC
      LIMIT ${limit}
    `;

    const result: QueryResult<ProductRow> = await this.pool.query(sql, params);
    const hasMore = result.rows.length > filter.pageSize;
    const items = hasMore ? result.rows.slice(0, filter.pageSize) : result.rows;

    // Get total count
    const countSql = `SELECT COUNT(*) as total FROM products WHERE ${whereClause}`;
    const countResult = await this.pool.query(countSql, params.slice(0, paramIdx - 1));
    const totalCount = parseInt(countResult.rows[0].total as string, 10);

    const nextCursor = hasMore && items.length > 0
      ? items[items.length - 1].product_id
      : '';

    return {
      items: items.map((row) => this.toDomain(row)),
      nextCursor,
      totalCount,
      hasMore,
    };
  }

  async hasActiveOrders(productId: string): Promise<boolean> {
    // In a real system, this would query the orders table or a materialized view.
    // For now, we check a hypothetical order_items table.
    const sql = `
      SELECT COUNT(*) as count FROM order_items oi
      JOIN orders o ON o.order_id = oi.order_id
      WHERE oi.product_id = $1 AND o.status NOT IN ('cancelled', 'completed', 'refunded')
    `;
    try {
      const result = await this.pool.query(sql, [productId]);
      return parseInt(result.rows[0].count as string, 10) > 0;
    } catch {
      // If order_items table doesn't exist, allow delete
      return false;
    }
  }

  async adjustInventory(productId: string, delta: number): Promise<number> {
    const sql = `
      UPDATE products
      SET available_quantity = available_quantity + $1,
          updated_at = NOW()
      WHERE product_id = $2 AND available_quantity + $1 >= 0 AND deleted_at IS NULL
      RETURNING available_quantity
    `;
    const result = await this.pool.query(sql, [delta, productId]);

    if (result.rows.length === 0) {
      throw new Error(
        `Insufficient stock or product not found: productId=${productId}, delta=${delta}`
      );
    }

    return result.rows[0].available_quantity as number;
  }

  // -------------------------------------------------------------------------
  // Database Schema Initialization
  // -------------------------------------------------------------------------

  async initializeSchema(): Promise<void> {
    const sql = `
      CREATE TABLE IF NOT EXISTS products (
        product_id            VARCHAR(64)  PRIMARY KEY,
        name                  VARCHAR(500) NOT NULL,
        description           TEXT         NOT NULL DEFAULT '',
        currency_code         CHAR(3)      NOT NULL DEFAULT 'USD',
        price_units           BIGINT       NOT NULL DEFAULT 0,
        price_nanos           INTEGER      NOT NULL DEFAULT 0,
        category              VARCHAR(255) NOT NULL,
        tags                  TEXT[]       NOT NULL DEFAULT '{}',
        available_quantity    INTEGER      NOT NULL DEFAULT 0,
        status                VARCHAR(32)  NOT NULL DEFAULT 'PRODUCT_STATUS_ACTIVE',
        created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        deleted_at            TIMESTAMPTZ,
        replacement_product_id VARCHAR(64)
      );

      CREATE INDEX IF NOT EXISTS idx_products_category ON products (category) WHERE deleted_at IS NULL;
      CREATE INDEX IF NOT EXISTS idx_products_status ON products (status) WHERE deleted_at IS NULL;
      CREATE INDEX IF NOT EXISTS idx_products_created_at ON products (created_at DESC) WHERE deleted_at IS NULL;
      CREATE INDEX IF NOT EXISTS idx_products_name_trgm ON products USING gin (name gin_trgm_ops) WHERE deleted_at IS NULL;
    `;
    await this.pool.query(sql);
  }

  // -------------------------------------------------------------------------
  // Connection Management
  // -------------------------------------------------------------------------

  async close(): Promise<void> {
    await this.pool.end();
  }

  async ping(): Promise<boolean> {
    try {
      const result = await this.pool.query('SELECT 1');
      return result.rowCount === 1;
    } catch {
      return false;
    }
  }

  // -------------------------------------------------------------------------
  // Private Helpers
  // -------------------------------------------------------------------------

  private async findByIdRaw(productId: string): Promise<ProductRow | null> {
    const sql = 'SELECT * FROM products WHERE product_id = $1';
    const result: QueryResult<ProductRow> = await this.pool.query(sql, [productId]);
    return result.rows.length > 0 ? result.rows[0] : null;
  }

  private async insert(product: Product): Promise<Product> {
    const sql = `
      INSERT INTO products (product_id, name, description, currency_code, price_units, price_nanos,
                            category, tags, available_quantity, status, created_at, updated_at)
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
      RETURNING *
    `;
    const params = this.toRow(product);
    const result: QueryResult<ProductRow> = await this.pool.query(sql, params);
    return this.toDomain(result.rows[0]);
  }

  private async update(product: Product): Promise<Product> {
    const sql = `
      UPDATE products
      SET name = $2, description = $3, currency_code = $4, price_units = $5, price_nanos = $6,
          category = $7, tags = $8, available_quantity = $9, status = $10, updated_at = $11
      WHERE product_id = $1
      RETURNING *
    `;
    const params = [
      product.productId,
      product.name,
      product.description,
      product.price.currencyCode,
      product.price.units,
      product.price.nanos,
      product.category,
      product.tags,
      product.availableQuantity,
      product.status,
      product.updatedAt,
    ];
    const result: QueryResult<ProductRow> = await this.pool.query(sql, params);
    return this.toDomain(result.rows[0]);
  }

  private toDomain(row: ProductRow): Product {
    const props: ProductProps = {
      productId: row.product_id,
      name: row.name,
      description: row.description,
      price: Money.create(row.currency_code, row.price_units, row.price_nanos),
      category: row.category,
      tags: row.tags,
      availableQuantity: row.available_quantity,
      status: row.status as ProductStatus,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
    };
    return Product.reconstitute(props);
  }

  private toRow(product: Product): unknown[] {
    return [
      product.productId,
      product.name,
      product.description,
      product.price.currencyCode,
      product.price.units,
      product.price.nanos,
      product.category,
      product.tags,
      product.availableQuantity,
      product.status,
      product.createdAt,
      product.updatedAt,
    ];
  }
}
