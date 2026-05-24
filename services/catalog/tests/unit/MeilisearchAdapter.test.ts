import { describe, it, expect, jest, beforeEach } from '@jest/globals';
import { MeilisearchAdapter } from '../../src/adapters/outbound/search/MeilisearchAdapter';
import { MeiliSearch } from 'meilisearch';
import { SortBy } from '../../src/domain/ports/inbound/SearchCatalog';
import { ProductStatus } from '../../src/domain/models';

jest.mock('meilisearch');

describe('MeilisearchAdapter', () => {
  let adapter: MeilisearchAdapter;
  let mockIndex: any;
  let mockClient: any;

  const config = {
    host: 'http://localhost:7700',
    apiKey: 'masterKey',
    indexName: 'products',
  };

  beforeEach(() => {
    mockIndex = {
      search: jest.fn<any>().mockResolvedValue({
        hits: [],
        totalHits: 0,
        page: 1,
        totalPages: 1,
        facetDistribution: {},
      }),
      updateFilterableAttributes: jest.fn<any>().mockResolvedValue({ taskUid: 1 }),
      updateSortableAttributes: jest.fn<any>().mockResolvedValue({ taskUid: 2 }),
      updateSearchableAttributes: jest.fn<any>().mockResolvedValue({ taskUid: 3 }),
    };

    mockClient = {
      index: jest.fn<any>().mockReturnValue(mockIndex),
      createIndex: jest.fn<any>().mockResolvedValue({ taskUid: 0 }),
      waitForTask: jest.fn<any>().mockResolvedValue({ status: 'succeeded' }),
      health: jest.fn<any>().mockResolvedValue({ status: 'available' }),
    };

    (MeiliSearch as unknown as jest.Mock).mockReturnValue(mockClient);

    adapter = new MeilisearchAdapter(config);
  });

  describe('search filter injection', () => {
    it('escapes double quotes in categories to prevent filter injection', async () => {
      const maliciousCategory = 'electronics" OR status = "PRODUCT_STATUS_INACTIVE';
      const escapedCategory = 'electronics\\" OR status = \\"PRODUCT_STATUS_INACTIVE';

      await adapter.search({
        query: 'test',
        filters: {
          categories: [maliciousCategory],
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
            `(category = "${escapedCategory}")`,
          ]),
        })
      );
    });

    it('escapes double quotes in tags to prevent filter injection', async () => {
      const maliciousTag = 'sale" OR availableQuantity = 0';
      const escapedTag = 'sale\\" OR availableQuantity = 0';

      await adapter.search({
        query: 'test',
        filters: {
          tags: [maliciousTag],
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
            `(tags = "${escapedTag}")`,
          ]),
        })
      );
    });

    it('escapes backslashes to prevent escape-the-escape bypass', async () => {
      const maliciousTag = 'sale\\"; OR status = "ACTIVE';
      // Expected: backslash is escaped first, then the quote is escaped.
      const escapedTag = 'sale\\\\\\"; OR status = \\"ACTIVE';

      await adapter.search({
        query: 'test',
        filters: {
          tags: [maliciousTag],
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
            `(tags = "${escapedTag}")`,
          ]),
        })
      );
    });
  });
});
