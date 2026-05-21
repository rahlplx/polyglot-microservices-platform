/**
 * CatalogService Unit Tests
 *
 * Tests the domain service in isolation using mocked outbound ports.
 * All tests verify business logic without any infrastructure dependencies.
 */

import { describe, it, expect, jest, beforeEach } from '@jest/globals';
import { CatalogService } from '../../src/domain/services/CatalogService';
import type { ProductRepository } from '../../src/domain/ports/outbound/ProductRepository';
import type { SearchIndex } from '../../src/domain/ports/outbound/SearchIndex';
import {
  Product,
  ProductStatus,
  Money,
  ProductNotFoundError,
  InsufficientStockError,
  ProductHasActiveOrdersError,
  InvalidQueryError,
  DeleteReason,
} from '../../src/domain/models';
import type { ProductProps } from '../../src/domain/models/Product';
import { SortBy } from '../../src/domain/ports/inbound/SearchCatalog';

// ---------------------------------------------------------------------------
// Test Fixtures
// ---------------------------------------------------------------------------

function createTestProduct(overrides: Partial<ProductProps> = {}): Product {
  const defaults: ProductProps = {
    productId: 'prod-001',
    name: 'Test Product',
    description: 'A test product description',
    price: Money.create('USD', 29, 990000000),
    category: 'electronics',
    tags: ['test', 'sample'],
    availableQuantity: 100,
    status: ProductStatus.ACTIVE,
    createdAt: new Date('2024-01-01T00:00:00Z'),
    updatedAt: new Date('2024-01-01T00:00:00Z'),
  };
  return Product.reconstitute({ ...defaults, ...overrides });
}

function createMockRepository(): jest.Mocked<ProductRepository> {
  return {
    findById: jest.fn(),
    findByIds: jest.fn(),
    save: jest.fn(),
    softDelete: jest.fn(),
    hardDelete: jest.fn(),
    list: jest.fn(),
    hasActiveOrders: jest.fn(),
    adjustInventory: jest.fn(),
  };
}

function createMockSearchIndex(): jest.Mocked<SearchIndex> {
  return {
    index: jest.fn(),
    bulkIndex: jest.fn(),
    search: jest.fn(),
    delete: jest.fn(),
    refresh: jest.fn(),
    suggest: jest.fn(),
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('CatalogService', () => {
  let service: CatalogService;
  let mockRepo: jest.Mocked<ProductRepository>;
  let mockSearch: jest.Mocked<SearchIndex>;
  let idCounter: number;

  beforeEach(() => {
    idCounter = 0;
    mockRepo = createMockRepository();
    mockSearch = createMockSearchIndex();
    service = new CatalogService({
      productRepository: mockRepo,
      searchIndex: mockSearch,
      generateId: () => `prod-${String(++idCounter).padStart(3, '0')}`,
    });
  });

  // -------------------------------------------------------------------------
  // CreateProduct
  // -------------------------------------------------------------------------

  describe('createProduct', () => {
    it('should create a product with valid input', async () => {
      mockRepo.save.mockImplementation(async (product: Product) => product);

      const result = await service.createProduct({
        name: 'New Product',
        description: 'Brand new product',
        price: { currencyCode: 'USD', units: 49, nanos: 990000000 },
        category: 'electronics',
        tags: ['new'],
        initialQuantity: 50,
      });

      expect(result.product).toBeDefined();
      expect(result.product.name).toBe('New Product');
      expect(result.product.category).toBe('electronics');
      expect(result.product.status).toBe(ProductStatus.ACTIVE);
      expect(result.product.availableQuantity).toBe(50);
      expect(mockRepo.save).toHaveBeenCalledTimes(1);
      expect(mockSearch.index).toHaveBeenCalledTimes(1);
    });

    it('should throw on empty name', async () => {
      await expect(
        service.createProduct({
          name: '',
          description: '',
          price: { currencyCode: 'USD', units: 10, nanos: 0 },
          category: 'test',
          tags: [],
          initialQuantity: 0,
        })
      ).rejects.toThrow('Product name is required');
    });

    it('should throw on empty category', async () => {
      await expect(
        service.createProduct({
          name: 'Valid Name',
          description: '',
          price: { currencyCode: 'USD', units: 10, nanos: 0 },
          category: '',
          tags: [],
          initialQuantity: 0,
        })
      ).rejects.toThrow('Product category is required');
    });

    it('should not fail if search indexing fails', async () => {
      mockRepo.save.mockImplementation(async (product: Product) => product);
      mockSearch.index.mockRejectedValue(new Error('Search unavailable'));

      const result = await service.createProduct({
        name: 'Product',
        description: 'Test',
        price: { currencyCode: 'USD', units: 10, nanos: 0 },
        category: 'test',
        tags: [],
        initialQuantity: 0,
      });

      expect(result.product).toBeDefined();
      expect(mockRepo.save).toHaveBeenCalledTimes(1);
    });
  });

  // -------------------------------------------------------------------------
  // GetProduct
  // -------------------------------------------------------------------------

  describe('getProduct', () => {
    it('should return a product by ID', async () => {
      const testProduct = createTestProduct();
      mockRepo.findById.mockResolvedValue(testProduct);

      const result = await service.getProduct({ productId: 'prod-001' });

      expect(result.product).toBe(testProduct);
      expect(mockRepo.findById).toHaveBeenCalledWith('prod-001');
    });

    it('should throw ProductNotFoundError when product does not exist', async () => {
      mockRepo.findById.mockResolvedValue(null);

      await expect(
        service.getProduct({ productId: 'nonexistent' })
      ).rejects.toThrow(ProductNotFoundError);
    });

    it('should throw ProductNotFoundError for INACTIVE products', async () => {
      const inactiveProduct = createTestProduct({ status: ProductStatus.INACTIVE });
      mockRepo.findById.mockResolvedValue(inactiveProduct);

      await expect(
        service.getProduct({ productId: 'prod-001' })
      ).rejects.toThrow(ProductNotFoundError);
    });
  });

  // -------------------------------------------------------------------------
  // SearchCatalog
  // -------------------------------------------------------------------------

  describe('searchCatalog', () => {
    it('should search products via search index', async () => {
      mockSearch.search.mockResolvedValue({
        results: [
          {
            productId: 'prod-001',
            name: 'Test Product',
            descriptionSnippet: 'A test product',
            price: Money.create('USD', 29, 990000000),
            relevanceScore: 0.95,
          },
        ],
        totalCount: 1,
        nextPageToken: '',
        facets: {},
        suggestions: [],
      });

      const result = await service.searchCatalog({
        query: 'test',
        filters: {},
        pageSize: 20,
        pageToken: '',
        sortBy: SortBy.RELEVANCE,
        facetFields: [],
      });

      expect(result.results).toHaveLength(1);
      expect(result.results[0].productId).toBe('prod-001');
      expect(result.totalCount).toBe(1);
      expect(mockSearch.search).toHaveBeenCalledTimes(1);
    });

    it('should throw InvalidQueryError for query exceeding max length', async () => {
      const longQuery = 'a'.repeat(1001);

      await expect(
        service.searchCatalog({
          query: longQuery,
          filters: {},
          pageSize: 20,
          pageToken: '',
          sortBy: SortBy.RELEVANCE,
          facetFields: [],
        })
      ).rejects.toThrow(InvalidQueryError);
    });

    it('should throw InvalidQueryError for invalid page size', async () => {
      await expect(
        service.searchCatalog({
          query: 'test',
          filters: {},
          pageSize: 0,
          pageToken: '',
          sortBy: SortBy.RELEVANCE,
          facetFields: [],
        })
      ).rejects.toThrow(InvalidQueryError);
    });

    it('should fall back to database search when search index is unavailable', async () => {
      const { SearchIndexUnavailableError } = await import('../../src/domain/models');
      mockSearch.search.mockRejectedValue(new SearchIndexUnavailableError());
      mockRepo.list.mockResolvedValue({
        items: [createTestProduct()],
        nextCursor: '',
        totalCount: 1,
        hasMore: false,
      });

      const result = await service.searchCatalog({
        query: 'test',
        filters: {},
        pageSize: 20,
        pageToken: '',
        sortBy: SortBy.RELEVANCE,
        facetFields: [],
      });

      expect(result.results).toHaveLength(1);
      expect(result.totalCount).toBe(1);
      // Fallback results have 0 relevance score
      expect(result.results[0].relevanceScore).toBe(0);
    });
  });

  // -------------------------------------------------------------------------
  // DeleteProduct
  // -------------------------------------------------------------------------

  describe('deleteProduct', () => {
    it('should soft-delete a product', async () => {
      const product = createTestProduct();
      mockRepo.findById.mockResolvedValue(product);
      mockRepo.save.mockImplementation(async (p: Product) => p);

      const result = await service.deleteProduct({
        productId: 'prod-001',
        reason: DeleteReason.DISCONTINUED,
        hardDelete: false,
      });

      expect(result.deleted).toBe(true);
      expect(result.hardDeleted).toBe(false);
      expect(mockRepo.save).toHaveBeenCalledTimes(1);
      expect(product.status).toBe(ProductStatus.DISCONTINUED);
    });

    it('should hard-delete a product with no active orders', async () => {
      const product = createTestProduct();
      mockRepo.findById.mockResolvedValue(product);
      mockRepo.hasActiveOrders.mockResolvedValue(false);
      mockRepo.hardDelete.mockResolvedValue(true);

      const result = await service.deleteProduct({
        productId: 'prod-001',
        reason: DeleteReason.ADMIN_ACTION,
        hardDelete: true,
      });

      expect(result.deleted).toBe(true);
      expect(result.hardDeleted).toBe(true);
      expect(mockRepo.hardDelete).toHaveBeenCalledWith('prod-001');
      expect(mockSearch.delete).toHaveBeenCalledWith('prod-001');
    });

    it('should throw ProductHasActiveOrdersError for hard-delete with active orders', async () => {
      const product = createTestProduct();
      mockRepo.findById.mockResolvedValue(product);
      mockRepo.hasActiveOrders.mockResolvedValue(true);

      await expect(
        service.deleteProduct({
          productId: 'prod-001',
          reason: DeleteReason.ADMIN_ACTION,
          hardDelete: true,
        })
      ).rejects.toThrow(ProductHasActiveOrdersError);
    });

    it('should throw ProductNotFoundError for nonexistent product', async () => {
      mockRepo.findById.mockResolvedValue(null);

      await expect(
        service.deleteProduct({
          productId: 'nonexistent',
          reason: DeleteReason.ADMIN_ACTION,
          hardDelete: false,
        })
      ).rejects.toThrow(ProductNotFoundError);
    });

    it('should handle replacement product redirect on soft delete', async () => {
      const product = createTestProduct();
      mockRepo.findById.mockResolvedValue(product);
      mockRepo.save.mockImplementation(async (p: Product) => p);

      const result = await service.deleteProduct({
        productId: 'prod-001',
        reason: DeleteReason.MERGE_DUPLICATE,
        hardDelete: false,
        replacementProductId: 'prod-002',
      });

      expect(result.replacementRedirect).toBe('prod-002');
    });
  });

  // -------------------------------------------------------------------------
  // UpdateProduct
  // -------------------------------------------------------------------------

  describe('updateProduct', () => {
    it('should update product name', async () => {
      const product = createTestProduct();
      mockRepo.findById.mockResolvedValue(product);
      mockRepo.save.mockImplementation(async (p: Product) => p);

      const updated = await service.updateProduct('prod-001', { name: 'Updated Name' });

      expect(updated.name).toBe('Updated Name');
      expect(mockRepo.save).toHaveBeenCalledTimes(1);
    });

    it('should throw ProductNotFoundError for nonexistent product', async () => {
      mockRepo.findById.mockResolvedValue(null);

      await expect(
        service.updateProduct('nonexistent', { name: 'New Name' })
      ).rejects.toThrow(ProductNotFoundError);
    });

    it('should adjust inventory with positive delta', async () => {
      const product = createTestProduct({ availableQuantity: 50 });
      mockRepo.findById.mockResolvedValue(product);
      mockRepo.save.mockImplementation(async (p: Product) => p);

      const updated = await service.updateProduct('prod-001', { quantityAdjustment: 10 });

      expect(updated.availableQuantity).toBe(60);
    });

    it('should throw InsufficientStockError for negative delta exceeding stock', async () => {
      const product = createTestProduct({ availableQuantity: 5 });
      mockRepo.findById.mockResolvedValue(product);

      await expect(
        service.updateProduct('prod-001', { quantityAdjustment: -10 })
      ).rejects.toThrow(InsufficientStockError);
    });
  });

  // -------------------------------------------------------------------------
  // AdjustInventory
  // -------------------------------------------------------------------------

  describe('adjustInventory', () => {
    it('should increase inventory on restock', async () => {
      const product = createTestProduct({ availableQuantity: 100 });
      mockRepo.findById.mockResolvedValue(product);
      mockRepo.save.mockImplementation(async (p: Product) => p);

      const result = await service.adjustInventory('prod-001', 50, 'RESTOCK');

      expect(result.newQuantity).toBe(150);
      expect(result.previousQuantity).toBe(100);
    });

    it('should decrease inventory on sale', async () => {
      const product = createTestProduct({ availableQuantity: 100 });
      mockRepo.findById.mockResolvedValue(product);
      mockRepo.save.mockImplementation(async (p: Product) => p);

      const result = await service.adjustInventory('prod-001', -30, 'SALE');

      expect(result.newQuantity).toBe(70);
      expect(result.previousQuantity).toBe(100);
    });

    it('should throw InsufficientStockError when overselling', async () => {
      const product = createTestProduct({ availableQuantity: 5 });
      mockRepo.findById.mockResolvedValue(product);

      await expect(
        service.adjustInventory('prod-001', -10, 'SALE')
      ).rejects.toThrow(InsufficientStockError);
    });

    it('should throw ProductNotFoundError for nonexistent product', async () => {
      mockRepo.findById.mockResolvedValue(null);

      await expect(
        service.adjustInventory('nonexistent', 10, 'RESTOCK')
      ).rejects.toThrow(ProductNotFoundError);
    });
  });

  // -------------------------------------------------------------------------
  // ListProducts
  // -------------------------------------------------------------------------

  describe('listProducts', () => {
    it('should list products with pagination', async () => {
      const products = [
        createTestProduct({ productId: 'prod-001' }),
        createTestProduct({ productId: 'prod-002' }),
      ];
      mockRepo.list.mockResolvedValue({
        items: products,
        nextCursor: 'cursor-abc',
        totalCount: 50,
        hasMore: true,
      });

      const result = await service.listProducts({ pageSize: 2 });

      expect(result.products).toHaveLength(2);
      expect(result.nextCursor).toBe('cursor-abc');
      expect(result.totalCount).toBe(50);
      expect(result.hasMore).toBe(true);
    });

    it('should list products filtered by category', async () => {
      mockRepo.list.mockResolvedValue({
        items: [createTestProduct()],
        nextCursor: '',
        totalCount: 1,
        hasMore: false,
      });

      const result = await service.listProducts({ category: 'electronics', pageSize: 20 });

      expect(result.products).toHaveLength(1);
      expect(mockRepo.list).toHaveBeenCalledWith(
        expect.objectContaining({ category: 'electronics' })
      );
    });
  });
});

// ---------------------------------------------------------------------------
// Money Value Object Tests
// -------------------------------------------------------------------------

describe('Money', () => {
  it('should create a valid Money value', () => {
    const money = Money.create('USD', 29, 990000000);
    expect(money.currencyCode).toBe('USD');
    expect(money.units).toBe(29);
    expect(money.nanos).toBe(990000000);
  });

  it('should throw on invalid currency code', () => {
    expect(() => Money.create('US', 10, 0)).toThrow('Invalid currency code');
    expect(() => Money.create('', 10, 0)).toThrow('Invalid currency code');
  });

  it('should throw on non-integer units', () => {
    expect(() => Money.create('USD', 10.5, 0)).toThrow('Units must be an integer');
  });

  it('should throw on nanos out of range', () => {
    expect(() => Money.create('USD', 10, -1)).toThrow();
    expect(() => Money.create('USD', 10, 1000000000)).toThrow('Nanos must be in range');
  });

  it('should create Money from decimal string', () => {
    const money = Money.fromDecimal('USD', '29.99');
    expect(money.units).toBe(29);
    expect(money.nanos).toBe(990000000);
  });

  it('should convert back to decimal string', () => {
    const money = Money.create('USD', 29, 990000000);
    expect(money.toDecimal()).toBe('29.99');
  });

  it('should add two Money values', () => {
    const a = Money.create('USD', 10, 500000000);
    const b = Money.create('USD', 20, 300000000);
    const result = a.add(b);
    expect(result.units).toBe(30);
    expect(result.nanos).toBe(800000000);
  });

  it('should subtract two Money values', () => {
    const a = Money.create('USD', 30, 500000000);
    const b = Money.create('USD', 10, 200000000);
    const result = a.subtract(b);
    expect(result.units).toBe(20);
    expect(result.nanos).toBe(300000000);
  });

  it('should compare Money values correctly', () => {
    const a = Money.create('USD', 10, 0);
    const b = Money.create('USD', 20, 0);
    expect(a.lessThan(b)).toBe(true);
    expect(b.greaterThan(a)).toBe(true);
    expect(a.equals(Money.create('USD', 10, 0))).toBe(true);
  });

  it('should throw on currency mismatch', () => {
    const usd = Money.create('USD', 10, 0);
    const eur = Money.create('EUR', 10, 0);
    expect(() => usd.add(eur)).toThrow('Currency mismatch');
  });
});

// ---------------------------------------------------------------------------
// Product Entity Tests
// -------------------------------------------------------------------------

describe('Product', () => {
  it('should create a product with valid input', () => {
    const product = Product.create({
      productId: 'prod-test',
      name: 'Test Product',
      description: 'A product for testing',
      price: Money.create('USD', 99, 990000000),
      category: 'electronics',
      tags: ['test'],
      initialQuantity: 100,
    });

    expect(product.productId).toBe('prod-test');
    expect(product.name).toBe('Test Product');
    expect(product.status).toBe(ProductStatus.ACTIVE);
    expect(product.availableQuantity).toBe(100);
  });

  it('should soft-delete a product', () => {
    const product = createTestProduct();
    product.softDelete();
    expect(product.status).toBe(ProductStatus.DISCONTINUED);
  });

  it('should check availability correctly', () => {
    const active = createTestProduct({ availableQuantity: 10 });
    expect(active.isAvailable()).toBe(true);

    const outOfStock = createTestProduct({ availableQuantity: 0 });
    expect(outOfStock.isAvailable()).toBe(false);

    const discontinued = createTestProduct({ status: ProductStatus.DISCONTINUED });
    expect(discontinued.isAvailable()).toBe(false);
  });

  it('should update product fields', () => {
    const product = createTestProduct();
    product.update({ name: 'Updated Name' });
    expect(product.name).toBe('Updated Name');
  });

  it('should adjust inventory', () => {
    const product = createTestProduct({ availableQuantity: 50 });
    product.adjustInventory(10, 'RESTOCK');
    expect(product.availableQuantity).toBe(60);
  });

  it('should throw InsufficientStockError when overselling', () => {
    const product = createTestProduct({ availableQuantity: 5 });
    expect(() => product.adjustInventory(-10, 'SALE')).toThrow(InsufficientStockError);
  });
});
