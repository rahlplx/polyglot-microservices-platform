-- Analytics Service — Initial Schema (PostgreSQL)
-- ClickHouse migration path: see docs/clickhouse-migration.md

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

CREATE TABLE metric_series (
    series_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_name     TEXT NOT NULL,
    labels          JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE metric_points (
    point_id        BIGSERIAL PRIMARY KEY,
    series_id       UUID NOT NULL REFERENCES metric_series(series_id),
    timestamp       TIMESTAMPTZ NOT NULL,
    value           DOUBLE PRECISION NOT NULL
) PARTITION BY RANGE (timestamp);

-- Create monthly partitions for current + next 3 months
CREATE TABLE metric_points_2026_05 PARTITION OF metric_points
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE metric_points_2026_06 PARTITION OF metric_points
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE metric_points_2026_07 PARTITION OF metric_points
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE metric_points_2026_08 PARTITION OF metric_points
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');

CREATE TABLE reports (
    report_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_type     TEXT NOT NULL,
    format          TEXT NOT NULL DEFAULT 'JSON',
    parameters      JSONB NOT NULL DEFAULT '{}',
    data            JSONB,
    cache_key       TEXT UNIQUE,
    cached_until    TIMESTAMPTZ,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_metric_series_name   ON metric_series(metric_name);
CREATE INDEX idx_metric_series_labels ON metric_series USING GIN(labels);
CREATE INDEX idx_metric_points_series ON metric_points(series_id, timestamp DESC);
CREATE INDEX idx_reports_cache        ON reports(cache_key) WHERE cached_until > NOW();
