-- Payment Service — Initial Schema

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TYPE payment_status AS ENUM (
    'PENDING', 'PROCESSING', 'SUCCEEDED', 'FAILED', 'REFUNDED', 'PARTIALLY_REFUNDED', 'CANCELLED'
);

CREATE TYPE payment_gateway AS ENUM ('STRIPE', 'ADYEN', 'BRAINTREE', 'MOCK');

CREATE TABLE payments (
    payment_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id            UUID NOT NULL,
    customer_id         TEXT NOT NULL,
    gateway             payment_gateway NOT NULL,
    gateway_payment_id  TEXT UNIQUE,
    status              payment_status NOT NULL DEFAULT 'PENDING',
    currency_code       CHAR(3) NOT NULL,
    amount_units        BIGINT NOT NULL,
    amount_nanos        INT NOT NULL DEFAULT 0,
    refunded_units      BIGINT NOT NULL DEFAULT 0,
    refunded_nanos      INT NOT NULL DEFAULT 0,
    idempotency_key     TEXT UNIQUE NOT NULL,
    failure_reason      TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ
);

CREATE TABLE refunds (
    refund_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payment_id          UUID NOT NULL REFERENCES payments(payment_id),
    currency_code       CHAR(3) NOT NULL,
    amount_units        BIGINT NOT NULL,
    amount_nanos        INT NOT NULL DEFAULT 0,
    reason              TEXT NOT NULL,
    gateway_refund_id   TEXT,
    status              TEXT NOT NULL DEFAULT 'PENDING',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE payment_outbox (
    event_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_id    UUID NOT NULL,
    event_type      TEXT NOT NULL,
    payload         JSONB NOT NULL,
    published       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at    TIMESTAMPTZ
);

CREATE INDEX idx_payments_order     ON payments(order_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_payments_customer  ON payments(customer_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_payments_status    ON payments(status) WHERE deleted_at IS NULL;
CREATE INDEX idx_refunds_payment    ON refunds(payment_id);
CREATE INDEX idx_payment_outbox_unpublished ON payment_outbox(created_at) WHERE published = FALSE;
