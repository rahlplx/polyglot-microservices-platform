import { describe, it, expect, jest, beforeEach } from '@jest/globals';
import { MeilisearchAdapter } from '../../../../../src/adapters/outbound/search/MeilisearchAdapter';
import { SortBy } from '../../../../../src/domain/ports/inbound/SearchCatalog';

jest.mock('meilisearch', () => {
  const mIndex = {
    search: jest.fn(),
    createIndex: jest.fn(),
    waitForTask: jest.fn(),
    updateFilterableAttributes: jest.fn(),
    updateSortableAttributes: jest.fn(),
    updateSearchableAttributes: jest.fn(),
    deleteDocument: jest.fn(),
  };
  return {
    MeiliSearch: jest.fn(() => ({
      index: jest.fn(() => mIndex),
      createIndex: jest.fn(async () => ({ taskUid: 1 })),
      waitForTask: jest.fn(async () => ({ status: 'succeeded' })),
      health: jest.fn(async () => ({ status: 'available' })),
    })),
  };
});

describe('MeilisearchAdapter Security', () => {
  let adapter: MeilisearchAdapter;
  let mockIndex: any;

  beforeEach(() => {
    jest.clearAllMocks();
    adapter = new MeilisearchAdapter({
      host: 'http://localhost:7700',
      apiKey: 'masterKey',
      indexName: 'products',
    });
    // @ts-ignore - access private client to get the mock index
    mockIndex = adapter.client.index();
    mockIndex.search.mockResolvedValue({
      hits: [],
      totalHits: 0,
      processingTimeMs: 1,
      query: '',
    });
  });

  it('should escape filter values to prevent filter injection', async () => {
    const maliciousCategory = 'electronics" OR status = "INACTIVE';

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

    const searchParams = mockIndex.search.mock.calls[0][1];
    const filter = searchParams.filter;

    // The filter is an array of strings
    // We expect the malicious category to be escaped.

    expect(filter).toContain(`(category = "electronics\\" OR status = \\"INACTIVE")`);
  });

  it('should escape backslashes in filter values', async () => {
    const maliciousTag = 'tag\\"; OR status = \\"INACTIVE';

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

    const searchParams = mockIndex.search.mock.calls[0][1];
    const filter = searchParams.filter;

    expect(filter).toContain(`(tags = "tag\\\\\\"; OR status = \\\\\\"INACTIVE")`);
  });
});
