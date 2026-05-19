# Catalog Service - Contracts Definition

> Language: Node.js/TypeScript | Role: Full CRUD product catalog with search

## gRPC Contract

### Proto Package

- **Package Name:** `catalog.v1`
- **File:** `catalog/v1/catalog.proto`

### Service Definition

**Service Name:** `CatalogService`

| RPC Method | Request Type | Response Type | Streaming |
|---|---|---|---|
| `Get` | `GetProductRequest` | `GetProductResponse` | Unary |
| `Search` | `SearchCatalogRequest` | `SearchCatalogResponse` | Unary |
| `Create` | `CreateProductRequest` | `CreateProductResponse` | Unary |
| `Update` | `UpdateProductRequest` | `UpdateProductResponse` | Unary |
| `Delete` | `DeleteProductRequest` | `DeleteProductResponse` | Unary |

### RPC Details

**Get:**
Retrieves a single product by ID with optional expansion of variants and inventory. The `include_variants` and `include_inventory` flags control which related data is included in the response, enabling clients to optimize for either completeness or minimal payload size.

**Search:**
Executes a full-text search with filtering, faceted navigation, and pagination. The request supports complex boolean queries, field-level boosting, range filters, and hierarchical category filtering. The response includes facet counts and query suggestions in addition to the matching products.

**Create:**
Creates a new product with optional variants and initial inventory. The request is validated atomically: SKU uniqueness, category existence, and attribute schema compliance are all checked before the product is persisted. The response includes the assigned product ID and an ETag for optimistic concurrency control.

**Update:**
Updates an existing product or its inventory. The update mask field specifies which fields are being modified, enabling partial updates without sending the full product representation. Inventory updates are processed through `UpdateInventoryPort` when the update mask includes inventory fields.

**Delete:**
Deletes a product from the catalog, either through a soft delete (marking as discontinued) or a hard delete (permanent removal). The request specifies the deletion reason and whether a replacement product should be designated for URL redirection. Hard deletes require that no active orders reference the product. The response confirms the deletion type and provides a replacement redirect URL if applicable.

### Key Message Types

```protobuf
message GetProductRequest {
  string product_id = 1;
  bool include_variants = 2;
  bool include_inventory = 3;
}

message GetProductResponse {
  Product product = 1;
  repeated ProductVariant variants = 2;
  InventorySummary inventory = 3;
}

message SearchCatalogRequest {
  string query = 1;
  SearchFilters filters = 2;
  int32 page_size = 3;
  string page_token = 4;
  enum SortBy {
    RELEVANCE = 0;
    PRICE_ASC = 1;
    PRICE_DESC = 2;
    CREATED_AT = 3;
    POPULARITY = 4;
  }
  SortBy sort_by = 5;
  repeated string facet_fields = 6;
}

message SearchCatalogResponse {
  repeated ProductSummary results = 1;
  int64 total_count = 2;
  string next_page_token = 3;
  map<string, FacetValues> facets = 4;
  repeated string suggestions = 5;
}

message CreateProductRequest {
  ProductInput product = 1;
  repeated VariantInput variants = 2;
  InventoryInput initial_stock = 3;
}

message CreateProductResponse {
  string product_id = 1;
  google.protobuf.Timestamp created_at = 2;
  string etag = 3;
}

message Product {
  string id = 1;
  string sku = 2;
  string name = 3;
  string description = 4;
  string category_id = 5;
  Money base_price = 6;
  map<string, string> attributes = 7;
  ProductStatus status = 8;
  google.protobuf.Timestamp created_at = 9;
  google.protobuf.Timestamp updated_at = 10;
}

message ProductVariant {
  string id = 1;
  string product_id = 2;
  string sku = 3;
  string name = 4;
  Money price = 5;
  map<string, string> attributes = 6;
}

message Money {
  int64 units = 1;
  int32 nanos = 2;
  string currency_code = 3;
}

enum ProductStatus {
  ACTIVE = 0;
  INACTIVE = 1;
  SUSPENDED = 2;
  DISCONTINUED = 3;
}
```

## OpenAPI Contract

### API Path Prefix

`/api/v1/catalog`

### Endpoints

| Method | Path | Request Body | Response | Auth Required |
|---|---|---|---|---|
| `GET` | `/api/v1/catalog/products/{id}` | None | `GetProductResponse` JSON | Optional |
| `GET` | `/api/v1/catalog/products` | None (query params) | `SearchCatalogResponse` JSON | Optional |
| `POST` | `/api/v1/catalog/products` | `CreateProductRequest` JSON | `CreateProductResponse` JSON | Yes |
| `PATCH` | `/api/v1/catalog/products/{id}` | `UpdateProductRequest` JSON | `UpdateProductResponse` JSON | Yes |
| `PATCH` | `/api/v1/catalog/products/{id}/inventory` | `UpdateInventoryRequest` JSON | `UpdateInventoryResponse` JSON | Yes |
| `DELETE` | `/api/v1/catalog/products/{id}` | None | 204 No Content | Yes |

### Endpoint Details

**GET /products/{id}:**
Retrieves a product by ID. Supports `?include=variants,inventory` query parameter for expansion. Returns 404 if the product does not exist or has been soft-deleted. Public products can be accessed without authentication; restricted products require a valid JWT with the `catalog:read` scope.

**GET /products:**
Searches the catalog. Query parameters include `q` (search text), `category` (category filter), `min_price`/`max_price` (price range), `page_size`, `page_token`, `sort`, and `facets`. Returns a paginated list with facet counts and suggestions. No authentication required for basic search; advanced filters may require the `catalog:search:advanced` scope.

**POST /products:**
Creates a new product. Requires the `catalog:write` scope. The request body must include the product name, SKU, category, and base price. Returns 201 with the product ID and ETag. Returns 409 if the SKU already exists. Returns 422 for validation errors with detailed field-level messages.

**PATCH /products/{id}/inventory:**
Updates inventory for a product. Requires the `catalog:inventory` scope. The request body specifies the warehouse, quantity delta, and reason. Returns the new and previous quantities. Returns 409 for concurrent modifications. Returns 422 for insufficient stock on negative deltas.

### Authentication Requirements

- Read operations (GET) are available without authentication for public product data
- Write operations (POST, PATCH, DELETE) require a valid JWT with appropriate scopes
- Internal service-to-service calls use mTLS with SPIFFE SVID verification
- Rate limiting is applied per client ID with higher limits for authenticated clients

## Event Contracts

### CloudEvents Type Prefix

`com.company.catalog.`

### Event Types

| Event Type | Payload Schema | Consumer Services |
|---|---|---|
| `com.company.catalog.product-created` | `ProductCreatedEvent` | Analytics, Notification, CDC Relay |
| `com.company.catalog.product-updated` | `ProductUpdatedEvent` | Analytics, Search Index, CDC Relay |
| `com.company.catalog.inventory-updated` | `InventoryUpdatedEvent` | Analytics, Order, Notification |
| `com.company.catalog.inventory-low` | `InventoryLowEvent` | Notification, Analytics |

### Event Details

**ProductCreatedEvent:**
Emitted when a new product is created. The payload includes the full product data including variants and initial inventory levels. The Analytics service uses this event to track catalog growth metrics. The Notification service uses this event to send alerts to merchandising teams about new listings. The CDC Relay replicates the event to the analytics data warehouse for reporting.

**ProductUpdatedEvent:**
Emitted when a product's attributes, pricing, or status changes. The payload includes the updated fields (using a field mask pattern) and the previous values for audit purposes. The Analytics service tracks pricing changes and listing modifications. The search index is updated based on this event to keep the Elasticsearch index in sync. The CDC Relay replicates the change to downstream stores.

**InventoryUpdatedEvent:**
Emitted after any inventory level change. The payload includes the product ID, variant ID, warehouse, quantity delta, new quantity, and the reason for the change. The Order service consumes this event to update its local inventory cache for availability checks during order placement. The Analytics service tracks inventory velocity and stockout rates.

**InventoryLowEvent:**
Emitted when inventory for a product drops below the configured reorder threshold. The payload includes the product ID, current quantity, and threshold. The Notification service consumes this event to send restock alerts to the procurement team. The Analytics service tracks stockout frequency for supply chain optimization.
