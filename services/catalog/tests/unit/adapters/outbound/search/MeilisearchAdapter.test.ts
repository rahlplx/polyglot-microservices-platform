import { describe, it, expect, jest } from '@jest/globals';
import { MeilisearchAdapter } from '../../../../../src/adapters/outbound/search/MeilisearchAdapter';
import { SortBy } from '../../../../../src/domain/ports/inbound/SearchCatalog';

jest.mock('meilisearch', () => ({
  MeiliSearch: jest.fn().mockImplementation(() => ({
    index: jest.fn().mockReturnValue({
      search: jest.fn().mockResolvedValue({ hits: [], totalHits: 0 }),
    }),
  })),
}));

describe('MeilisearchAdapter Security', () => {
  it('escapes filters to prevent injection', async () => {
    const adapter = new MeilisearchAdapter({ host: 'http://h', apiKey: 'k', indexName: 'i' });
    (adapter as any).indexInitialized = true;
    const mockSearch = (adapter as any).client.index().search;
    await adapter.search({
      query: 'q',
      filters: { categories: ['electronics" OR "a"="a'], tags: ['tag\\'] },
      pageSize: 20, pageToken: '', sortBy: SortBy.RELEVANCE, facetFields: []
    });
    const filters = mockSearch.mock.calls[0][1].filter;
    expect(filters).toContain('(category = "electronics\\" OR \\"a\\"=\\"a")');
    expect(filters).toContain('(tags = "tag\\\\")');
  });
});
