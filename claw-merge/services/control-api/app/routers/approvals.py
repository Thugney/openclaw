"""Approval queue routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Query, Header
from pydantic import BaseModel

from msclaw_shared.bus import SUBJECTS
from msclaw_shared.models.approval import ApprovalStatus

logger = logging.getLogger("msclaw.control_api.approvals")

router = APIRouter()


class ApprovalDecisionRequest(BaseModel):
    action: str  # "approve" or "reject"
    reason: str = ""


@router.get("")
async def list_pending_approvals(
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """List pending approval requests."""
    db = request.app.state.db
    return await db.list_pending_approvals(offset=offset, limit=limit)


@router.get("/{approval_id}")
async def get_approval(request: Request, approval_id: str):
    db = request.app.state.db
    approval = await db.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return approval


@router.post("/{approval_id}/decide", status_code=200)
async def decide_approval(
    request: Request,
    approval_id: str,
    body: ApprovalDecisionRequest,
    x_actor: str = Header(..., description="Approver username"),
):
    """Approve or reject a pending approval request."""
    db = request.app.state.db
    bus = request.app.state.bus

    approval = await db.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Approval already decided: {approval.status}",
        )

    if body.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")

    new_status = ApprovalStatus.APPROVED if body.action == "approve" else ApprovalStatus.REJECTED
    await db.decide_approval(approval_id, new_status, x_actor, body.reason)

    # Publish decision to orchestrator
    await bus.publish(
        SUBJECTS["approval_decided"],
        {
            "approval_id": approval_id,
            "correlation_id": approval.correlation_id,
            "workflow_run_id": approval.workflow_run_id,
            "step_id": approval.step_id,
            "intent_id": approval.intent_id,
            "status": new_status.value,
            "decided_by": x_actor,
            "reason": body.reason,
        },
    )

    logger.info(
        "Approval %s decided: %s by %s", approval_id, new_status.value, x_actor
    )
    return {"approval_id": approval_id, "status": new_status.value}
