import { describe, it, expect, beforeEach, jest } from '@jest/globals';
import { MeilisearchAdapter } from '../../src/adapters/outbound/search/MeilisearchAdapter';
import type { SearchQuery } from '../../src/domain/ports/outbound/SearchIndex';
import { SortBy } from '../../src/domain/ports/inbound/SearchCatalog';

// Mock the meilisearch client
const mockSearch = jest.fn() as any;
const mockIndex = {
  search: mockSearch,
  addDocuments: jest.fn(),
  deleteDocument: jest.fn(),
  updateFilterableAttributes: jest.fn(),
  updateSortableAttributes: jest.fn(),
  updateSearchableAttributes: jest.fn(),
};

jest.mock('meilisearch', () => {
  return {
    MeiliSearch: jest.fn().mockImplementation(() => ({
      index: jest.fn().mockReturnValue(mockIndex),
      createIndex: jest.fn().mockReturnValue({ then: (cb: any) => cb({ taskUid: 1 }) }),
      waitForTask: jest.fn().mockReturnValue({ then: (cb: any) => cb({ status: 'succeeded' }) }),
    })),
  };
});

describe('MeilisearchAdapter', () => {
  let adapter: MeilisearchAdapter;

  beforeEach(() => {
    jest.clearAllMocks();
    adapter = new MeilisearchAdapter({
      host: 'http://localhost:7700',
      apiKey: 'masterKey',
      indexName: 'products',
    });
    // Mark as initialized to avoid calling createIndex/waitForTask in every test
    (adapter as any).indexInitialized = true;
  });

  describe('search', () => {
    it('should properly escape special characters in filters through the public API', async () => {
      const query: SearchQuery = {
        query: 'test',
        filters: {
          categories: ['electronics"', 'back\\slash'],
          tags: ['tag"injection'],
        },
        pageSize: 10,
        pageToken: '',
        sortBy: SortBy.RELEVANCE,
        facetFields: [],
      };

      mockSearch.mockResolvedValue({
        hits: [],
        totalHits: 0,
        processingTimeMs: 1,
        query: 'test',
      });

      await adapter.search(query);

      expect(mockSearch).toHaveBeenCalledWith(
        'test',
        expect.objectContaining({
          filter: [
            'status = "PRODUCT_STATUS_ACTIVE"',
            '(category = "electronics\\"" OR category = "back\\\\slash")',
            '(tags = "tag\\"injection")',
          ],
        })
      );
    });

    it('should handle multiple categories and tags with escaping', async () => {
      const query: SearchQuery = {
        query: 'test',
        filters: {
          categories: ['cat1', 'cat"2'],
          tags: ['tag1', 'tag\\2'],
        },
        pageSize: 10,
        pageToken: '',
        sortBy: SortBy.RELEVANCE,
        facetFields: [],
      };

      mockSearch.mockResolvedValue({
        hits: [],
        totalHits: 0,
      });

      await adapter.search(query);

      const searchParams = mockSearch.mock.calls[0][1] as any;
      expect(searchParams.filter).toContain('(category = "cat1" OR category = "cat\\"2")');
      expect(searchParams.filter).toContain('(tags = "tag1" OR tags = "tag\\\\2")');
    });
  });
});
