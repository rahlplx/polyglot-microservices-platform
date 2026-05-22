/**
 * MeilisearchAdapter — Filter Injection Prevention Tests (Security)
 *
 * Verifies that filter values are sanitized before being embedded in
 * Meilisearch filter expressions. Without sanitization, a value like:
 *   foo" OR status = "ACTIVE
 * would produce the filter:
 *   category = "foo" OR status = "ACTIVE"
 * allowing an attacker to read all active products regardless of category.
 */

import { describe, it, expect } from '@jest/globals';

// ---------------------------------------------------------------------------
// Inline sanitizer (mirrors MeilisearchAdapter.sanitizeFilterValue)
// Tests the algorithm independently before wiring to the adapter.
// ---------------------------------------------------------------------------

function sanitizeFilterValue(value: unknown): string {
  if (typeof value !== 'string') return '';
  return value.replace(/["\\\u0000]/g, '').slice(0, 256);
}

describe('MeilisearchAdapter — sanitizeFilterValue', () => {
  describe('removes injection characters', () => {
    it('strips double-quote (closes filter string)', () => {
      expect(sanitizeFilterValue('foo" OR 1=1 "')).toBe('foo OR 1=1 ');
    });

    it('strips backslash (escape sequence)', () => {
      expect(sanitizeFilterValue('foo\\bar')).toBe('foobar');
    });

    it('strips null byte (string terminator)', () => {
      expect(sanitizeFilterValue('foo\u0000bar')).toBe('foobar');
    });

    it('strips combined injection attempt', () => {
      const payload = 'Electronics" OR status = "ACTIVE';
      expect(sanitizeFilterValue(payload)).toBe('Electronics OR status = ACTIVE');
    });

    it('strips full filter escape attempt', () => {
      const payload = '" OR availableQuantity > 0 OR category = "';
      expect(sanitizeFilterValue(payload)).toBe(' OR availableQuantity > 0 OR category = ');
    });
  });

  describe('preserves legitimate values', () => {
    it('passes normal category name', () => {
      expect(sanitizeFilterValue('Electronics')).toBe('Electronics');
    });

    it('passes category with spaces', () => {
      expect(sanitizeFilterValue('Home & Garden')).toBe('Home & Garden');
    });

    it('passes unicode category', () => {
      expect(sanitizeFilterValue('Électronique')).toBe('Électronique');
    });

    it('passes tag with hyphens', () => {
      expect(sanitizeFilterValue('best-seller')).toBe('best-seller');
    });

    it('passes alphanumeric with numbers', () => {
      expect(sanitizeFilterValue('Category123')).toBe('Category123');
    });
  });

  describe('length limiting', () => {
    it('truncates values over 256 chars', () => {
      const long = 'a'.repeat(300);
      expect(sanitizeFilterValue(long)).toHaveLength(256);
    });

    it('truncates after stripping injection chars', () => {
      const payload = '"'.repeat(10) + 'a'.repeat(300);
      const result = sanitizeFilterValue(payload);
      expect(result).toHaveLength(256);
      expect(result).toBe('a'.repeat(256));
    });
  });

  describe('type safety', () => {
    it('returns empty string for non-string input', () => {
      expect(sanitizeFilterValue(null)).toBe('');
      expect(sanitizeFilterValue(undefined)).toBe('');
      expect(sanitizeFilterValue(42)).toBe('');
      expect(sanitizeFilterValue({})).toBe('');
    });
  });

  describe('filter expression construction safety', () => {
    it('safely embeds sanitized category in filter expression', () => {
      const raw = 'Electronics" OR status = "ACTIVE';
      const safe = sanitizeFilterValue(raw);
      const filter = `category = "${safe}"`;
      // Must not contain unbalanced quotes or injection
      const quoteCount = (filter.match(/"/g) || []).length;
      expect(quoteCount).toBe(2); // exactly open + close
    });

    it('safely embeds sanitized tag in filter expression', () => {
      const raw = 'sale\\tag" OR availableQuantity > 0 --';
      const safe = sanitizeFilterValue(raw);
      const filter = `tags = "${safe}"`;
      const quoteCount = (filter.match(/"/g) || []).length;
      expect(quoteCount).toBe(2);
    });
  });
});
