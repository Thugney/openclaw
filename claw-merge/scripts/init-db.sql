-- MSClaw database initialization script
-- Run against PostgreSQL to create all required tables

-- Workflow runs
CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id          TEXT PRIMARY KEY,
    correlation_id  TEXT NOT NULL,
    workflow_name   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    idempotency_key TEXT NOT NULL UNIQUE,
    submitted_by    TEXT NOT NULL,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    inputs          JSONB NOT NULL DEFAULT '{}',
    steps           JSONB NOT NULL DEFAULT '[]',
    outputs         JSONB NOT NULL DEFAULT '{}',
    error           TEXT,
    tags            JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_wf_status ON workflow_runs(status);
CREATE INDEX IF NOT EXISTS idx_wf_correlation ON workflow_runs(correlation_id);
CREATE INDEX IF NOT EXISTS idx_wf_idempotency ON workflow_runs(idempotency_key);

-- Approval requests
CREATE TABLE IF NOT EXISTS approval_requests (
    approval_id     TEXT PRIMARY KEY,
    correlation_id  TEXT NOT NULL,
    workflow_run_id TEXT,
    step_id         TEXT,
    intent_id       TEXT NOT NULL,
    plugin          TEXT NOT NULL,
    action          TEXT NOT NULL,
    inputs          JSONB NOT NULL DEFAULT '{}',
    requested_by    TEXT NOT NULL,
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status          TEXT NOT NULL DEFAULT 'pending',
    required_approvers JSONB NOT NULL DEFAULT '[]',
    policy_reason   TEXT NOT NULL DEFAULT '',
    decided_by      TEXT,
    decided_at      TIMESTAMPTZ,
    decision_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status);
CREATE INDEX IF NOT EXISTS idx_approval_correlation ON approval_requests(correlation_id);
CREATE INDEX IF NOT EXISTS idx_approval_workflow ON approval_requests(workflow_run_id);

-- Idempotency keys
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key             TEXT PRIMARY KEY,
    result          JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Audit entries
CREATE TABLE IF NOT EXISTS audit_entries (
    id              TEXT PRIMARY KEY,
    correlation_id  TEXT NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor           TEXT NOT NULL,
    actor_type      TEXT NOT NULL DEFAULT 'user',
    action          TEXT NOT NULL,
    service         TEXT NOT NULL,
    inputs          JSONB NOT NULL DEFAULT '{}',
    outputs         JSONB NOT NULL DEFAULT '{}',
    model_id        TEXT,
    model_provider  TEXT,
    tool_name       TEXT,
    idempotency_key TEXT,
    policy_decision TEXT,
    policy_rule     TEXT,
    policy_reason   TEXT,
    approval_chain  JSONB NOT NULL DEFAULT '[]',
    previous_hash   TEXT,
    entry_hash      TEXT NOT NULL,
    tags            JSONB NOT NULL DEFAULT '{}',
    error           TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_correlation ON audit_entries(correlation_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_entries(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_entries(actor);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_entries(action);
CREATE INDEX IF NOT EXISTS idx_audit_idempotency ON audit_entries(idempotency_key);
