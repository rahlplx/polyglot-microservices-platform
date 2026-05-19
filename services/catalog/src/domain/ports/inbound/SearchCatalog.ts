/**
 * SearchCatalog Use Case Port (Inbound)
 *
 * Defines the interface for searching the product catalog with
 * filtering, pagination, sorting, and faceted navigation.
 * This is a driving port — adapters on the inbound side call this use case.
 *
 * Domain core has ZERO external dependencies.
 */
import type { Product, SearchIndexUnavailableError, InvalidQueryError } from '../../models';

// ---------------------------------------------------------------------------
// Sort Options
// ---------------------------------------------------------------------------

export enum SortBy {
  RELEVANCE = 'RELEVANCE',
  PRICE_ASC = 'PRICE_ASC',
  PRICE_DESC = 'PRICE_DESC',
  CREATED_AT = 'CREATED_AT',
  POPULARITY = 'POPULARITY',
}

// ---------------------------------------------------------------------------
// Search Filters
// ---------------------------------------------------------------------------

export interface SearchFilters {
  readonly categories?: string[];
  readonly tags?: string[];
  readonly priceRange?: {
    readonly min: { readonly currencyCode: string; readonly units: number; readonly nanos: number };
    readonly max: { readonly currencyCode: string; readonly units: number; readonly nanos: number };
  };
  readonly inStockOnly?: boolean;
}

// ---------------------------------------------------------------------------
// Facet Value
// ---------------------------------------------------------------------------

export interface FacetValue {
  readonly value: string;
  readonly count: number;
}

// ---------------------------------------------------------------------------
// Search Request / Response
// ---------------------------------------------------------------------------

export interface SearchCatalogRequest {
  readonly query: string;
  readonly filters: SearchFilters;
  readonly pageSize: number;
  readonly pageToken: string;
  readonly sortBy: SortBy;
  readonly facetFields: string[];
}

export interface ProductSummary {
  readonly productId: string;
  readonly name: string;
  readonly descriptionSnippet: string;
  readonly price: { readonly currencyCode: string; readonly units: number; readonly nanos: number };
  readonly relevanceScore: number;
}

export interface SearchCatalogResponse {
  readonly results: ProductSummary[];
  readonly totalCount: number;
  readonly nextPageToken: string;
  readonly facets: Readonly<Record<string, FacetValue[]>>;
  readonly suggestions: string[];
}

export type SearchCatalogError =
  | SearchIndexUnavailableError
  | InvalidQueryError;

export interface SearchCatalog {
  execute(request: SearchCatalogRequest): Promise<SearchCatalogResponse>;
}

export type { Product };
