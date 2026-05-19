/**
 * Outbound Ports - Public API
 *
 * Re-exports all outbound (driven) port interfaces.
 * Domain core has ZERO external dependencies.
 */
export {
  ProductRepository,
  type ProductRow,
  type PaginatedResult,
  type ListProductsFilter,
} from './ProductRepository';

export {
  SearchIndex,
  type SearchDocument,
  type SearchQuery,
  type SearchResultItem,
  type SearchIndexResult,
} from './SearchIndex';
