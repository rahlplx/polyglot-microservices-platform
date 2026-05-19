/**
 * MeilisearchAdapter Unit Tests
 *
 * Focuses on testing the MeilisearchAdapter in isolation, specifically
 * the filter building and escaping logic.
 */

import { describe, it, expect, jest, beforeEach } from '@jest/globals';
import { MeilisearchAdapter } from '../../src/adapters/outbound/search/MeilisearchAdapter';
import { SortBy } from '../../src/domain/ports/inbound/SearchCatalog';

// Mock Meilisearch client
const mockSearch = jest.fn();
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
      // @ts-ignore
      createIndex: jest.fn().mockResolvedValue({ taskUid: 1 }),
      // @ts-ignore
      waitForTask: jest.fn().mockResolvedValue({ status: 'succeeded' }),
      // @ts-ignore
      health: jest.fn().mockResolvedValue({ status: 'available' }),
    })),
  };
});

describe('MeilisearchAdapter', () => {
  let adapter: MeilisearchAdapter;

  beforeEach(() => {
    jest.clearAllMocks();
    adapter = new MeilisearchAdapter({
      host: 'http://localhost:7700',
      apiKey: 'test-key',
      indexName: 'products',
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (adapter as any).indexInitialized = true;
  });

  describe('search', () => {
    it('should escape double quotes in filters', async () => {
      // @ts-ignore
      mockSearch.mockResolvedValue({
        hits: [],
        totalHits: 0,
        page: 1,
        totalPages: 0,
      });

      await adapter.search({
        query: 'test',
        filters: {
          categories: ['electronics" OR status = "ACTIVE'],
          tags: ['sale" OR status = "ACTIVE'],
        },
        pageSize: 20,
        pageToken: '',
        sortBy: SortBy.RELEVANCE,
        facetFields: [],
      });

      expect(mockSearch).toHaveBeenCalledWith(
        'test',
        expect.objectContaining({
          filter: [
            'status = "PRODUCT_STATUS_ACTIVE"',
            '(category = "electronics\\" OR status = \\"ACTIVE")',
            '(tags = "sale\\" OR status = \\"ACTIVE")',
          ],
        })
      );
    });

    it('should escape backslashes in filters', async () => {
      // @ts-ignore
      mockSearch.mockResolvedValue({
        hits: [],
        totalHits: 0,
        page: 1,
        totalPages: 0,
      });

      await adapter.search({
        query: 'test',
        filters: {
          categories: ['cat\\'],
        },
        pageSize: 20,
        pageToken: '',
        sortBy: SortBy.RELEVANCE,
        facetFields: [],
      });

      expect(mockSearch).toHaveBeenCalledWith(
        'test',
        expect.objectContaining({
          filter: [
            'status = "PRODUCT_STATUS_ACTIVE"',
            '(category = "cat\\\\")',
          ],
        })
      );
    });
  });
});
