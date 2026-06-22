import { describe, it, expect, jest, beforeEach } from '@jest/globals';
import { MeilisearchAdapter } from '../../src/adapters/outbound/search/MeilisearchAdapter';
import { SortBy } from '../../src/domain/ports/inbound/SearchCatalog';
import { ProductStatus } from '../../src/domain/models';

// Mock meilisearch
jest.mock('meilisearch', () => {
  const mockIndex = {
    search: jest.fn(),
    updateFilterableAttributes: jest.fn().mockResolvedValue({} as never),
    updateSortableAttributes: jest.fn().mockResolvedValue({} as never),
    updateSearchableAttributes: jest.fn().mockResolvedValue({} as never),
    addDocuments: jest.fn().mockResolvedValue({} as never),
    deleteDocument: jest.fn().mockResolvedValue({} as never),
  };
  return {
    MeiliSearch: jest.fn().mockImplementation(() => ({
      createIndex: jest.fn().mockResolvedValue({ taskUid: '123' } as never),
      waitForTask: jest.fn().mockResolvedValue({ status: 'succeeded' } as never),
      index: jest.fn().mockReturnValue(mockIndex),
      health: jest.fn().mockResolvedValue({ status: 'available' } as never),
    })),
  };
});

import { MeiliSearch } from 'meilisearch';

describe('MeilisearchAdapter Security', () => {
  let adapter: MeilisearchAdapter;
  let mockClient: any;
  let mockIndex: any;

  beforeEach(() => {
    jest.clearAllMocks();
    adapter = new MeilisearchAdapter({
      host: 'http://localhost:7700',
      apiKey: 'masterKey',
      indexName: 'products',
    });
    // @ts-ignore
    mockClient = (MeiliSearch as jest.Mock).mock.results[0].value;
    mockIndex = mockClient.index();
  });

  describe('search filter escaping', () => {
    it('should escape double quotes in category filters to prevent injection', async () => {
      mockIndex.search.mockResolvedValue({
        hits: [],
        totalHits: 0,
        page: 1,
        totalPages: 1,
      });

      await adapter.search({
        query: 'test',
        filters: {
          categories: ['electronics" OR status = "INACTIVE'],
          inStockOnly: false,
        },
        pageSize: 20,
        pageToken: '',
        sortBy: SortBy.RELEVANCE,
        facetFields: [],
      });

      expect(mockIndex.search).toHaveBeenCalledWith(
        'test',
        expect.objectContaining({
          filter: expect.arrayContaining([
            `status = "${ProductStatus.ACTIVE}"`,
            '(category = "electronics\\" OR status = \\"INACTIVE")',
          ]),
        })
      );
    });

    it('should escape backslashes and double quotes in tag filters', async () => {
      mockIndex.search.mockResolvedValue({
        hits: [],
        totalHits: 0,
        page: 1,
        totalPages: 1,
      });

      await adapter.search({
        query: 'test',
        filters: {
          tags: ['special\\tag"'],
          inStockOnly: false,
        },
        pageSize: 20,
        pageToken: '',
        sortBy: SortBy.RELEVANCE,
        facetFields: [],
      });

      expect(mockIndex.search).toHaveBeenCalledWith(
        'test',
        expect.objectContaining({
          filter: expect.arrayContaining([
            '(tags = "special\\\\tag\\"")',
          ]),
        })
      );
    });
  });
});
