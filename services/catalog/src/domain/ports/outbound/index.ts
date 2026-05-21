/**
 * Outbound Ports - Public API
 *
 * Re-exports all outbound (driven) port interfaces.
 * Domain core has ZERO external dependencies.
 *
 * V-13 fix: SearchDocument and ProductRow removed — they are adapter
 * concerns, not domain port types.
 */
export {
  ProductRepository,
  type PaginatedResult,
  type ListProductsFilter,
} from './ProductRepository';

export {
  SearchIndex,
  type SearchQuery,
  type SearchResultItem,
  type SearchIndexResult,
} from './SearchIndex';
