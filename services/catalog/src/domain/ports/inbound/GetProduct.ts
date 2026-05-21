/**
 * GetProduct Use Case Port (Inbound)
 *
 * Defines the interface for retrieving a product by its ID.
 * This is a driving port — adapters on the inbound side call this use case.
 *
 * Domain core has ZERO external dependencies.
 */
import type { Product, ProductNotFoundError } from '../../models';

export interface GetProductRequest {
  readonly productId: string;
  readonly includeVariants?: boolean;
  readonly includeInventory?: boolean;
}

export interface GetProductResponse {
  readonly product: Product;
}

export type GetProductError =
  | ProductNotFoundError
  | { readonly code: 'PRODUCT_SUSPENDED'; readonly message: string; readonly productId: string };

export interface GetProduct {
  execute(request: GetProductRequest): Promise<GetProductResponse>;
}
