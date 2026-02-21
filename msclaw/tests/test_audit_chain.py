"""Unit tests for audit ledger hash chain verification.

Tests verify that:
  1. A valid chain passes verification
  2. A broken prev_hash link is detected
  3. Tampered content (modified entry_data) is detected
  4. An empty chain is valid
"""

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from msclaw.shared.audit import _canonical_json, _compute_hash, verify_chain


# ---------------------------------------------------------------------------
# Helper: build a mock audit chain
# ---------------------------------------------------------------------------

def _make_entry(
    entry_id: int,
    actor: str,
    action: str,
    prev_hash: str | None,
    correlation_id: str = "00000000-0000-0000-0000-000000000001",
    run_id: str | None = None,
    step_id: str | None = None,
    detail: dict | None = None,
    policy_decision: str | None = None,
    approval_chain: list | None = None,
    tool: str | None = None,
    adapter_mode: str | None = None,
    model: str | None = None,
):
    """Create a mock AuditEntry with correctly computed entry_hash."""
    entry_data = {
        "correlation_id": correlation_id,
        "run_id": run_id,
        "step_id": step_id,
        "actor": actor,
        "action": action,
        "detail": detail or {},
        "policy_decision": policy_decision,
        "approval_chain": approval_chain or [],
        "tool": tool,
        "adapter_mode": adapter_mode,
        "model": model,
    }
    entry_hash = _compute_hash(prev_hash, entry_data)

    entry = MagicMock()
    entry.id = entry_id
    entry.correlation_id = correlation_id
    entry.run_id = run_id
    entry.step_id = step_id
    entry.actor = actor
    entry.action = action
    entry.detail = detail or {}
    entry.policy_decision = policy_decision
    entry.approval_chain = approval_chain or []
    entry.tool = tool
    entry.adapter_mode = adapter_mode
    entry.model = model
    entry.prev_hash = prev_hash
    entry.entry_hash = entry_hash
    return entry


def _build_valid_chain(length: int = 3) -> list:
    """Build a valid chain of mock audit entries."""
    entries = []
    prev = None
    for i in range(length):
        e = _make_entry(
            entry_id=i + 1,
            actor=f"actor_{i}",
            action=f"action_{i}",
            prev_hash=prev,
        )
        prev = e.entry_hash
        entries.append(e)
    return entries


# ---------------------------------------------------------------------------
# Tests for _compute_hash
# ---------------------------------------------------------------------------


def test_compute_hash_deterministic():
    """Same inputs produce the same hash."""
    data = {"actor": "alice", "action": "submit"}
    h1 = _compute_hash("prev123", data)
    h2 = _compute_hash("prev123", data)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_compute_hash_genesis():
    """First entry (no prev_hash) hashes correctly."""
    data = {"actor": "system", "action": "init"}
    h = _compute_hash(None, data)
    expected = hashlib.sha256(
        ("" + _canonical_json(data)).encode()
    ).hexdigest()
    assert h == expected


def test_compute_hash_different_prev_produces_different_hash():
    data = {"actor": "bob", "action": "run"}
    h1 = _compute_hash("aaa", data)
    h2 = _compute_hash("bbb", data)
    assert h1 != h2


def test_compute_hash_different_data_produces_different_hash():
    h1 = _compute_hash("prev", {"actor": "alice", "action": "run"})
    h2 = _compute_hash("prev", {"actor": "alice", "action": "deny"})
    assert h1 != h2


# ---------------------------------------------------------------------------
# Tests for _canonical_json
# ---------------------------------------------------------------------------


def test_canonical_json_key_order_irrelevant():
    """JSON canonicalization sorts keys."""
    a = _canonical_json({"b": 2, "a": 1})
    b = _canonical_json({"a": 1, "b": 2})
    assert a == b


def test_canonical_json_compact():
    """No extra whitespace in canonical form."""
    result = _canonical_json({"key": "value"})
    assert " " not in result


# ---------------------------------------------------------------------------
# Tests for verify_chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_chain_valid():
    """A correctly built chain should verify."""
    entries = _build_valid_chain(5)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = entries

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    ok, errors = await verify_chain(session=mock_session)
    assert ok is True
    assert errors == []


@pytest.mark.asyncio
async def test_verify_chain_broken_prev_hash():
    """Detect a broken prev_hash link."""
    entries = _build_valid_chain(3)
    # Corrupt the second entry's prev_hash
    entries[1].prev_hash = "corrupted_prev_hash_value"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = entries

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    ok, errors = await verify_chain(session=mock_session)
    assert ok is False
    assert len(errors) >= 1
    assert "prev_hash mismatch" in errors[0]


@pytest.mark.asyncio
async def test_verify_chain_tampered_content():
    """Detect content tampering (entry_hash won't match recomputed hash)."""
    entries = _build_valid_chain(3)
    # Tamper with the second entry's action field (but keep entry_hash unchanged)
    entries[1].action = "TAMPERED_ACTION"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = entries

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    ok, errors = await verify_chain(session=mock_session)
    assert ok is False
    assert any("entry_hash mismatch" in e for e in errors)


@pytest.mark.asyncio
async def test_verify_chain_empty():
    """An empty chain is valid."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    ok, errors = await verify_chain(session=mock_session)
    assert ok is True
    assert errors == []


@pytest.mark.asyncio
async def test_verify_chain_single_entry():
    """A single-entry chain should verify."""
    entries = _build_valid_chain(1)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = entries

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    ok, errors = await verify_chain(session=mock_session)
    assert ok is True
    assert errors == []
