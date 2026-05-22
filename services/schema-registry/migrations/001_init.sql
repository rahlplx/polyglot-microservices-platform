-- Schema Registry Service — Initial Schema

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TYPE schema_type AS ENUM ('PROTOBUF', 'AVRO', 'JSON_SCHEMA', 'THRIFT');
CREATE TYPE compatibility_level AS ENUM (
    'NONE', 'BACKWARD', 'BACKWARD_TRANSITIVE',
    'FORWARD', 'FORWARD_TRANSITIVE', 'FULL', 'FULL_TRANSITIVE'
);

CREATE TABLE subjects (
    subject_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_name        TEXT UNIQUE NOT NULL,
    compatibility_level compatibility_level NOT NULL DEFAULT 'BACKWARD',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ
);

CREATE TABLE schemas (
    schema_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id      UUID NOT NULL REFERENCES subjects(subject_id),
    version         INT NOT NULL,
    schema_type     schema_type NOT NULL DEFAULT 'PROTOBUF',
    definition      TEXT NOT NULL,
    fingerprint     TEXT NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,
    UNIQUE (subject_id, version),
    UNIQUE (subject_id, fingerprint)
);

CREATE INDEX idx_subjects_name    ON subjects(subject_name) WHERE deleted_at IS NULL;
CREATE INDEX idx_schemas_subject  ON schemas(subject_id, version DESC) WHERE deleted_at IS NULL;
CREATE INDEX idx_schemas_fingerprint ON schemas(fingerprint);
