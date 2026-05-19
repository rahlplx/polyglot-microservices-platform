/**
 * Domain Models - Public API
 *
 * Re-exports all domain model types and value objects.
 * Domain core has ZERO external dependencies.
 */
export { Money, MoneyValidationError } from './Money';
export {
  Product,
  ProductStatus,
  DeleteReason,
  ProductNotFoundError,
  DuplicateSKUError,
  InsufficientStockError,
  ProductHasActiveOrdersError,
  DeleteNotAuthorizedError,
  SearchIndexUnavailableError,
  InvalidQueryError,
  ProductValidationError,
} from './Product';
export type { ProductProps, CreateProductInput, UpdateProductInput } from './Product';
