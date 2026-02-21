"""MSClaw Audit Service.

Append-only audit ledger with hash chain for tamper evidence.
Every action in the system produces an audit entry with:
- who (actor)
- what (action, plugin, tool)
- when (timestamp)
- inputs/outputs
- model used
- policy decision
- approval chain
- correlation ID

The hash chain links each entry to the previous one,
making it detectable if any entry is modified or deleted.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from ...shared.contracts import AuditAction, AuditEntry

logger = logging.getLogger("msclaw.audit-service")


class AuditLedger:
    """Append-only audit ledger with hash chain."""

    def __init__(self):
        self._entries: list[AuditEntry] = []
        self._last_hash: str = "GENESIS"

    def append(self, entry: AuditEntry) -> AuditEntry:
        """Append an entry to the ledger. Computes and stores hash chain."""
        entry.prev_hash = self._last_hash
        entry.entry_hash = self._compute_hash(entry)
        self._last_hash = entry.entry_hash
        self._entries.append(entry)

        logger.info(
            "AUDIT [%s] %s by %s | target=%s | plugin=%s.%s | hash=%s",
            entry.correlation_id[:8],
            entry.action.value,
            entry.actor,
            entry.target or "-",
            entry.plugin or "-",
            entry.tool_action or "-",
            entry.entry_hash[:12],
        )

        return entry

    def verify_chain(self) -> tuple[bool, str]:
        """Verify the integrity of the entire audit chain.

        Returns (is_valid, message).
        """
        if not self._entries:
            return True, "Empty ledger"

        prev_hash = "GENESIS"
        for i, entry in enumerate(self._entries):
            if entry.prev_hash != prev_hash:
                return False, f"Chain broken at entry {i}: expected prev_hash={prev_hash}, got={entry.prev_hash}"

            computed = self._compute_hash(entry)
            if entry.entry_hash != computed:
                return False, f"Hash mismatch at entry {i}: stored={entry.entry_hash}, computed={computed}"

            prev_hash = entry.entry_hash

        return True, f"Chain verified: {len(self._entries)} entries"

    def query(
        self,
        *,
        correlation_id: str | None = None,
        workflow_run_id: str | None = None,
        action: AuditAction | None = None,
        actor: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Query audit entries with filters."""
        results = self._entries

        if correlation_id:
            results = [e for e in results if e.correlation_id == correlation_id]
        if workflow_run_id:
            results = [e for e in results if e.workflow_run_id == workflow_run_id]
        if action:
            results = [e for e in results if e.action == action]
        if actor:
            results = [e for e in results if e.actor == actor]
        if since:
            results = [e for e in results if e.timestamp >= since]

        return sorted(results, key=lambda e: e.timestamp, reverse=True)[:limit]

    def get_chain(self, correlation_id: str) -> list[AuditEntry]:
        """Get all entries for a correlation ID, in chronological order."""
        entries = [e for e in self._entries if e.correlation_id == correlation_id]
        return sorted(entries, key=lambda e: e.timestamp)

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    @staticmethod
    def _compute_hash(entry: AuditEntry) -> str:
        """Compute SHA-256 hash of an audit entry (excluding the hash fields)."""
        data = {
            "entry_id": entry.entry_id,
            "correlation_id": entry.correlation_id,
            "workflow_run_id": entry.workflow_run_id,
            "action": entry.action.value,
            "actor": entry.actor,
            "target": entry.target,
            "plugin": entry.plugin,
            "tool_action": entry.tool_action,
            "inputs": entry.inputs,
            "outputs": entry.outputs,
            "policy_decision": entry.policy_decision,
            "model_used": entry.model_used,
            "approval_chain": entry.approval_chain,
            "error": entry.error,
            "timestamp": entry.timestamp.isoformat(),
            "prev_hash": entry.prev_hash,
        }
        serialized = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()


# Sample audit entries for documentation
SAMPLE_AUDIT_ENTRIES = [
    {
        "entry_id": "ae-001",
        "correlation_id": "corr-abc123",
        "workflow_run_id": "run-xyz789",
        "action": "workflow.submitted",
        "actor": "operator@contoso.com",
        "target": None,
        "plugin": None,
        "tool_action": None,
        "inputs": {"workflow_id": "contain-device-from-incident", "incidentId": "INC-42"},
        "outputs": None,
        "policy_decision": None,
        "model_used": None,
        "approval_chain": None,
        "error": None,
        "timestamp": "2026-02-21T10:00:00Z",
        "prev_hash": "GENESIS",
        "entry_hash": "a1b2c3d4...",
    },
    {
        "entry_id": "ae-002",
        "correlation_id": "corr-abc123",
        "workflow_run_id": "run-xyz789",
        "action": "tool.policy_checked",
        "actor": "policy-gate",
        "target": "device-001",
        "plugin": "defender_xdr",
        "tool_action": "isolate_device",
        "inputs": {"device_id": "device-001"},
        "outputs": None,
        "policy_decision": "require_approval",
        "model_used": None,
        "approval_chain": None,
        "error": None,
        "timestamp": "2026-02-21T10:00:01Z",
        "prev_hash": "a1b2c3d4...",
        "entry_hash": "e5f6g7h8...",
    },
    {
        "entry_id": "ae-003",
        "correlation_id": "corr-abc123",
        "workflow_run_id": "run-xyz789",
        "action": "tool.approved",
        "actor": "senior-operator@contoso.com",
        "target": "device-001",
        "plugin": "defender_xdr",
        "tool_action": "isolate_device",
        "inputs": None,
        "outputs": None,
        "policy_decision": None,
        "model_used": None,
        "approval_chain": ["senior-operator@contoso.com"],
        "error": None,
        "timestamp": "2026-02-21T10:02:00Z",
        "prev_hash": "e5f6g7h8...",
        "entry_hash": "i9j0k1l2...",
    },
    {
        "entry_id": "ae-004",
        "correlation_id": "corr-abc123",
        "workflow_run_id": "run-xyz789",
        "action": "tool.executed",
        "actor": "tool-runner",
        "target": "device-001",
        "plugin": "defender_xdr",
        "tool_action": "isolate_device",
        "inputs": {"device_id": "device-001"},
        "outputs": {"action_id": "mde-action-456", "status": "Pending", "type": "Isolate"},
        "policy_decision": "allow",
        "model_used": None,
        "approval_chain": ["senior-operator@contoso.com"],
        "error": None,
        "timestamp": "2026-02-21T10:02:05Z",
        "prev_hash": "i9j0k1l2...",
        "entry_hash": "m3n4o5p6...",
    },
]
