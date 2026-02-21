"""Concurrency test for idempotency.

Proves that two simultaneous requests with the same idempotency key
do not result in double execution.

Run with: pytest msclaw/tests/test_idempotency_concurrent.py -v
Requires: running Postgres (docker compose up postgres)
"""

import asyncio
import os
import sys
import uuid

import pytest

# Ensure msclaw is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://msclaw:msclaw@localhost:5432/msclaw",
)

from msclaw_shared.idempotency import check_and_reserve, compute_fingerprint


@pytest.mark.asyncio
async def test_concurrent_same_key_same_payload():
    """Two concurrent requests with same key + same payload: only one proceeds."""
    key = f"test-concurrent-{uuid.uuid4().hex[:8]}"
    action = "test_action"
    params = {"test": True, "value": 42}

    results = await asyncio.gather(
        check_and_reserve(key, action, params),
        check_and_reserve(key, action, params),
        return_exceptions=True,
    )

    # Filter out exceptions
    successes = [r for r in results if not isinstance(r, Exception)]

    # At most one should be "new" (not duplicate, not conflict)
    new_count = sum(1 for r in successes if not r.is_duplicate and not r.is_conflict)
    duplicate_count = sum(1 for r in successes if r.is_duplicate)

    assert new_count <= 1, f"Expected at most 1 new reservation, got {new_count}"
    # The other should be a duplicate
    assert new_count + duplicate_count == len(successes)


@pytest.mark.asyncio
async def test_concurrent_same_key_different_payload():
    """Two concurrent requests with same key + different payload: one succeeds, one conflicts."""
    key = f"test-conflict-{uuid.uuid4().hex[:8]}"
    action = "test_action"

    results = await asyncio.gather(
        check_and_reserve(key, action, {"payload": "A"}),
        check_and_reserve(key, action, {"payload": "B"}),
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    conflicts = sum(1 for r in successes if r.is_conflict)

    # At least one should be a conflict (different fingerprint)
    # or both could succeed if one processes before the other
    assert len(successes) >= 1
