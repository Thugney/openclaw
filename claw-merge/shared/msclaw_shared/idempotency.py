"""Durable idempotency enforcement backed by Postgres unique constraints.

Rules:
  1. Same key + same action fingerprint → return prior result (no re-execute)
  2. Same key + different fingerprint → reject with 409 and audit
  3. New key → insert and proceed
  4. Concurrent submissions serialized via SELECT … FOR UPDATE SKIP LOCKED
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text as sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .db import IdempotencyKey, get_session

logger = logging.getLogger("msclaw.idempotency")


def compute_fingerprint(action: str, params: dict[str, Any]) -> str:
    """Deterministic fingerprint of an action + its parameters."""
    canonical = json.dumps(
        {"action": action, "params": params},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class IdempotencyResult:
    """Outcome of an idempotency check."""

    def __init__(
        self,
        *,
        is_duplicate: bool,
        is_conflict: bool,
        prior_result: dict | None = None,
        prior_status: str | None = None,
    ):
        self.is_duplicate = is_duplicate
        self.is_conflict = is_conflict
        self.prior_result = prior_result
        self.prior_status = prior_status


async def check_and_reserve(
    key: str,
    action: str,
    params: dict[str, Any],
    session: AsyncSession | None = None,
) -> IdempotencyResult:
    """Check idempotency key and reserve if new.

    Uses Postgres INSERT … ON CONFLICT to guarantee atomicity.
    """
    fingerprint = compute_fingerprint(action, params)

    async def _do(sess: AsyncSession) -> IdempotencyResult:
        # Try to lock existing row first
        existing = await sess.execute(
            select(IdempotencyKey)
            .where(IdempotencyKey.key == key)
            .with_for_update(skip_locked=True)
        )
        row = existing.scalar_one_or_none()

        if row is not None:
            if row.action_fingerprint == fingerprint:
                # Duplicate – return prior result
                logger.info(
                    "Idempotency hit: key=%s status=%s", key, row.status
                )
                return IdempotencyResult(
                    is_duplicate=True,
                    is_conflict=False,
                    prior_result=row.result,
                    prior_status=row.status,
                )
            else:
                # Conflict – same key, different payload
                logger.warning(
                    "Idempotency conflict: key=%s existing_fp=%s new_fp=%s",
                    key,
                    row.action_fingerprint[:12],
                    fingerprint[:12],
                )
                return IdempotencyResult(
                    is_duplicate=False,
                    is_conflict=True,
                    prior_status=row.status,
                )

        # New key – insert
        stmt = pg_insert(IdempotencyKey).values(
            key=key,
            action_fingerprint=fingerprint,
            status="processing",
        ).on_conflict_do_nothing(index_elements=["key"])

        result = await sess.execute(stmt)
        if result.rowcount == 0:
            # Race condition – another transaction inserted first
            # Re-read and check
            existing2 = await sess.execute(
                select(IdempotencyKey).where(IdempotencyKey.key == key)
            )
            row2 = existing2.scalar_one_or_none()
            if row2 and row2.action_fingerprint == fingerprint:
                return IdempotencyResult(
                    is_duplicate=True,
                    is_conflict=False,
                    prior_result=row2.result,
                    prior_status=row2.status,
                )
            return IdempotencyResult(is_duplicate=False, is_conflict=True)

        await sess.flush()
        logger.info("Idempotency key reserved: key=%s", key)
        return IdempotencyResult(is_duplicate=False, is_conflict=False)

    if session:
        return await _do(session)
    else:
        async with get_session() as sess:
            return await _do(sess)


async def mark_completed(
    key: str,
    result: dict[str, Any] | None = None,
    session: AsyncSession | None = None,
) -> None:
    """Mark an idempotency key as completed with its result."""

    async def _do(sess: AsyncSession) -> None:
        row = await sess.execute(
            select(IdempotencyKey)
            .where(IdempotencyKey.key == key)
            .with_for_update()
        )
        entry = row.scalar_one_or_none()
        if entry:
            entry.status = "completed"
            entry.result = result
            entry.completed_at = datetime.now(timezone.utc)
            await sess.flush()

    if session:
        await _do(session)
    else:
        async with get_session() as sess:
            await _do(sess)


async def mark_failed(
    key: str,
    error: str | None = None,
    session: AsyncSession | None = None,
) -> None:
    """Mark an idempotency key as failed."""

    async def _do(sess: AsyncSession) -> None:
        row = await sess.execute(
            select(IdempotencyKey)
            .where(IdempotencyKey.key == key)
            .with_for_update()
        )
        entry = row.scalar_one_or_none()
        if entry:
            entry.status = "failed"
            entry.result = {"error": error} if error else None
            entry.completed_at = datetime.now(timezone.utc)
            await sess.flush()

    if session:
        await _do(session)
    else:
        async with get_session() as sess:
            await _do(sess)
