import { describe, it, expect, beforeEach, jest } from '@jest/globals';
import { MeilisearchAdapter } from '../../src/adapters/outbound/search/MeilisearchAdapter';

// Mock the meilisearch client
jest.mock('meilisearch', () => {
  return {
    MeiliSearch: jest.fn().mockImplementation(() => ({
      index: jest.fn(),
    })),
  };
});

describe('MeilisearchAdapter', () => {
  let adapter: MeilisearchAdapter;

  beforeEach(() => {
    adapter = new MeilisearchAdapter({
      host: 'http://localhost:7700',
      apiKey: 'masterKey',
      indexName: 'products',
    });
  });

  describe('buildFilters', () => {
    it('should escape double quotes in category filters', () => {
      const filters = {
        categories: ['electronics"', 'books'],
      };

      // Access private method for testing
      const result = (adapter as any).buildFilters(filters);

      // Expected: category = "electronics\"" OR category = "books"
      // Current implementation will likely produce: category = "electronics"" OR category = "books"
      // which is invalid Meilisearch filter syntax and can lead to injection.
      expect(result).toContain('(category = "electronics\\"" OR category = "books")');
    });

    it('should escape backslashes in tag filters', () => {
      const filters = {
        tags: ['tag\\with\\backslashes', 'simple'],
      };

      const result = (adapter as any).buildFilters(filters);

      // Meilisearch requires escaping backslashes in filters
      expect(result).toContain('(tags = "tag\\\\with\\\\backslashes" OR tags = "simple")');
    });

    it('should handle complex injection attempts', () => {
      const filters = {
        categories: ['active" OR status = "deleted'],
      };

      const result = (adapter as any).buildFilters(filters);

      // Should be escaped so it stays within the category attribute
      expect(result).toContain('(category = "active\\" OR status = \\"deleted")');
      expect(result).not.toContain('OR status = "deleted"');
    });
  });
});
