"""Tests for the audit ledger."""

from __future__ import annotations

from shared.contracts import AuditAction, AuditEntry
from services.audit_service import AuditLedger


def test_append_entry() -> None:
    ledger = AuditLedger()
    entry = AuditEntry(
        correlation_id="corr-001",
        action=AuditAction.WORKFLOW_SUBMITTED,
        actor="operator@test.com",
    )
    result = ledger.append(entry)
    assert result.entry_hash is not None
    assert result.prev_hash == "GENESIS"
    assert ledger.entry_count == 1


def test_hash_chain_integrity() -> None:
    ledger = AuditLedger()

    for i in range(5):
        entry = AuditEntry(
            correlation_id="corr-chain",
            action=AuditAction.TOOL_EXECUTED,
            actor=f"actor-{i}",
            plugin="defender_xdr",
            tool_action="isolate_device",
        )
        ledger.append(entry)

    is_valid, message = ledger.verify_chain()
    assert is_valid
    assert "5 entries" in message


def test_chain_links_correctly() -> None:
    ledger = AuditLedger()

    entry1 = AuditEntry(
        correlation_id="corr-001",
        action=AuditAction.WORKFLOW_STARTED,
        actor="system",
    )
    result1 = ledger.append(entry1)

    entry2 = AuditEntry(
        correlation_id="corr-001",
        action=AuditAction.TOOL_EXECUTED,
        actor="tool-runner",
    )
    result2 = ledger.append(entry2)

    assert result2.prev_hash == result1.entry_hash


def test_query_by_correlation() -> None:
    ledger = AuditLedger()

    for corr_id in ["corr-a", "corr-a", "corr-b"]:
        entry = AuditEntry(
            correlation_id=corr_id,
            action=AuditAction.TOOL_EXECUTED,
            actor="test",
        )
        ledger.append(entry)

    results = ledger.query(correlation_id="corr-a")
    assert len(results) == 2


def test_query_by_action() -> None:
    ledger = AuditLedger()

    ledger.append(AuditEntry(
        correlation_id="corr-x",
        action=AuditAction.WORKFLOW_STARTED,
        actor="test",
    ))
    ledger.append(AuditEntry(
        correlation_id="corr-x",
        action=AuditAction.TOOL_EXECUTED,
        actor="test",
    ))

    results = ledger.query(action=AuditAction.TOOL_EXECUTED)
    assert len(results) == 1


def test_empty_chain_valid() -> None:
    ledger = AuditLedger()
    is_valid, message = ledger.verify_chain()
    assert is_valid
    assert "Empty ledger" in message
