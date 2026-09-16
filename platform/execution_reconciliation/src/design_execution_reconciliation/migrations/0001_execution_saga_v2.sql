CREATE SCHEMA IF NOT EXISTS execution_saga;

CREATE TABLE IF NOT EXISTS execution_saga.schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS execution_saga.saga_v2 (
    saga_id text PRIMARY KEY,
    saga_revision bigint NOT NULL CHECK (saga_revision >= 0),
    definition_hash char(64) NOT NULL,
    status text NOT NULL,
    snapshot jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
