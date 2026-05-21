-- Order Service — Initial Schema
-- Flyway managed. Run via: ./gradlew flywayMigrate

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TYPE order_status AS ENUM (
    'PENDING', 'CONFIRMED', 'PROCESSING', 'SHIPPED', 'DELIVERED', 'CANCELLED', 'REFUNDED'
);

CREATE TABLE orders (
    order_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id     TEXT NOT NULL,
    status          order_status NOT NULL DEFAULT 'PENDING',
    currency_code   CHAR(3) NOT NULL,
    total_units     BIGINT NOT NULL DEFAULT 0,
    total_nanos     INT NOT NULL DEFAULT 0,
    shipping_line1  TEXT NOT NULL,
    shipping_city   TEXT NOT NULL,
    shipping_state  TEXT,
    shipping_postal TEXT NOT NULL,
    shipping_country CHAR(2) NOT NULL,
    payment_id      TEXT,
    idempotency_key TEXT UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

CREATE TABLE order_lines (
    line_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES orders(order_id),
    product_id      TEXT NOT NULL,
    product_name    TEXT NOT NULL,
    quantity        INT NOT NULL CHECK (quantity > 0),
    unit_currency   CHAR(3) NOT NULL,
    unit_units      BIGINT NOT NULL,
    unit_nanos      INT NOT NULL DEFAULT 0,
    reservation_id  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE order_outbox (
    event_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_id    UUID NOT NULL,
    event_type      TEXT NOT NULL,
    payload         JSONB NOT NULL,
    published       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at    TIMESTAMPTZ
);

CREATE TABLE saga_instances (
    saga_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES orders(order_id),
    saga_type       TEXT NOT NULL,
    current_step    INT NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'RUNNING',
    context         JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_orders_customer   ON orders(customer_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_orders_status     ON orders(status) WHERE deleted_at IS NULL;
CREATE INDEX idx_order_lines_order ON order_lines(order_id);
CREATE INDEX idx_outbox_unpublished ON order_outbox(created_at) WHERE published = FALSE;
CREATE INDEX idx_saga_order        ON saga_instances(order_id);
