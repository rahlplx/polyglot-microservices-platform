import { describe, it, expect, jest, beforeEach } from '@jest/globals';
import { MeilisearchAdapter } from '@adapters/outbound/search/MeilisearchAdapter';

// Mock Meilisearch
const mockSearch = jest.fn();
const mockIndex = {
  search: mockSearch,
  updateFilterableAttributes: jest.fn().mockResolvedValue({} as any),
  updateSortableAttributes: jest.fn().mockResolvedValue({} as any),
  updateSearchableAttributes: jest.fn().mockResolvedValue({} as any),
};

jest.mock('meilisearch', () => {
  return {
    MeiliSearch: jest.fn().mockImplementation(() => ({
      index: jest.fn().mockReturnValue(mockIndex),
      createIndex: jest.fn().mockResolvedValue({ taskUid: 1 } as any),
      waitForTask: jest.fn().mockResolvedValue({ status: 'succeeded' } as any),
      health: jest.fn().mockResolvedValue({ status: 'available' } as any),
    })),
  };
});

describe('MeilisearchAdapter Security', () => {
  let adapter: MeilisearchAdapter;

  beforeEach(() => {
    jest.clearAllMocks();
    adapter = new MeilisearchAdapter({
      host: 'http://localhost:7700',
      apiKey: 'test-key',
      indexName: 'products',
    });
  });

  it('should escape double quotes in category filters to prevent injection', async () => {
    const maliciousCategory = 'electronics" OR status = "DISCONTINUED';

    mockSearch.mockResolvedValue({
      hits: [],
      totalHits: 0,
      processingTimeMs: 1,
      query: '',
    } as any);

    await adapter.search({
      query: 'test',
      filters: {
        categories: [maliciousCategory],
      },
      pageSize: 20,
      pageToken: '',
      sortBy: 0 as any, // SortBy.RELEVANCE
      facetFields: [],
    });

    expect(mockSearch).toHaveBeenCalledWith(
      'test',
      expect.objectContaining({
        filter: expect.arrayContaining([
          expect.stringContaining(`category = "electronics\\" OR status = \\"DISCONTINUED"`)
        ]),
      })
    );
  });

  it('should escape backslashes in category filters', async () => {
    const maliciousCategory = 'some\\category';

    mockSearch.mockResolvedValue({
      hits: [],
      totalHits: 0,
      processingTimeMs: 1,
      query: '',
    } as any);

    await adapter.search({
      query: 'test',
      filters: {
        categories: [maliciousCategory],
      },
      pageSize: 20,
      pageToken: '',
      sortBy: 0 as any, // SortBy.RELEVANCE
      facetFields: [],
    });

    expect(mockSearch).toHaveBeenCalledWith(
      'test',
      expect.objectContaining({
        filter: expect.arrayContaining([
          expect.stringContaining(`category = "some\\\\category"`)
        ]),
      })
    );
  });

  it('should escape double quotes in tag filters', async () => {
    const maliciousTag = 'tag" OR status = "DISCONTINUED';

    mockSearch.mockResolvedValue({
      hits: [],
      totalHits: 0,
      processingTimeMs: 1,
      query: '',
    } as any);

    await adapter.search({
      query: 'test',
      filters: {
        tags: [maliciousTag],
      },
      pageSize: 20,
      pageToken: '',
      sortBy: 0 as any, // SortBy.RELEVANCE
      facetFields: [],
    });

    expect(mockSearch).toHaveBeenCalledWith(
      'test',
      expect.objectContaining({
        filter: expect.arrayContaining([
          expect.stringContaining(`tags = "tag\\" OR status = \\"DISCONTINUED"`)
        ]),
      })
    );
  });
});
