"""Audit trail query endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AuditEntryResponse(BaseModel):
    entry_id: str
    correlation_id: str
    workflow_run_id: str | None
    action: str
    actor: str
    target: str | None
    plugin: str | None
    tool_action: str | None
    inputs: dict[str, Any] | None
    outputs: dict[str, Any] | None
    policy_decision: str | None
    model_used: str | None
    approval_chain: list[str] | None
    error: str | None
    timestamp: str
    entry_hash: str | None


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

_audit_entries: list[dict[str, Any]] = []


def append_audit_entry(entry: dict[str, Any]) -> None:
    """Called by audit-service to store entries."""
    _audit_entries.append(entry)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[AuditEntryResponse])
async def list_audit_entries(
    correlation_id: str | None = None,
    workflow_run_id: str | None = None,
    limit: int = 100,
) -> list[AuditEntryResponse]:
    """Query audit entries by correlation ID or workflow run."""
    entries = _audit_entries

    if correlation_id:
        entries = [e for e in entries if e.get("correlation_id") == correlation_id]
    if workflow_run_id:
        entries = [e for e in entries if e.get("workflow_run_id") == workflow_run_id]

    entries = sorted(entries, key=lambda e: e.get("timestamp", ""), reverse=True)
    return [_to_response(e) for e in entries[:limit]]


@router.get("/{entry_id}", response_model=AuditEntryResponse)
async def get_audit_entry(entry_id: str) -> AuditEntryResponse:
    """Get a specific audit entry."""
    for entry in _audit_entries:
        if entry.get("entry_id") == entry_id:
            return _to_response(entry)
    raise HTTPException(status_code=404, detail=f"Audit entry {entry_id} not found")


@router.get("/chain/{correlation_id}", response_model=list[AuditEntryResponse])
async def get_audit_chain(correlation_id: str) -> list[AuditEntryResponse]:
    """Get the full audit chain for a correlation ID."""
    entries = [e for e in _audit_entries if e.get("correlation_id") == correlation_id]
    entries.sort(key=lambda e: e.get("timestamp", ""))
    return [_to_response(e) for e in entries]


def _to_response(e: dict[str, Any]) -> AuditEntryResponse:
    return AuditEntryResponse(
        entry_id=e.get("entry_id", ""),
        correlation_id=e.get("correlation_id", ""),
        workflow_run_id=e.get("workflow_run_id"),
        action=e.get("action", ""),
        actor=e.get("actor", ""),
        target=e.get("target"),
        plugin=e.get("plugin"),
        tool_action=e.get("tool_action"),
        inputs=e.get("inputs"),
        outputs=e.get("outputs"),
        policy_decision=e.get("policy_decision"),
        model_used=e.get("model_used"),
        approval_chain=e.get("approval_chain"),
        error=e.get("error"),
        timestamp=e.get("timestamp", ""),
        entry_hash=e.get("entry_hash"),
    )
