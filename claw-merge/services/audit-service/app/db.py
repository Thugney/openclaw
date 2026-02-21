"""Audit database layer – append-only with hash chain."""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

from msclaw_shared.models.audit import AuditEntry
from msclaw_shared.models.common import sha256_hex

logger = logging.getLogger("msclaw.audit.db")

SCHEMA_SQL = """
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
"""


class AuditDB:
    """Append-only audit database with hash chain for tamper evidence."""

    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None
        self._last_hash: str | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=10)
        logger.info("Connected to audit database")
        # Load the last hash for chain continuity
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT entry_hash FROM audit_entries ORDER BY timestamp DESC LIMIT 1"
            )
            if row:
                self._last_hash = row["entry_hash"]

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()

    async def ensure_schema(self) -> None:
        if not self._pool:
            raise RuntimeError("Not connected")
        async with self._pool.acquire() as conn:
            await conn.execute(SCHEMA_SQL)
        logger.info("Audit schema ensured")

    def _compute_hash(self, entry: AuditEntry) -> str:
        """Compute SHA-256 hash of entry content + previous hash."""
        content = entry.model_dump_json(exclude={"entry_hash", "previous_hash"})
        chain_input = f"{self._last_hash or 'GENESIS'}:{content}"
        return sha256_hex(chain_input.encode("utf-8"))

    async def append(self, entry: AuditEntry) -> AuditEntry:
        """Append an audit entry. This is append-only – no updates or deletes."""
        if not self._pool:
            raise RuntimeError("Not connected")

        entry.previous_hash = self._last_hash
        entry.entry_hash = self._compute_hash(entry)

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_entries (
                    id, correlation_id, timestamp, actor, actor_type,
                    action, service, inputs, outputs,
                    model_id, model_provider, tool_name, idempotency_key,
                    policy_decision, policy_rule, policy_reason,
                    approval_chain, previous_hash, entry_hash, tags, error
                ) VALUES (
                    $1, $2, $3, $4, $5,
                    $6, $7, $8, $9,
                    $10, $11, $12, $13,
                    $14, $15, $16,
                    $17, $18, $19, $20, $21
                )
                """,
                entry.id,
                entry.correlation_id,
                entry.timestamp,
                entry.actor,
                entry.actor_type,
                entry.action,
                entry.service,
                json.dumps(entry.inputs),
                json.dumps(entry.outputs),
                entry.model_id,
                entry.model_provider,
                entry.tool_name,
                entry.idempotency_key,
                entry.policy_decision.value if entry.policy_decision else None,
                entry.policy_rule,
                entry.policy_reason,
                json.dumps([r.model_dump(mode="json") for r in entry.approval_chain]),
                entry.previous_hash,
                entry.entry_hash,
                json.dumps(entry.tags),
                entry.error,
            )

        self._last_hash = entry.entry_hash
        logger.info("Audit entry appended: %s (action=%s)", entry.id, entry.action)
        return entry

    async def get_by_id(self, entry_id: str) -> AuditEntry | None:
        if not self._pool:
            raise RuntimeError("Not connected")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM audit_entries WHERE id = $1", entry_id)
            return self._row_to_entry(row) if row else None

    async def get_by_correlation_id(self, correlation_id: str) -> list[AuditEntry]:
        if not self._pool:
            raise RuntimeError("Not connected")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM audit_entries WHERE correlation_id = $1 ORDER BY timestamp",
                correlation_id,
            )
            return [self._row_to_entry(r) for r in rows]

    async def list_entries(
        self, offset: int = 0, limit: int = 50, action: str | None = None
    ) -> list[AuditEntry]:
        if not self._pool:
            raise RuntimeError("Not connected")
        async with self._pool.acquire() as conn:
            if action:
                rows = await conn.fetch(
                    "SELECT * FROM audit_entries WHERE action = $1 ORDER BY timestamp DESC OFFSET $2 LIMIT $3",
                    action, offset, limit,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM audit_entries ORDER BY timestamp DESC OFFSET $1 LIMIT $2",
                    offset, limit,
                )
            return [self._row_to_entry(r) for r in rows]

    async def verify_chain(self, limit: int = 100) -> tuple[bool, str]:
        """Verify the hash chain integrity of the last N entries."""
        if not self._pool:
            raise RuntimeError("Not connected")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM audit_entries ORDER BY timestamp ASC LIMIT $1", limit
            )

        prev_hash: str | None = None
        for row in rows:
            entry = self._row_to_entry(row)
            if entry.previous_hash != prev_hash:
                return False, f"Chain broken at entry {entry.id}"
            prev_hash = entry.entry_hash
        return True, "Chain verified"

    @staticmethod
    def _row_to_entry(row: asyncpg.Record) -> AuditEntry:
        return AuditEntry(
            id=row["id"],
            correlation_id=row["correlation_id"],
            timestamp=row["timestamp"],
            actor=row["actor"],
            actor_type=row["actor_type"],
            action=row["action"],
            service=row["service"],
            inputs=json.loads(row["inputs"]) if isinstance(row["inputs"], str) else row["inputs"],
            outputs=json.loads(row["outputs"]) if isinstance(row["outputs"], str) else row["outputs"],
            model_id=row["model_id"],
            model_provider=row["model_provider"],
            tool_name=row["tool_name"],
            idempotency_key=row["idempotency_key"],
            policy_decision=row["policy_decision"],
            policy_rule=row["policy_rule"],
            policy_reason=row["policy_reason"],
            approval_chain=json.loads(row["approval_chain"]) if isinstance(row["approval_chain"], str) else row["approval_chain"],
            previous_hash=row["previous_hash"],
            entry_hash=row["entry_hash"],
            tags=json.loads(row["tags"]) if isinstance(row["tags"], str) else row["tags"],
            error=row["error"],
        )
