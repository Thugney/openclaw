-- MSClaw Database Schema
-- Postgres initialization for local development

-- Workflow runs
CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    inputs          JSONB NOT NULL DEFAULT '{}',
    correlation_id  UUID NOT NULL,
    idempotency_key TEXT UNIQUE NOT NULL,
    operator_id     TEXT NOT NULL,
    steps_completed INTEGER[] DEFAULT '{}',
    step_results    JSONB DEFAULT '{}',
    artifacts       TEXT[] DEFAULT '{}',
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_workflow_runs_status ON workflow_runs(status);
CREATE INDEX idx_workflow_runs_correlation ON workflow_runs(correlation_id);
CREATE INDEX idx_workflow_runs_idempotency ON workflow_runs(idempotency_key);

-- Approval requests
CREATE TABLE IF NOT EXISTS approval_requests (
    approval_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_run_id UUID NOT NULL REFERENCES workflow_runs(run_id),
    step_index      INTEGER NOT NULL,
    plugin          TEXT NOT NULL,
    action          TEXT NOT NULL,
    parameters      JSONB NOT NULL DEFAULT '{}',
    reason          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at      TIMESTAMPTZ,
    decided_by      TEXT,
    decision_note   TEXT
);

CREATE INDEX idx_approval_requests_status ON approval_requests(status);
CREATE INDEX idx_approval_requests_workflow ON approval_requests(workflow_run_id);

-- Audit ledger (append-only)
CREATE TABLE IF NOT EXISTS audit_entries (
    entry_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    correlation_id  UUID NOT NULL,
    workflow_run_id UUID,
    action          TEXT NOT NULL,
    actor           TEXT NOT NULL,
    target          TEXT,
    plugin          TEXT,
    tool_action     TEXT,
    inputs          JSONB,
    outputs         JSONB,
    policy_decision TEXT,
    model_used      TEXT,
    approval_chain  TEXT[],
    error           TEXT,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    prev_hash       TEXT,
    entry_hash      TEXT
);

CREATE INDEX idx_audit_entries_correlation ON audit_entries(correlation_id);
CREATE INDEX idx_audit_entries_workflow ON audit_entries(workflow_run_id);
CREATE INDEX idx_audit_entries_action ON audit_entries(action);
CREATE INDEX idx_audit_entries_timestamp ON audit_entries(timestamp DESC);

-- Idempotency records
CREATE TABLE IF NOT EXISTS idempotency_records (
    idempotency_key TEXT PRIMARY KEY,
    action          TEXT NOT NULL,
    status          TEXT NOT NULL,
    result          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

-- Artifacts metadata
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    correlation_id  UUID NOT NULL,
    artifact_type   TEXT NOT NULL,
    storage_path    TEXT NOT NULL,
    size_bytes      BIGINT,
    metadata        JSONB DEFAULT '{}',
    stored_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_artifacts_correlation ON artifacts(correlation_id);
