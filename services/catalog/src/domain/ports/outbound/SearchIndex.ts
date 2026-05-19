/**
 * SearchIndex Outbound Port (Driven)
 *
 * Defines the interface for indexing and searching products
 * via a full-text search engine (e.g., Meilisearch, Elasticsearch).
 * This is a driven port — adapters on the outbound side implement this interface.
 *
 * Domain core has ZERO external dependencies.
 */
import type { Product } from '../../models';
import type { SearchFilters, SortBy, FacetValue } from '../inbound/SearchCatalog';

// ---------------------------------------------------------------------------
// Search Document (what gets indexed)
// ---------------------------------------------------------------------------

export interface SearchDocument {
  readonly productId: string;
  readonly name: string;
  readonly description: string;
  readonly category: string;
  readonly tags: string[];
  readonly priceUnits: number;
  readonly priceNanos: number;
  readonly currencyCode: string;
  readonly availableQuantity: number;
  readonly status: string;
  readonly createdAt: string;
}

// ---------------------------------------------------------------------------
// Search Query
// ---------------------------------------------------------------------------

export interface SearchQuery {
  readonly query: string;
  readonly filters: SearchFilters;
  readonly pageSize: number;
  readonly pageToken: string;
  readonly sortBy: SortBy;
  readonly facetFields: string[];
}

// ---------------------------------------------------------------------------
// Search Result
// ---------------------------------------------------------------------------

export interface SearchResultItem {
  readonly productId: string;
  readonly name: string;
  readonly descriptionSnippet: string;
  readonly price: { readonly currencyCode: string; readonly units: number; readonly nanos: number };
  readonly relevanceScore: number;
}

export interface SearchIndexResult {
  readonly results: SearchResultItem[];
  readonly totalCount: number;
  readonly nextPageToken: string;
  readonly facets: Readonly<Record<string, FacetValue[]>>;
  readonly suggestions: string[];
}

// ---------------------------------------------------------------------------
// Port Interface
// ---------------------------------------------------------------------------

export interface SearchIndex {
  /**
   * Index or re-index a single product document.
   */
  index(product: Product): Promise<void>;

  /**
   * Batch index multiple products for initial load or bulk updates.
   */
  bulkIndex(products: Product[]): Promise<void>;

  /**
   * Execute a search query with filtering, sorting, and faceting.
   */
  search(query: SearchQuery): Promise<SearchIndexResult>;

  /**
   * Remove a product from the search index.
   */
  delete(productId: string): Promise<void>;

  /**
   * Force a refresh of the search index for near-real-time consistency.
   */
  refresh(): Promise<void>;

  /**
   * Get search suggestions for a prefix (autocomplete).
   */
  suggest(prefix: string, maxSuggestions: number): Promise<string[]>;
}
