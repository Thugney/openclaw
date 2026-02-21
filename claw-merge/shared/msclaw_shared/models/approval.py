"""Approval models for policy-gated actions."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from msclaw_shared.models.common import CorrelationId, utcnow


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ApprovalRequest(BaseModel):
    """Request for human approval before executing a tool intent."""

    approval_id: str = Field(..., description="ULID for this request")
    correlation_id: CorrelationId
    workflow_run_id: str | None = None
    step_id: str | None = None
    intent_id: str

    plugin: str
    action: str
    inputs: dict[str, Any] = Field(default_factory=dict)

    requested_by: str
    requested_at: datetime = Field(default_factory=utcnow)

    status: ApprovalStatus = ApprovalStatus.PENDING
    required_approvers: list[str] = Field(default_factory=list)
    policy_reason: str = Field(default="")

    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None
