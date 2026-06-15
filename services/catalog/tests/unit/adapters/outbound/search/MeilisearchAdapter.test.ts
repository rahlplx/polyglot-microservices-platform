/**
 * MeilisearchAdapter Security Tests
 *
 * Verifies that user input used in Meilisearch filters is correctly escaped
 * to prevent filter injection vulnerabilities.
 */

import { describe, it, expect, jest, beforeEach } from '@jest/globals';
import { MeilisearchAdapter } from '../../../../../src/adapters/outbound/search/MeilisearchAdapter';
import { SortBy } from '../../../../../src/domain/ports/inbound/SearchCatalog';

// Mock the MeiliSearch client
const mockSearch = jest.fn();
const mockIndex = {
  search: mockSearch,
  updateFilterableAttributes: jest.fn(),
  updateSortableAttributes: jest.fn(),
  updateSearchableAttributes: jest.fn(),
};

jest.mock('meilisearch', () => {
  return {
    MeiliSearch: jest.fn().mockImplementation(() => ({
      index: jest.fn().mockReturnValue(mockIndex),
      createIndex: jest.fn(),
      waitForTask: jest.fn(),
    })),
  };
});

describe('MeilisearchAdapter Filter Security', () => {
  let adapter: MeilisearchAdapter;

  beforeEach(() => {
    jest.clearAllMocks();
    (mockIndex.updateFilterableAttributes as any).mockResolvedValue({});
    (mockIndex.updateSortableAttributes as any).mockResolvedValue({});
    (mockIndex.updateSearchableAttributes as any).mockResolvedValue({});

    adapter = new MeilisearchAdapter({
      host: 'http://localhost:7700',
      apiKey: 'masterKey',
      indexName: 'products',
    });
  });

  it('should escape special characters in category filters to prevent injection', async () => {
    const maliciousCategory = 'electronics" OR status = "INACTIVE" OR "a" = "a';

    (mockIndex.search as any).mockResolvedValue({
      hits: [],
      totalHits: 0,
      processingTimeMs: 1,
      query: '',
    });

    // Mock initial indexing setup
    const meiliSearchInstance = (adapter as any).client;
    (meiliSearchInstance.createIndex as any).mockResolvedValue({ taskUid: '123' });
    (meiliSearchInstance.waitForTask as any).mockResolvedValue({ status: 'succeeded' });

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

    const lastCall = (mockIndex.search as any).mock.calls[0];
    const searchParams = lastCall[1] as any;
    const filter = searchParams.filter;

    // The filter should contain the escaped category value
    expect(filter[1]).toContain('category = "electronics\" OR status = \"INACTIVE\" OR \"a\" = \"a"');
  });

  it('should escape special characters in tag filters to prevent injection', async () => {
    const maliciousTag = 'tag" OR status = "INACTIVE';

    (mockIndex.search as any).mockResolvedValue({
      hits: [],
      totalHits: 0,
      processingTimeMs: 1,
      query: '',
    });

    // Mock initial indexing setup
    const meiliSearchInstance = (adapter as any).client;
    (meiliSearchInstance.createIndex as any).mockResolvedValue({ taskUid: '123' });
    (meiliSearchInstance.waitForTask as any).mockResolvedValue({ status: 'succeeded' });

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

    const lastCall = (mockIndex.search as any).mock.calls[0];
    const searchParams = lastCall[1] as any;
    const filter = searchParams.filter;

    expect(filter[1]).toContain('tags = "tag\" OR status = \"INACTIVE"');
  });

  it('should escape backslashes in filters', async () => {
    const categoryWithBackslash = 'category\value';

    (mockIndex.search as any).mockResolvedValue({
      hits: [],
      totalHits: 0,
      processingTimeMs: 1,
      query: '',
    });

    // Mock initial indexing setup
    const meiliSearchInstance = (adapter as any).client;
    (meiliSearchInstance.createIndex as any).mockResolvedValue({ taskUid: '123' });
    (meiliSearchInstance.waitForTask as any).mockResolvedValue({ status: 'succeeded' });

    await adapter.search({
      query: 'test',
      filters: {
        categories: [categoryWithBackslash],
      },
      pageSize: 20,
      pageToken: '',
      sortBy: SortBy.RELEVANCE,
      facetFields: [],
    });

    const lastCall = (mockIndex.search as any).mock.calls[0];
    const searchParams = lastCall[1] as any;
    const filter = searchParams.filter;

    // Backslash should be escaped as well
    expect(filter[1]).toContain('category = "category\\value"');
  });
});
