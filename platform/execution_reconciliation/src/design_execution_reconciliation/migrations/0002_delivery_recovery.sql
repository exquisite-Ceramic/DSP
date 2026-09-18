CREATE TABLE IF NOT EXISTS execution_saga.outbox (
    event_id uuid PRIMARY KEY,
    event_fingerprint char(64) NOT NULL,
    event_type text NOT NULL,
    aggregate_ref text NOT NULL,
    aggregate_revision bigint,
    occurred_at timestamptz NOT NULL,
    payload jsonb NOT NULL,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    claimed_until timestamptz,
    published_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_execution_saga_outbox_pending
    ON execution_saga.outbox (published_at, claimed_until, occurred_at);

CREATE TABLE IF NOT EXISTS execution_saga.inbox_receipt (
    event_id uuid PRIMARY KEY,
    event_fingerprint char(64) NOT NULL,
    producer_owner text NOT NULL,
    event_type text NOT NULL,
    source_ref text NOT NULL,
    source_revision bigint,
    processed_at timestamptz NOT NULL,
    result_ref text
);

CREATE TABLE IF NOT EXISTS execution_saga.host_dispatch_intent (
    dispatch_intent_id uuid PRIMARY KEY,
    saga_id text NOT NULL REFERENCES execution_saga.saga_v2(saga_id),
    execution_slice_hash char(64) NOT NULL,
    grant_hash char(64) NOT NULL,
    binding_set_hash char(64) NOT NULL,
    host_instance_id text NOT NULL,
    document_ref text NOT NULL,
    idempotency_key uuid NOT NULL,
    expected_host_revision text,
    status text NOT NULL,
    intent_revision bigint NOT NULL DEFAULT 0 CHECK (intent_revision >= 0),
    prepared_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (saga_id, execution_slice_hash),
    UNIQUE (document_ref, idempotency_key)
);

-- 观察记录只追加，不承担 Saga 状态机权威；后续恢复必须结合 Host/read-back 证据。
CREATE TABLE IF NOT EXISTS execution_saga.host_dispatch_observation (
    observation_id uuid PRIMARY KEY,
    dispatch_intent_id uuid NOT NULL
        REFERENCES execution_saga.host_dispatch_intent(dispatch_intent_id),
    observation_kind text NOT NULL,
    observed_at timestamptz NOT NULL,
    evidence_ref text,
    evidence_hash char(64),
    detail jsonb NOT NULL DEFAULT '{}'::jsonb
);
