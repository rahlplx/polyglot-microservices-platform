import { describe, it, expect, jest, beforeEach } from '@jest/globals';
import { MeilisearchAdapter } from '../../src/adapters/outbound/search/MeilisearchAdapter';
import { SortBy } from '../../src/domain/ports/inbound/SearchCatalog';

// Mock Meilisearch client
const mockSearch = jest.fn<any>();
const mockCreateIndex = jest.fn<any>();
const mockWaitForTask = jest.fn<any>();
const mockUpdateFilterableAttributes = jest.fn<any>();
const mockUpdateSortableAttributes = jest.fn<any>();
const mockUpdateSearchableAttributes = jest.fn<any>();

jest.mock('meilisearch', () => {
  return {
    MeiliSearch: jest.fn().mockImplementation(() => ({
      index: jest.fn().mockReturnValue({
        search: mockSearch,
        updateFilterableAttributes: mockUpdateFilterableAttributes,
        updateSortableAttributes: mockUpdateSortableAttributes,
        updateSearchableAttributes: mockUpdateSearchableAttributes,
      }),
      createIndex: mockCreateIndex,
      waitForTask: mockWaitForTask,
    })),
  };
});

describe('MeilisearchAdapter Security', () => {
  let adapter: MeilisearchAdapter;

  beforeEach(() => {
    jest.clearAllMocks();
    mockCreateIndex.mockResolvedValue({ taskUid: 1 });
    mockWaitForTask.mockResolvedValue({});
    mockSearch.mockResolvedValue({
      hits: [],
      totalHits: 0,
      page: 1,
      totalPages: 1,
    });

    adapter = new MeilisearchAdapter({
      host: 'http://localhost:7700',
      apiKey: 'test-key',
      indexName: 'products',
    });
  });

  it('should escape double quotes in category filters to prevent injection', async () => {
    const maliciousCategory = 'electronics" OR status = "PRODUCT_STATUS_DISCONTINUED';

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

    expect(mockSearch).toHaveBeenCalledWith(
      'test',
      expect.objectContaining({
        filter: expect.arrayContaining([
          expect.stringContaining('category = "electronics\\" OR status = \\"PRODUCT_STATUS_DISCONTINUED"')
        ]),
      })
    );
  });

  it('should escape double quotes in tag filters to prevent injection', async () => {
    const maliciousTag = 'premium" OR availableQuantity = 0';

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

    expect(mockSearch).toHaveBeenCalledWith(
      'test',
      expect.objectContaining({
        filter: expect.arrayContaining([
          expect.stringContaining('tags = "premium\\" OR availableQuantity = 0"')
        ]),
      })
    );
  });

  it('should escape backslashes in filter values', async () => {
    const valueWithBackslash = 'test\\value';

    await adapter.search({
      query: 'test',
      filters: {
        categories: [valueWithBackslash],
      },
      pageSize: 20,
      pageToken: '',
      sortBy: SortBy.RELEVANCE,
      facetFields: [],
    });

    expect(mockSearch).toHaveBeenCalledWith(
      'test',
      expect.objectContaining({
        filter: expect.arrayContaining([
          expect.stringContaining('category = "test\\\\value"')
        ]),
      })
    );
  });
});
