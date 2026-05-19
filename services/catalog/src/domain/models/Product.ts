/**
 * Product Domain Entity
 *
 * Core domain model representing a product in the catalog.
 * Follows the catalog.v1.Product protobuf definition.
 *
 * Domain core has ZERO external dependencies.
 */
import { Money } from './Money';

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export enum ProductStatus {
  UNSPECIFIED = 'PRODUCT_STATUS_UNSPECIFIED',
  ACTIVE = 'PRODUCT_STATUS_ACTIVE',
  INACTIVE = 'PRODUCT_STATUS_INACTIVE',
  DISCONTINUED = 'PRODUCT_STATUS_DISCONTINUED',
}

export enum DeleteReason {
  DISCONTINUED = 'DISCONTINUED',
  COMPLIANCE_REMOVAL = 'COMPLIANCE_REMOVAL',
  MERGE_DUPLICATE = 'MERGE_DUPLICATE',
  ADMIN_ACTION = 'ADMIN_ACTION',
}

// ---------------------------------------------------------------------------
// Product Entity
// ---------------------------------------------------------------------------

export class Product {
  public readonly productId: string;
  public name: string;
  public description: string;
  public price: Money;
  public category: string;
  public tags: ReadonlyArray<string>;
  public availableQuantity: number;
  public status: ProductStatus;
  public readonly createdAt: Date;
  public updatedAt: Date;

  constructor(props: ProductProps) {
    this.productId = props.productId;
    this.name = props.name;
    this.description = props.description;
    this.price = props.price;
    this.category = props.category;
    this.tags = Object.freeze([...props.tags]);
    this.availableQuantity = props.availableQuantity;
    this.status = props.status;
    this.createdAt = props.createdAt;
    this.updatedAt = props.updatedAt;
  }

  /**
   * Factory method to create a new Product with validation.
   */
  public static create(input: CreateProductInput): Product {
    Product.validateName(input.name);
    Product.validateCategory(input.category);
    Product.validateQuantity(input.initialQuantity, 'initial_quantity');

    const now = new Date();
    return new Product({
      productId: input.productId,
      name: input.name,
      description: input.description ?? '',
      price: input.price,
      category: input.category,
      tags: input.tags ?? [],
      availableQuantity: input.initialQuantity,
      status: ProductStatus.ACTIVE,
      createdAt: now,
      updatedAt: now,
    });
  }

  /**
   * Reconstitute a Product from persistence (no validation - data is trusted).
   */
  public static reconstitute(props: ProductProps): Product {
    return new Product(props);
  }

  // ---------------------------------------------------------------------------
  // Behavior Methods
  // ---------------------------------------------------------------------------

  /**
   * Update mutable product fields.
   */
  public update(changes: UpdateProductInput): Product {
    if (changes.name !== undefined) {
      Product.validateName(changes.name);
      this.name = changes.name;
    }
    if (changes.description !== undefined) {
      this.description = changes.description;
    }
    if (changes.price !== undefined) {
      this.price = changes.price;
    }
    if (changes.category !== undefined) {
      Product.validateCategory(changes.category);
      this.category = changes.category;
    }
    if (changes.tags !== undefined) {
      this.tags = Object.freeze([...changes.tags]);
    }
    if (changes.quantityAdjustment !== undefined) {
      const newQty = this.availableQuantity + changes.quantityAdjustment;
      if (newQty < 0) {
        throw new InsufficientStockError(
          this.productId,
          this.availableQuantity,
          Math.abs(changes.quantityAdjustment)
        );
      }
      this.availableQuantity = newQty;
    }
    this.updatedAt = new Date();
    return this;
  }

  /**
   * Soft-delete the product (mark as discontinued).
   */
  public softDelete(): Product {
    this.status = ProductStatus.DISCONTINUED;
    this.updatedAt = new Date();
    return this;
  }

  /**
   * Check if product is available for purchase.
   */
  public isAvailable(): boolean {
    return this.status === ProductStatus.ACTIVE && this.availableQuantity > 0;
  }

  /**
   * Check if product is visible in search results.
   */
  public isSearchable(): boolean {
    return this.status === ProductStatus.ACTIVE;
  }

  /**
   * Adjust inventory by a delta (positive for restock, negative for sales).
   */
  public adjustInventory(delta: number, reason: string): Product {
    if (!Number.isInteger(delta)) {
      throw new ProductValidationError(
        `Inventory delta must be an integer, got: ${delta}`
      );
    }
    const newQty = this.availableQuantity + delta;
    if (newQty < 0) {
      throw new InsufficientStockError(
        this.productId,
        this.availableQuantity,
        Math.abs(delta)
      );
    }
    this.availableQuantity = newQty;
    this.updatedAt = new Date();
    void reason; // audit trail – consumed by event publisher
    return this;
  }

  // ---------------------------------------------------------------------------
  // Validation
  // ---------------------------------------------------------------------------

  private static validateName(name: string): void {
    if (!name || name.trim().length === 0) {
      throw new ProductValidationError('Product name is required and cannot be empty.');
    }
    if (name.length > 500) {
      throw new ProductValidationError(
        `Product name exceeds maximum length of 500 characters (got ${name.length}).`
      );
    }
  }

  private static validateCategory(category: string): void {
    if (!category || category.trim().length === 0) {
      throw new ProductValidationError('Product category is required and cannot be empty.');
    }
  }

  private static validateQuantity(quantity: number, field: string): void {
    if (!Number.isInteger(quantity)) {
      throw new ProductValidationError(
        `${field} must be an integer, got: ${quantity}`
      );
    }
    if (quantity < 0) {
      throw new ProductValidationError(
        `${field} cannot be negative, got: ${quantity}`
      );
    }
  }
}

// ---------------------------------------------------------------------------
// Type Definitions
// ---------------------------------------------------------------------------

export interface ProductProps {
  productId: string;
  name: string;
  description: string;
  price: Money;
  category: string;
  tags: string[];
  availableQuantity: number;
  status: ProductStatus;
  createdAt: Date;
  updatedAt: Date;
}

export interface CreateProductInput {
  productId: string;
  name: string;
  description?: string;
  price: Money;
  category: string;
  tags?: string[];
  initialQuantity: number;
}

export interface UpdateProductInput {
  name?: string;
  description?: string;
  price?: Money;
  category?: string;
  tags?: string[];
  quantityAdjustment?: number;
}

// ---------------------------------------------------------------------------
// Domain Errors
// ---------------------------------------------------------------------------

export class ProductValidationError extends Error {
  public readonly code = 'PRODUCT_VALIDATION_ERROR';

  constructor(message: string) {
    super(message);
    this.name = 'ProductValidationError';
  }
}

export class ProductNotFoundError extends Error {
  public readonly code = 'PRODUCT_NOT_FOUND';
  public readonly productId: string;

  constructor(productId: string) {
    super(`Product not found: ${productId}`);
    this.name = 'ProductNotFoundError';
    this.productId = productId;
  }
}

export class DuplicateSKUError extends Error {
  public readonly code = 'DUPLICATE_SKU';
  public readonly sku: string;

  constructor(sku: string) {
    super(`Duplicate SKU: ${sku}`);
    this.name = 'DuplicateSKUError';
    this.sku = sku;
  }
}

export class InsufficientStockError extends Error {
  public readonly code = 'INSUFFICIENT_STOCK';
  public readonly productId: string;
  public readonly available: number;
  public readonly requested: number;

  constructor(productId: string, available: number, requested: number) {
    super(
      `Insufficient stock for product ${productId}: available=${available}, requested=${requested}`
    );
    this.name = 'InsufficientStockError';
    this.productId = productId;
    this.available = available;
    this.requested = requested;
  }
}

export class ProductHasActiveOrdersError extends Error {
  public readonly code = 'PRODUCT_HAS_ACTIVE_ORDERS';
  public readonly productId: string;

  constructor(productId: string) {
    super(`Cannot hard-delete product ${productId}: active orders exist`);
    this.name = 'ProductHasActiveOrdersError';
    this.productId = productId;
  }
}

export class DeleteNotAuthorizedError extends Error {
  public readonly code = 'DELETE_NOT_AUTHORIZED';
  public readonly productId: string;

  constructor(productId: string) {
    super(`Not authorized to delete product ${productId}`);
    this.name = 'DeleteNotAuthorizedError';
    this.productId = productId;
  }
}

export class SearchIndexUnavailableError extends Error {
  public readonly code = 'SEARCH_INDEX_UNAVAILABLE';

  constructor(message = 'Search index is currently unavailable') {
    super(message);
    this.name = 'SearchIndexUnavailableError';
  }
}

export class InvalidQueryError extends Error {
  public readonly code = 'INVALID_QUERY';

  constructor(message: string) {
    super(message);
    this.name = 'InvalidQueryError';
  }
}
