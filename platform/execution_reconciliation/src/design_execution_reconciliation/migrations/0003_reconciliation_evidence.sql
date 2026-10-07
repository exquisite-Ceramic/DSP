CREATE TABLE IF NOT EXISTS execution_saga.reconciliation_evidence (
    evidence_hash char(64) PRIMARY KEY,
    evidence_kind text NOT NULL,
    codec_version integer NOT NULL CHECK (codec_version > 0),
    body jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_execution_saga_reconciliation_evidence_kind
    ON execution_saga.reconciliation_evidence (evidence_kind, created_at);
