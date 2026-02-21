"""Durable, append-only, hash-chained audit ledger.

Every workflow step, policy decision, approval action, and tool execution
produces at least one audit entry.  Entries are hash-chained (SHA-256) so
tamper is detectable.  A CLI command can verify the entire chain.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from .db import AuditEntry, get_session

logger = logging.getLogger("msclaw.audit")


def _canonical_json(obj: dict[str, Any]) -> str:
    """Deterministic JSON for hashing."""
    return json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))


def _compute_hash(prev_hash: str | None, entry_data: dict[str, Any]) -> str:
    """SHA-256 over prev_hash + canonical JSON of entry data."""
    payload = (prev_hash or "") + _canonical_json(entry_data)
    return hashlib.sha256(payload.encode()).hexdigest()


async def _get_last_hash(session: AsyncSession) -> str | None:
    """Get the entry_hash of the most recent audit entry."""
    result = await session.execute(
        select(AuditEntry.entry_hash)
        .order_by(AuditEntry.id.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return row


async def append_audit(
    *,
    correlation_id: str | UUID,
    actor: str,
    action: str,
    run_id: str | UUID | None = None,
    step_id: str | UUID | None = None,
    detail: dict[str, Any] | None = None,
    policy_decision: str | None = None,
    approval_chain: list[dict] | None = None,
    tool: str | None = None,
    adapter_mode: str | None = None,
    model: str | None = None,
    session: AsyncSession | None = None,
) -> AuditEntry:
    """Create a new hash-chained audit entry (append-only)."""

    async def _do(sess: AsyncSession) -> AuditEntry:
        # Lock to serialize inserts and guarantee chain integrity
        await sess.execute(sa_text("SELECT pg_advisory_xact_lock(42)"))

        prev_hash = await _get_last_hash(sess)

        # Use a single timestamp for both the hash and the DB row so
        # verify_chain can deterministically recompute the hash.
        now = datetime.now(timezone.utc)

        entry_data = {
            "correlation_id": str(correlation_id),
            "run_id": str(run_id) if run_id else None,
            "step_id": str(step_id) if step_id else None,
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

        entry = AuditEntry(
            correlation_id=correlation_id if isinstance(correlation_id, UUID) else UUID(str(correlation_id)),
            run_id=run_id if isinstance(run_id, UUID) or run_id is None else UUID(str(run_id)),
            step_id=step_id if isinstance(step_id, UUID) or step_id is None else UUID(str(step_id)),
            actor=actor,
            action=action,
            detail=detail or {},
            policy_decision=policy_decision,
            approval_chain=approval_chain or [],
            tool=tool,
            adapter_mode=adapter_mode,
            model=model,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
            created_at=now,
        )
        sess.add(entry)
        await sess.flush()
        logger.info(
            "Audit #%s  action=%s  corr=%s  hash=%s",
            entry.id,
            action,
            correlation_id,
            entry_hash[:12],
        )
        return entry

    if session:
        return await _do(session)
    else:
        async with get_session() as sess:
            return await _do(sess)


async def verify_chain(session: AsyncSession | None = None) -> tuple[bool, list[str]]:
    """Walk the entire audit ledger and verify the hash chain.

    Returns (ok, errors).  If ok is True the chain is intact.
    """
    errors: list[str] = []

    async def _do(sess: AsyncSession) -> tuple[bool, list[str]]:
        result = await sess.execute(
            select(AuditEntry).order_by(AuditEntry.id.asc())
        )
        entries = result.scalars().all()

        if not entries:
            return True, []

        prev_hash: str | None = None
        for entry in entries:
            # 1. Verify prev_hash chain link
            if entry.prev_hash != prev_hash:
                errors.append(
                    f"Entry #{entry.id}: prev_hash mismatch. "
                    f"Expected {prev_hash}, got {entry.prev_hash}"
                )

            # 2. Recompute hash from stored data (same fields as append_audit)
            entry_data = {
                "correlation_id": str(entry.correlation_id),
                "run_id": str(entry.run_id) if entry.run_id else None,
                "step_id": str(entry.step_id) if entry.step_id else None,
                "actor": entry.actor,
                "action": entry.action,
                "detail": entry.detail or {},
                "policy_decision": entry.policy_decision,
                "approval_chain": entry.approval_chain or [],
                "tool": entry.tool,
                "adapter_mode": entry.adapter_mode,
                "model": entry.model,
            }
            expected_hash = _compute_hash(entry.prev_hash, entry_data)

            if entry.entry_hash != expected_hash:
                errors.append(
                    f"Entry #{entry.id}: entry_hash mismatch. "
                    f"Expected {expected_hash[:16]}..., got {entry.entry_hash[:16]}..."
                )

            prev_hash = entry.entry_hash

        return len(errors) == 0, errors

    if session:
        return await _do(session)
    else:
        async with get_session() as sess:
            return await _do(sess)


async def get_audit_for_run(
    run_id: str | UUID, session: AsyncSession | None = None
) -> list[AuditEntry]:
    """Retrieve all audit entries for a given run."""

    async def _do(sess: AsyncSession) -> list[AuditEntry]:
        rid = run_id if isinstance(run_id, UUID) else UUID(str(run_id))
        result = await sess.execute(
            select(AuditEntry)
            .where(AuditEntry.run_id == rid)
            .order_by(AuditEntry.id.asc())
        )
        return list(result.scalars().all())

    if session:
        return await _do(session)
    else:
        async with get_session() as sess:
            return await _do(sess)


async def get_audit_by_correlation(
    correlation_id: str | UUID, session: AsyncSession | None = None
) -> list[AuditEntry]:
    """Retrieve all audit entries for a correlation ID."""

    async def _do(sess: AsyncSession) -> list[AuditEntry]:
        cid = correlation_id if isinstance(correlation_id, UUID) else UUID(str(correlation_id))
        result = await sess.execute(
            select(AuditEntry)
            .where(AuditEntry.correlation_id == cid)
            .order_by(AuditEntry.id.asc())
        )
        return list(result.scalars().all())

    if session:
        return await _do(session)
    else:
        async with get_session() as sess:
            return await _do(sess)
