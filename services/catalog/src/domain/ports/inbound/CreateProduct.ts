/**
 * CreateProduct Use Case Port (Inbound)
 *
 * Defines the interface for creating a new product in the catalog.
 * This is a driving port — adapters on the inbound side call this use case.
 *
 * Domain core has ZERO external dependencies.
 */
import type { Product, CreateProductInput, DuplicateSKUError, ProductValidationError } from '../../models';

export interface CreateProductRequest {
  readonly name: string;
  readonly description: string;
  readonly price: {
    readonly currencyCode: string;
    readonly units: number;
    readonly nanos: number;
  };
  readonly category: string;
  readonly tags: string[];
  readonly initialQuantity: number;
}

export interface CreateProductResponse {
  readonly product: Product;
}

export type CreateProductError =
  | DuplicateSKUError
  | ProductValidationError
  | { readonly code: 'INVALID_CATEGORY'; readonly message: string }
  | { readonly code: 'UNAUTHORIZED'; readonly message: string };

export interface CreateProduct {
  execute(request: CreateProductRequest): Promise<CreateProductResponse>;
}

export type { CreateProductInput, Product };
