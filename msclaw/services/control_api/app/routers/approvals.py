"""Approval queue endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ApprovalDecisionRequest(BaseModel):
    decision: str  # "approved" or "denied"
    decided_by: str
    note: str | None = None


class ApprovalResponse(BaseModel):
    approval_id: str
    workflow_run_id: str
    step_index: int
    plugin: str
    action: str
    reason: str
    parameters: dict[str, Any]
    status: str
    requested_at: str
    decided_at: str | None = None
    decided_by: str | None = None
    decision_note: str | None = None


# ---------------------------------------------------------------------------
# In-memory store (replaced by Postgres in production)
# ---------------------------------------------------------------------------

_approval_queue: dict[str, dict[str, Any]] = {}


def add_approval_request(approval: dict[str, Any]) -> None:
    """Called by orchestrator (via NATS) to add an approval request."""
    _approval_queue[approval["approval_id"]] = approval


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[ApprovalResponse])
async def list_pending_approvals(status: str = "pending") -> list[ApprovalResponse]:
    """List approval requests, filtered by status."""
    approvals = [
        a for a in _approval_queue.values()
        if a.get("status", "pending") == status
    ]
    approvals.sort(key=lambda a: a.get("requested_at", ""), reverse=True)
    return [_to_response(a) for a in approvals]


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(approval_id: str) -> ApprovalResponse:
    """Get a specific approval request."""
    approval = _approval_queue.get(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail=f"Approval {approval_id} not found")
    return _to_response(approval)


@router.post("/{approval_id}/decide", response_model=ApprovalResponse)
async def decide_approval(approval_id: str, request: ApprovalDecisionRequest) -> ApprovalResponse:
    """Approve or deny an approval request."""
    approval = _approval_queue.get(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail=f"Approval {approval_id} not found")

    if approval.get("status") != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Approval already decided: {approval.get('status')}",
        )

    if request.decision not in ("approved", "denied"):
        raise HTTPException(status_code=400, detail="Decision must be 'approved' or 'denied'")

    approval["status"] = request.decision
    approval["decided_by"] = request.decided_by
    approval["decided_at"] = datetime.utcnow().isoformat()
    approval["decision_note"] = request.note

    # TODO: Publish decision to NATS topic "approval.decided"
    # await nats_publish("approval.decided", approval)

    return _to_response(approval)


def _to_response(a: dict[str, Any]) -> ApprovalResponse:
    return ApprovalResponse(
        approval_id=a["approval_id"],
        workflow_run_id=a.get("workflow_run_id", ""),
        step_index=a.get("step_index", 0),
        plugin=a.get("plugin", ""),
        action=a.get("action", ""),
        reason=a.get("reason", ""),
        parameters=a.get("parameters", {}),
        status=a.get("status", "pending"),
        requested_at=a.get("requested_at", ""),
        decided_at=a.get("decided_at"),
        decided_by=a.get("decided_by"),
        decision_note=a.get("decision_note"),
    )
