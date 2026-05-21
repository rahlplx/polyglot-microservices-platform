import { describe, it, expect, jest, beforeEach } from '@jest/globals';
import { MeilisearchAdapter } from '../../src/adapters/outbound/search/MeilisearchAdapter';

// Mock MeiliSearch client
const mockSearch = jest.fn();
const mockIndex = {
  search: mockSearch,
  updateFilterableAttributes: jest.fn(),
  updateSortableAttributes: jest.fn(),
  updateSearchableAttributes: jest.fn(),
  addDocuments: jest.fn(),
  deleteDocument: jest.fn(),
};

jest.mock('meilisearch', () => {
  return {
    MeiliSearch: jest.fn().mockImplementation(() => ({
      index: jest.fn().mockReturnValue(mockIndex),
      createIndex: jest.fn().mockImplementation(() => Promise.resolve({ taskUid: 0 })),
      waitForTask: jest.fn().mockImplementation(() => Promise.resolve({ status: 'succeeded' })),
    })),
  };
});

describe('MeilisearchAdapter - Security', () => {
  let adapter: MeilisearchAdapter;

  beforeEach(() => {
    jest.clearAllMocks();
    (mockSearch as any).mockResolvedValue({
      hits: [],
      totalHits: 0,
      page: 1,
      totalPages: 1,
    });
    (mockIndex.updateFilterableAttributes as any).mockResolvedValue({ taskUid: 1 });
    (mockIndex.updateSortableAttributes as any).mockResolvedValue({ taskUid: 2 });
    (mockIndex.updateSearchableAttributes as any).mockResolvedValue({ taskUid: 3 });

    adapter = new MeilisearchAdapter({
      host: 'http://localhost:7700',
      apiKey: 'test-key',
      indexName: 'products',
    });
  });

  it('should escape double quotes in category filters to prevent injection', async () => {
    const maliciousCategory = 'electronics" OR status = "INACTIVE';

    await adapter.search({
      query: 'phone',
      filters: {
        categories: [maliciousCategory],
        inStockOnly: false,
      },
      pageSize: 20,
      pageToken: '',
      sortBy: 'relevance' as any,
      facetFields: [],
    });

    // Get the filters passed to Meilisearch
    const searchParams = (mockSearch as any).mock.calls[0][1];
    const filters = searchParams.filter;

    // Check if the malicious injection succeeded in creating a top-level OR condition or breaking the quote
    const categoryFilter = (filters as string[]).find((f: string) => f.includes('category ='));

    // Should be correctly escaped
    const escaped = maliciousCategory.replace(/"/g, '\\"');
    expect(categoryFilter).toBe(`(category = "${escaped}")`);
  });

  it('should escape backslashes in tag filters', async () => {
    const maliciousTag = 'tag\\") OR status = \\"INACTIVE';

    await adapter.search({
      query: 'phone',
      filters: {
        tags: [maliciousTag],
        inStockOnly: false,
      },
      pageSize: 20,
      pageToken: '',
      sortBy: 'relevance' as any,
      facetFields: [],
    });

    const searchParams = (mockSearch as any).mock.calls[0][1];
    const filters = searchParams.filter;
    const tagFilter = (filters as string[]).find((f: string) => f.includes('tags ='));

    const escaped = maliciousTag.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    expect(tagFilter).toBe(`(tags = "${escaped}")`);
  });
});
