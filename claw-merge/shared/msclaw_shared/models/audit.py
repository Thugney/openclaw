"""Audit ledger models – append-only with hash chain for tamper evidence."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from msclaw_shared.models.common import CorrelationId, utcnow


class AuditDecision(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    APPROVAL_REQUIRED = "approval_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    ERROR = "error"


class AuditEntry(BaseModel):
    """Single append-only audit record.

    Fields capture who/what/when/inputs/outputs/model/tool/
    policy-decision/approval-chain/correlation-id as required.
    """

    id: str = Field(..., description="ULID for this audit entry")
    correlation_id: CorrelationId
    timestamp: datetime = Field(default_factory=utcnow)

    # Who
    actor: str = Field(..., description="User or service principal that initiated the action")
    actor_type: str = Field(default="user", description="'user' | 'service' | 'system'")

    # What
    action: str = Field(..., description="Action name, e.g. 'defender_xdr.isolate_device'")
    service: str = Field(..., description="Service that produced this entry")

    # Inputs / Outputs
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)

    # Model (if LLM involved)
    model_id: str | None = Field(default=None, description="Model used, if any")
    model_provider: str | None = Field(default=None)

    # Tool
    tool_name: str | None = Field(default=None)
    idempotency_key: str | None = Field(default=None)

    # Policy
    policy_decision: AuditDecision | None = Field(default=None)
    policy_rule: str | None = Field(default=None, description="Rego rule that matched")
    policy_reason: str | None = Field(default=None)

    # Approval chain
    approval_chain: list[ApprovalRecord] = Field(default_factory=list)

    # Hash chain
    previous_hash: str | None = Field(default=None, description="SHA-256 of previous entry")
    entry_hash: str | None = Field(default=None, description="SHA-256 of this entry's content")

    # Metadata
    tags: dict[str, str] = Field(default_factory=dict)
    error: str | None = Field(default=None)


class ApprovalRecord(BaseModel):
    """Record of a single approval decision."""

    approver: str
    decision: AuditDecision
    timestamp: datetime = Field(default_factory=utcnow)
    reason: str | None = None
