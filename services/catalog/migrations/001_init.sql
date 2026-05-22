-- Catalog Service — Initial Schema

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

CREATE TYPE product_status AS ENUM ('ACTIVE', 'INACTIVE', 'DISCONTINUED', 'DRAFT');

CREATE TABLE products (
    product_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sku                 TEXT UNIQUE NOT NULL,
    name                TEXT NOT NULL,
    description         TEXT NOT NULL DEFAULT '',
    category            TEXT NOT NULL,
    tags                TEXT[] NOT NULL DEFAULT '{}',
    currency_code       CHAR(3) NOT NULL,
    price_units         BIGINT NOT NULL DEFAULT 0,
    price_nanos         INT NOT NULL DEFAULT 0,
    available_quantity  INT NOT NULL DEFAULT 0 CHECK (available_quantity >= 0),
    reserved_quantity   INT NOT NULL DEFAULT 0 CHECK (reserved_quantity >= 0),
    status              product_status NOT NULL DEFAULT 'DRAFT',
    search_indexed_at   TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ
);

CREATE TABLE inventory_reservations (
    reservation_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      UUID NOT NULL REFERENCES products(product_id),
    order_id        UUID NOT NULL,
    quantity        INT NOT NULL CHECK (quantity > 0),
    expires_at      TIMESTAMPTZ NOT NULL,
    confirmed       BOOLEAN NOT NULL DEFAULT FALSE,
    released        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE catalog_outbox (
    event_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_id    UUID NOT NULL,
    event_type      TEXT NOT NULL,
    payload         JSONB NOT NULL,
    published       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at    TIMESTAMPTZ
);

CREATE INDEX idx_products_category  ON products(category) WHERE deleted_at IS NULL;
CREATE INDEX idx_products_status    ON products(status) WHERE deleted_at IS NULL;
CREATE INDEX idx_products_name_trgm ON products USING GIN(name gin_trgm_ops);
CREATE INDEX idx_reservations_order ON inventory_reservations(order_id);
CREATE INDEX idx_reservations_expiry ON inventory_reservations(expires_at) WHERE confirmed = FALSE AND released = FALSE;
CREATE INDEX idx_catalog_outbox_unpublished ON catalog_outbox(created_at) WHERE published = FALSE;
