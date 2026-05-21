/**
 * Inbound Ports - Public API
 *
 * Re-exports all inbound (driving) port interfaces.
 * Domain core has ZERO external dependencies.
 */
export { CreateProduct, type CreateProductRequest, type CreateProductResponse, type CreateProductError } from './CreateProduct';
export { GetProduct, type GetProductRequest, type GetProductResponse, type GetProductError } from './GetProduct';
export {
  SearchCatalog,
  type SearchCatalogRequest,
  type SearchCatalogResponse,
  type SearchCatalogError,
  type SearchFilters,
  type ProductSummary,
  type FacetValue,
  SortBy,
} from './SearchCatalog';
export { DeleteProduct, type DeleteProductRequest, type DeleteProductResponse, type DeleteProductError } from './DeleteProduct';
