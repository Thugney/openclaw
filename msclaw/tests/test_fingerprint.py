"""Unit tests for fingerprint determinism and idempotency logic."""

import pytest

from msclaw.shared.idempotency import compute_fingerprint, IdempotencyResult


# ---------------------------------------------------------------------------
# Fingerprint determinism
# ---------------------------------------------------------------------------


def test_fingerprint_deterministic():
    """Same action + params always produce the same fingerprint."""
    fp1 = compute_fingerprint("isolate_device", {"device_id": "D-123"})
    fp2 = compute_fingerprint("isolate_device", {"device_id": "D-123"})
    assert fp1 == fp2
    assert len(fp1) == 64  # SHA-256 hex


def test_fingerprint_key_order_irrelevant():
    """Key ordering in params dict does not change the fingerprint."""
    fp1 = compute_fingerprint("run", {"a": 1, "b": 2, "c": 3})
    fp2 = compute_fingerprint("run", {"c": 3, "a": 1, "b": 2})
    assert fp1 == fp2


def test_fingerprint_different_action_differs():
    """Different actions produce different fingerprints."""
    fp1 = compute_fingerprint("isolate_device", {"device_id": "D-123"})
    fp2 = compute_fingerprint("release_device", {"device_id": "D-123"})
    assert fp1 != fp2


def test_fingerprint_different_params_differs():
    """Different params produce different fingerprints."""
    fp1 = compute_fingerprint("isolate_device", {"device_id": "D-123"})
    fp2 = compute_fingerprint("isolate_device", {"device_id": "D-456"})
    assert fp1 != fp2


def test_fingerprint_empty_params():
    """Empty params produce a valid fingerprint."""
    fp = compute_fingerprint("action", {})
    assert len(fp) == 64


def test_fingerprint_nested_params():
    """Nested params produce a deterministic fingerprint."""
    params = {"device": {"id": "D-123", "tags": ["VIP", "prod"]}, "force": True}
    fp1 = compute_fingerprint("isolate", params)
    fp2 = compute_fingerprint("isolate", params)
    assert fp1 == fp2


# ---------------------------------------------------------------------------
# IdempotencyResult
# ---------------------------------------------------------------------------


def test_idempotency_result_new():
    """New key result."""
    r = IdempotencyResult(is_duplicate=False, is_conflict=False)
    assert not r.is_duplicate
    assert not r.is_conflict


def test_idempotency_result_duplicate():
    """Duplicate key result with prior data."""
    r = IdempotencyResult(
        is_duplicate=True,
        is_conflict=False,
        prior_result={"run_id": "abc"},
        prior_status="completed",
    )
    assert r.is_duplicate
    assert not r.is_conflict
    assert r.prior_result == {"run_id": "abc"}
    assert r.prior_status == "completed"


def test_idempotency_result_conflict():
    """Conflict result."""
    r = IdempotencyResult(
        is_duplicate=False,
        is_conflict=True,
        prior_status="processing",
    )
    assert not r.is_duplicate
    assert r.is_conflict
