# Catalog Service - Ports Definition

> Language: Node.js/TypeScript | Role: Full CRUD product catalog with search

## Inbound Ports (Driving / Use Case Interfaces)

### GetProductPort

- **Port Name:** `GetProductPort`
- **Input Type:** `GetProductRequest` (product_id: string, include_variants: bool, include_inventory: bool)
- **Output Type:** `GetProductResponse` (product: Product, variants: optional<list<ProductVariant>>, inventory: optional<InventorySummary>)
- **Error Types:** `ProductNotFoundError`, `ProductSuspendedError`
- **Description:** Retrieves a single product by its unique identifier. The port supports optional expansion of related data through the `include_variants` and `include_inventory` flags, which allow callers to fetch a complete product view in a single call rather than making multiple round trips. When variants are requested, the response includes all active variants with their pricing and attribute differences. When inventory is requested, the response includes a summary of available stock across all warehouses. The product data is first looked up in the Redis cache for sub-millisecond reads; on cache miss, the port queries the primary PostgreSQL database and populates the cache for subsequent requests. Products that have been suspended by the moderation team return a `ProductSuspendedError` instead of the product data, preventing display of non-compliant listings.

### SearchCatalogPort

- **Port Name:** `SearchCatalogPort`
- **Input Type:** `SearchCatalogRequest` (query: string, filters: SearchFilters, page_size: int32, page_token: string, sort_by: enum [RELEVANCE, PRICE_ASC, PRICE_DESC, CREATED_AT, POPULARITY], facet_fields: list<string>)
- **Output Type:** `SearchCatalogResponse` (results: list<ProductSummary>, total_count: int64, next_page_token: string, facets: map<string, list<FacetValue>>, suggestions: list<string>)
- **Error Types:** `SearchIndexUnavailableError`, `InvalidQueryError`
- **Description:** Executes a full-text search against the product catalog with support for filtering, pagination, sorting, and faceted navigation. The search is powered by Elasticsearch, which indexes product data in near-real-time via the CDC pipeline. The port supports complex boolean queries with field-level boosting, range filters on price and date fields, and category-based hierarchical filtering. Faceted navigation returns aggregate counts for brand, category, price range, and any custom attribute facets requested by the caller. The suggestions field returns query suggestions based on the user's partial input, enabling type-ahead search experiences. When Elasticsearch is unavailable, the port falls back to a basic PostgreSQL full-text search with degraded relevance ranking, returning a `SearchIndexUnavailableError` warning alongside the results.

### CreateProductPort

- **Port Name:** `CreateProductPort`
- **Input Type:** `CreateProductRequest` (product: ProductInput, variants: list<VariantInput>, initial_stock: optional<InventoryInput>)
- **Output Type:** `CreateProductResponse` (product_id: string, created_at: timestamp, etag: string)
- **Error Types:** `DuplicateSKUError`, `InvalidCategoryError`, `ValidationError`, `UnauthorizedError`
- **Description:** Creates a new product listing in the catalog. The port performs comprehensive validation of the product input, including SKU uniqueness checking, category path validation against the category taxonomy, attribute schema validation for category-specific attributes, and pricing consistency checks across variants. If initial stock information is provided, the port atomically creates both the product record and the corresponding inventory records in a single database transaction. Upon successful creation, the port publishes a `com.company.catalog.product-created` domain event, which triggers downstream processes such as search index indexing, inventory allocation, and analytics ingestion. The returned ETag value enables optimistic concurrency control for subsequent updates.

### UpdateInventoryPort

- **Port Name:** `UpdateInventoryPort`
- **Input Type:** `UpdateInventoryRequest` (product_id: string, variant_id: optional<string>, warehouse_id: string, quantity_delta: int32, reason: enum [SALE, RESTOCK, ADJUSTMENT, RETURN], reference_id: string)
- **Output Type:** `UpdateInventoryResponse` (new_quantity: int64, previous_quantity: int64, updated_at: timestamp)
- **Error Types:** `InsufficientStockError`, `ProductNotFoundError`, `ConcurrentModificationError`
- **Description:** Updates the inventory level for a product or variant at a specific warehouse. The `quantity_delta` can be positive (restock, return) or negative (sale, adjustment), and the operation is atomic to prevent overselling. The port uses optimistic concurrency control with a version field to detect and reject concurrent modifications, ensuring that two simultaneous sales do not oversell the last item. When inventory drops below the configured reorder threshold, the port publishes a `com.company.catalog.inventory-low` event to trigger procurement workflows. The `reference_id` field links the inventory change to the originating order or restock shipment for audit traceability. This port is called by the Order service during order placement and by the warehouse management system during restocking operations.

### DeleteProductPort

- **Port Name:** `DeleteProductPort`
- **Input Type:** `DeleteProductRequest` (product_id: string, reason: enum [DISCONTINUED, COMPLIANCE_REMOVAL, MERGE_DUPLICATE, ADMIN_ACTION], hard_delete: bool, replacement_product_id: optional<string>)
- **Output Type:** `DeleteProductResponse` (product_id: string, deleted: bool, hard_deleted: bool, replacement_redirect: optional<string>, deleted_at: timestamp)
- **Error Types:** `ProductNotFoundError`, `ProductHasActiveOrdersError`, `DeleteNotAuthorizedError`
- **Description:** Deletes a product from the catalog, either through a soft delete (marking the product as discontinued so it no longer appears in search results but remains accessible via direct link for order history) or a hard delete (permanently removing the product record from the database). The soft delete is the default and recommended approach because it preserves order history integrity and allows existing orders referencing the product to continue displaying the correct product information. Hard deletes are restricted to administrative users and require that the product has no associated active orders; if active orders exist, the port returns a `ProductHasActiveOrdersError` and the caller must wait until all orders referencing the product have been completed or cancelled. When a `replacement_product_id` is provided, the deleted product's canonical URL is redirected to the replacement product's URL, preserving SEO value and ensuring that bookmarked links continue to work. The port publishes a `com.company.catalog.product-deleted` domain event upon successful deletion, which triggers search index removal, analytics recording, and inventory cleanup for the deleted product.

## Outbound Ports (Driven / Infrastructure Interfaces)

### CatalogRepositoryPort

- **Port Name:** `CatalogRepositoryPort`
- **Operations:**
  - `FindById(product_id: string) -> optional<Product>`: Retrieves a product by ID with all attributes.
  - `FindBySKU(sku: string) -> optional<Product>`: Retrieves a product by its unique SKU.
  - `Save(product: Product) -> Product`: Persists a product, creating or updating as appropriate.
  - `Delete(product_id: string) -> void`: Soft-deletes a product by marking it as removed.
  - `UpdateInventory(product_id: string, variant_id: string, warehouse_id: string, delta: int) -> InventoryUpdateResult`: Atomically adjusts inventory levels.
  - `FindByIds(product_ids: list<string>) -> list<Product>`: Batch retrieval of multiple products by ID.
- **Technology:** PostgreSQL with Prisma ORM
- **ACL Required:** No (internal data store)
- **Description:** The catalog repository port abstracts all database operations for product and inventory data. Prisma provides type-safe query generation, automatic migration management, and connection pooling. The repository uses PostgreSQL's row-level locking for inventory updates to prevent overselling, and partial indexes for efficient soft-delete filtering. Complex queries such as category tree traversal use recursive CTEs for efficient hierarchical lookups.

### SearchIndexPort

- **Port Name:** `SearchIndexPort`
- **Operations:**
  - `Index(product: Product) -> void`: Indexes or re-indexes a product document in the search engine.
  - `BulkIndex(products: list<Product>) -> void`: Batch indexing for initial load and bulk updates.
  - `Search(query: SearchQuery) -> SearchResult`: Executes a search query with filtering, sorting, and faceting.
  - `Delete(product_id: string) -> void`: Removes a product from the search index.
  - `Refresh() -> void`: Forces a refresh of the search index for near-real-time consistency.
- **Technology:** Elasticsearch 8.x
- **ACL Required:** No (internal infrastructure)
- **Description:** The search index port manages all interactions with the Elasticsearch cluster. Product documents are indexed with a carefully designed mapping that supports full-text search on name and description fields (with language-specific analyzers), exact filtering on category and attribute fields, range queries on price and date fields, and nested document queries for variant data. The port implements a bulk indexing strategy that batches index updates into groups of 500 documents with a 5-second flush interval, balancing indexing latency against cluster load. The search operation supports cursor-based pagination using Elasticsearch's search_after mechanism for deep pagination without the performance penalty of offset-based paging.

### EventPublisherPort

- **Port Name:** `EventPublisherPort`
- **Operations:**
  - `Publish(event: DomainEvent) -> void`: Publishes a single domain event to the event backbone.
  - `PublishBatch(events: list<DomainEvent>) -> void`: Publishes multiple events atomically.
- **Technology:** Apache Kafka (using Transactional Producer API)
- **ACL Required:** No (internal infrastructure)
- **Description:** The event publisher port handles all outbound event production for the Catalog service. Events are published to Kafka using the transactional producer API to ensure exactly-once delivery semantics. The port implements the transactional outbox pattern by writing events to a PostgreSQL outbox table in the same transaction as the data mutation, then a separate relay process reads the outbox and publishes to Kafka. This guarantees that the database state and the event stream are always consistent, even in the face of application crashes or network partitions. Event payloads are serialized using Protobuf for efficiency and schema evolution compatibility with the Schema Registry service.
