-- Notification Service — Initial Schema

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TYPE notification_channel AS ENUM ('EMAIL', 'SMS', 'PUSH', 'WEBHOOK', 'IN_APP');
CREATE TYPE notification_status  AS ENUM ('PENDING', 'SENT', 'DELIVERED', 'FAILED', 'DEFERRED');
CREATE TYPE notification_priority AS ENUM ('LOW', 'NORMAL', 'HIGH', 'CRITICAL');

CREATE TABLE notifications (
    notification_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_id        TEXT NOT NULL,
    recipient_address   TEXT NOT NULL,
    channel             notification_channel NOT NULL,
    priority            notification_priority NOT NULL DEFAULT 'NORMAL',
    template_id         TEXT NOT NULL,
    subject             TEXT,
    body                TEXT NOT NULL,
    status              notification_status NOT NULL DEFAULT 'PENDING',
    idempotency_key     TEXT UNIQUE NOT NULL,
    retry_count         INT NOT NULL DEFAULT 0,
    max_retries         INT NOT NULL DEFAULT 3,
    next_retry_at       TIMESTAMPTZ,
    sent_at             TIMESTAMPTZ,
    delivered_at        TIMESTAMPTZ,
    failure_reason      TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE recipient_preferences (
    preference_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_id    TEXT UNIQUE NOT NULL,
    channels        notification_channel[] NOT NULL DEFAULT '{EMAIL}',
    quiet_hours_start TIME,
    quiet_hours_end   TIME,
    timezone        TEXT NOT NULL DEFAULT 'UTC',
    opted_out       BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_notifications_recipient ON notifications(recipient_id);
CREATE INDEX idx_notifications_status    ON notifications(status);
CREATE INDEX idx_notifications_retry     ON notifications(next_retry_at) WHERE status = 'FAILED' AND retry_count < max_retries;
