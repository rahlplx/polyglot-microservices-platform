/**
 * Meilisearch Search Index Adapter
 *
 * Implements the SearchIndex outbound port using the Meilisearch client.
 * Handles product indexing, full-text search with filters, faceting,
 * and autocomplete suggestions.
 */
import { MeiliSearch, type Index, type SearchResponse } from 'meilisearch';
import type {
  SearchIndex,
  SearchQuery,
  SearchResultItem,
  SearchIndexResult,
} from '../../../domain/ports/outbound/SearchIndex';
import type { Product } from '../../../domain/models';
import { Money, ProductStatus, SearchIndexUnavailableError } from '../../../domain/models';
import { SortBy } from '../../../domain/ports/inbound/SearchCatalog';
import type { FacetValue } from '../../../domain/ports/inbound/SearchCatalog';

// ---------------------------------------------------------------------------
// Flattened document shape stored in Meilisearch
// (Money is denormalized into priceUnits/priceNanos/currencyCode for
//  filterable/sortable attribute support)
// ---------------------------------------------------------------------------

interface MeilisearchDocument {
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
// V-13 fix: Adapter-local search document type (was previously in domain port).
// This is the technology-neutral view of an indexed document that the adapter
// uses internally. It is NOT part of the domain port — the port accepts
// `Product` directly and returns `SearchIndexResult`.
// ---------------------------------------------------------------------------

interface AdapterSearchDocument {
  readonly productId: string;
  readonly name: string;
  readonly description: string;
  readonly category: string;
  readonly tags: string[];
  readonly price: Money;
  readonly availableQuantity: number;
  readonly status: string;
  readonly createdAt: string;
}

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export interface MeilisearchConfig {
  readonly host: string;
  readonly apiKey: string;
  readonly indexName: string;
}

// ---------------------------------------------------------------------------
// Adapter Implementation
// ---------------------------------------------------------------------------

export class MeilisearchAdapter implements SearchIndex {
  private readonly client: MeiliSearch;
  private readonly indexName: string;
  private indexInitialized = false;

  constructor(config: MeilisearchConfig) {
    this.client = new MeiliSearch({
      host: config.host,
      apiKey: config.apiKey,
    });
    this.indexName = config.indexName;
  }

  // -------------------------------------------------------------------------
  // Public API
  // -------------------------------------------------------------------------

  async index(product: Product): Promise<void> {
    const idx = await this.getIndex();
    const doc = this.toMeilisearchDocument(product);
    await idx.addDocuments([doc], { primaryKey: 'productId' });
  }

  async bulkIndex(products: Product[]): Promise<void> {
    if (products.length === 0) {
      return;
    }
    const idx = await this.getIndex();
    const docs = products.map((p) => this.toMeilisearchDocument(p));
    // Batch in groups of 500 for balanced indexing
    const batchSize = 500;
    for (let i = 0; i < docs.length; i += batchSize) {
      const batch = docs.slice(i, i + batchSize);
      await idx.addDocuments(batch, { primaryKey: 'productId' });
    }
  }

  async search(query: SearchQuery): Promise<SearchIndexResult> {
    try {
      const idx = await this.getIndex();

      // Build Meilisearch filter expressions
      const filters = this.buildFilters(query.filters);
      const sort = this.buildSort(query.sortBy);

      const searchParams: Record<string, unknown> = {
        q: query.query,
        filter: filters.length > 0 ? filters : undefined,
        sort: sort.length > 0 ? sort : undefined,
        hitsPerPage: query.pageSize,
        page: query.pageToken ? this.decodePageToken(query.pageToken) : 1,
        attributesToRetrieve: [
          'productId', 'name', 'description', 'category', 'tags',
          'priceUnits', 'priceNanos', 'currencyCode', 'availableQuantity', 'status',
        ],
        attributesToCrop: ['description'],
        cropLength: 200,
        facets: query.facetFields.length > 0 ? query.facetFields : undefined,
      };

      const response: SearchResponse<MeilisearchDocument> = await idx.search(
        query.query,
        searchParams
      );

      return this.toSearchResult(response, query.facetFields);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown search error';
      throw new SearchIndexUnavailableError(
        `Meilisearch search failed: ${message}`
      );
    }
  }

  async delete(productId: string): Promise<void> {
    const idx = await this.getIndex();
    await idx.deleteDocument(productId);
  }

  async refresh(): Promise<void> {
    // Meilisearch auto-refreshes; this is a no-op for API compatibility
  }

  async suggest(prefix: string, maxSuggestions: number): Promise<string[]> {
    try {
      const idx = await this.getIndex();
      const response = await idx.search(prefix, {
        limit: maxSuggestions,
        attributesToRetrieve: ['name'],
      });
      return response.hits.map((hit) => hit.name);
    } catch {
      return [];
    }
  }

  // -------------------------------------------------------------------------
  // Connection Management
  // -------------------------------------------------------------------------

  async ping(): Promise<boolean> {
    try {
      await this.client.health();
      return true;
    } catch {
      return false;
    }
  }

  // -------------------------------------------------------------------------
  // Private Helpers
  // -------------------------------------------------------------------------

  private async getIndex(): Promise<Index<MeilisearchDocument>> {
    if (!this.indexInitialized) {
      const task = await this.client.createIndex(this.indexName, {
        primaryKey: 'productId',
      });
      await this.client.waitForTask(task.taskUid);

      const idx = this.client.index<MeilisearchDocument>(this.indexName);

      // Configure filterable and sortable attributes
      await idx.updateFilterableAttributes([
        'category', 'tags', 'status', 'currencyCode', 'availableQuantity',
      ]);
      await idx.updateSortableAttributes([
        'priceUnits', 'createdAt', 'name',
      ]);
      await idx.updateSearchableAttributes([
        'name', 'description', 'category', 'tags',
      ]);

      this.indexInitialized = true;
    }

    return this.client.index<MeilisearchDocument>(this.indexName);
  }

  private buildFilters(filters: SearchQuery['filters']): string[] {
    const conditions: string[] = [];

    // Only show active products
    conditions.push(`status = "${ProductStatus.ACTIVE}"`);

    if (filters.categories && filters.categories.length > 0) {
      const categoryFilters = filters.categories.map(
        (c) => `category = "${this.escapeFilterValue(c)}"`
      );
      conditions.push(`(${categoryFilters.join(' OR ')})`);
    }

    if (filters.tags && filters.tags.length > 0) {
      const tagFilters = filters.tags.map(
        (t) => `tags = "${this.escapeFilterValue(t)}"`
      );
      conditions.push(`(${tagFilters.join(' OR ')})`);
    }

    if (filters.priceRange) {
      conditions.push(
        `priceUnits >= ${filters.priceRange.min.units}`
      );
      conditions.push(
        `priceUnits <= ${filters.priceRange.max.units}`
      );
    }

    if (filters.inStockOnly) {
      conditions.push('availableQuantity > 0');
    }

    return conditions;
  }

  private buildSort(sortBy: SortBy): string[] {
    switch (sortBy) {
      case SortBy.PRICE_ASC:
        return ['priceUnits:asc'];
      case SortBy.PRICE_DESC:
        return ['priceUnits:desc'];
      case SortBy.CREATED_AT:
        return ['createdAt:desc'];
      case SortBy.POPULARITY:
        // Popularity not directly supported; fall back to relevance
        return [];
      case SortBy.RELEVANCE:
      default:
        return [];
    }
  }

  /**
   * Escape special characters in filter values to prevent injection.
   * Meilisearch filters use double quotes for strings, so we must
   * escape backslashes and double quotes.
   */
  private escapeFilterValue(value: string): string {
    return value.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  }

  /**
   * Convert a Product domain entity to a flattened Meilisearch document.
   * The Money value object is denormalized into separate fields so that
   * Meilisearch can filter/sort on priceUnits and currencyCode independently.
   */
  private toMeilisearchDocument(product: Product): MeilisearchDocument {
    return {
      productId: product.productId,
      name: product.name,
      description: product.description,
      category: product.category,
      tags: [...product.tags],
      priceUnits: product.price.units,
      priceNanos: product.price.nanos,
      currencyCode: product.price.currencyCode,
      availableQuantity: product.availableQuantity,
      status: product.status,
      createdAt: product.createdAt.toISOString(),
    };
  }

  /**
   * Reconstruct a domain-compatible search result from a flattened
   * Meilisearch hit, reassembling the Money value object from the
   * denormalized fields. (V-13: SearchDocument moved to adapter-local type.)
   */
  private toSearchDocument(hit: MeilisearchDocument): AdapterSearchDocument {
    return {
      productId: hit.productId,
      name: hit.name,
      description: hit.description,
      category: hit.category,
      tags: hit.tags,
      price: Money.create(hit.currencyCode, hit.priceUnits, hit.priceNanos),
      availableQuantity: hit.availableQuantity,
      status: hit.status,
      createdAt: hit.createdAt,
    };
  }

  private toSearchResult(
    response: SearchResponse<MeilisearchDocument>,
    facetFields: string[]
  ): SearchIndexResult {
    const results: SearchResultItem[] = response.hits.map((hit) => ({
      productId: hit.productId,
      name: hit.name,
      descriptionSnippet: hit.description?.slice(0, 200) ?? '',
      price: Money.create(hit.currencyCode, hit.priceUnits, hit.priceNanos),
      relevanceScore: hit._rankingScore ?? 0,
    }));

    // Extract facets from Meilisearch facetDistribution
    const facets: Record<string, FacetValue[]> = {};
    if (response.facetDistribution && facetFields.length > 0) {
      for (const field of facetFields) {
        const distribution = response.facetDistribution[field];
        if (distribution) {
          facets[field] = Object.entries(distribution).map(
            ([value, count]) => ({
              value,
              count: count as number,
            })
          );
        }
      }
    }

    const page = response.page ?? 1;
    const totalPages = response.totalPages ?? 1;
    const nextPageToken = page < totalPages
      ? this.encodePageToken(page + 1)
      : '';

    return {
      results,
      totalCount: response.totalHits ?? 0,
      nextPageToken,
      facets,
      suggestions: [],
    };
  }

  private encodePageToken(page: number): string {
    return Buffer.from(JSON.stringify({ page })).toString('base64');
  }

  private decodePageToken(token: string): number {
    try {
      const decoded = JSON.parse(Buffer.from(token, 'base64').toString('utf-8'));
      return typeof decoded.page === 'number' ? decoded.page : 1;
    } catch {
      return 1;
    }
  }
}
