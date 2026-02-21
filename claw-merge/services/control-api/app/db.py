"""Control API database layer – workflow runs, approvals, idempotency."""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

from msclaw_shared.models.workflow import WorkflowRun, WorkflowStatus
from msclaw_shared.models.approval import ApprovalRequest, ApprovalStatus

logger = logging.getLogger("msclaw.control_api.db")

SCHEMA_SQL = """
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

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key             TEXT PRIMARY KEY,
    result          JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


class ControlDB:
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=10)
        logger.info("Connected to control database")

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()

    async def ensure_schema(self) -> None:
        if not self._pool:
            raise RuntimeError("Not connected")
        async with self._pool.acquire() as conn:
            await conn.execute(SCHEMA_SQL)
        logger.info("Control schema ensured")

    # -- Idempotency --

    async def check_idempotency(self, key: str) -> dict | None:
        if not self._pool:
            raise RuntimeError("Not connected")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT result FROM idempotency_keys WHERE key = $1", key)
            if row:
                return json.loads(row["result"]) if isinstance(row["result"], str) else row["result"]
            return None

    async def store_idempotency(self, key: str, result: dict) -> None:
        if not self._pool:
            raise RuntimeError("Not connected")
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO idempotency_keys (key, result) VALUES ($1, $2) ON CONFLICT (key) DO NOTHING",
                key, json.dumps(result),
            )

    # -- Workflow Runs --

    async def create_workflow_run(self, run: WorkflowRun) -> WorkflowRun:
        if not self._pool:
            raise RuntimeError("Not connected")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workflow_runs (
                    run_id, correlation_id, workflow_name, status, idempotency_key,
                    submitted_by, submitted_at, inputs, steps, outputs, error, tags
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """,
                run.run_id, run.correlation_id, run.workflow_name, run.status.value,
                run.idempotency_key, run.submitted_by, run.submitted_at,
                json.dumps(run.inputs),
                json.dumps([s.model_dump(mode="json") for s in run.steps]),
                json.dumps(run.outputs),
                run.error,
                json.dumps(run.tags),
            )
        return run

    async def get_workflow_run(self, run_id: str) -> WorkflowRun | None:
        if not self._pool:
            raise RuntimeError("Not connected")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM workflow_runs WHERE run_id = $1", run_id)
            return self._row_to_workflow_run(row) if row else None

    async def update_workflow_status(
        self, run_id: str, status: WorkflowStatus, **kwargs: Any
    ) -> None:
        if not self._pool:
            raise RuntimeError("Not connected")
        sets = ["status = $2"]
        params: list[Any] = [run_id, status.value]
        idx = 3
        for key, val in kwargs.items():
            if val is not None:
                if isinstance(val, (dict, list)):
                    val = json.dumps(val)
                sets.append(f"{key} = ${idx}")
                params.append(val)
                idx += 1
        query = f"UPDATE workflow_runs SET {', '.join(sets)} WHERE run_id = $1"
        async with self._pool.acquire() as conn:
            await conn.execute(query, *params)

    async def list_workflow_runs(
        self, offset: int = 0, limit: int = 50, status: str | None = None
    ) -> list[WorkflowRun]:
        if not self._pool:
            raise RuntimeError("Not connected")
        async with self._pool.acquire() as conn:
            if status:
                rows = await conn.fetch(
                    "SELECT * FROM workflow_runs WHERE status = $1 ORDER BY submitted_at DESC OFFSET $2 LIMIT $3",
                    status, offset, limit,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM workflow_runs ORDER BY submitted_at DESC OFFSET $1 LIMIT $2",
                    offset, limit,
                )
            return [self._row_to_workflow_run(r) for r in rows]

    # -- Approvals --

    async def create_approval(self, approval: ApprovalRequest) -> ApprovalRequest:
        if not self._pool:
            raise RuntimeError("Not connected")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO approval_requests (
                    approval_id, correlation_id, workflow_run_id, step_id, intent_id,
                    plugin, action, inputs, requested_by, requested_at, status,
                    required_approvers, policy_reason
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                approval.approval_id, approval.correlation_id, approval.workflow_run_id,
                approval.step_id, approval.intent_id, approval.plugin, approval.action,
                json.dumps(approval.inputs), approval.requested_by, approval.requested_at,
                approval.status.value, json.dumps(approval.required_approvers),
                approval.policy_reason,
            )
        return approval

    async def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        if not self._pool:
            raise RuntimeError("Not connected")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM approval_requests WHERE approval_id = $1", approval_id
            )
            return self._row_to_approval(row) if row else None

    async def list_pending_approvals(self, offset: int = 0, limit: int = 50) -> list[ApprovalRequest]:
        if not self._pool:
            raise RuntimeError("Not connected")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM approval_requests WHERE status = 'pending' ORDER BY requested_at DESC OFFSET $1 LIMIT $2",
                offset, limit,
            )
            return [self._row_to_approval(r) for r in rows]

    async def decide_approval(
        self, approval_id: str, status: ApprovalStatus, decided_by: str, reason: str = ""
    ) -> None:
        if not self._pool:
            raise RuntimeError("Not connected")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE approval_requests
                SET status = $2, decided_by = $3, decided_at = NOW(), decision_reason = $4
                WHERE approval_id = $1 AND status = 'pending'
                """,
                approval_id, status.value, decided_by, reason,
            )

    @staticmethod
    def _row_to_workflow_run(row: asyncpg.Record) -> WorkflowRun:
        return WorkflowRun(
            run_id=row["run_id"],
            correlation_id=row["correlation_id"],
            workflow_name=row["workflow_name"],
            status=WorkflowStatus(row["status"]),
            idempotency_key=row["idempotency_key"],
            submitted_by=row["submitted_by"],
            submitted_at=row["submitted_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            inputs=json.loads(row["inputs"]) if isinstance(row["inputs"], str) else row["inputs"],
            steps=json.loads(row["steps"]) if isinstance(row["steps"], str) else row["steps"],
            outputs=json.loads(row["outputs"]) if isinstance(row["outputs"], str) else row["outputs"],
            error=row["error"],
            tags=json.loads(row["tags"]) if isinstance(row["tags"], str) else row["tags"],
        )

    @staticmethod
    def _row_to_approval(row: asyncpg.Record) -> ApprovalRequest:
        return ApprovalRequest(
            approval_id=row["approval_id"],
            correlation_id=row["correlation_id"],
            workflow_run_id=row["workflow_run_id"],
            step_id=row["step_id"],
            intent_id=row["intent_id"],
            plugin=row["plugin"],
            action=row["action"],
            inputs=json.loads(row["inputs"]) if isinstance(row["inputs"], str) else row["inputs"],
            requested_by=row["requested_by"],
            requested_at=row["requested_at"],
            status=ApprovalStatus(row["status"]),
            required_approvers=json.loads(row["required_approvers"]) if isinstance(row["required_approvers"], str) else row["required_approvers"],
            policy_reason=row["policy_reason"],
            decided_by=row["decided_by"],
            decided_at=row["decided_at"],
            decision_reason=row["decision_reason"],
        )
