"""Tool intent and result models.

The LLM proposes ToolIntents; the policy gate decides; the tool runner executes.
This separation treats the LLM as untrusted.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from msclaw_shared.models.common import CorrelationId, IdempotencyKey, utcnow


class ToolResultStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    APPROVAL_PENDING = "approval_pending"
    IDEMPOTENT_SKIP = "idempotent_skip"


class ToolIntent(BaseModel):
    """An intent to execute a tool, proposed by orchestrator/LLM.

    This is NOT execution — it must pass through the policy gate first.
    """

    intent_id: str = Field(..., description="ULID for this intent")
    correlation_id: CorrelationId
    workflow_run_id: str | None = None
    step_id: str | None = None

    plugin: str = Field(..., description="Plugin name, e.g. 'defender_xdr'")
    action: str = Field(..., description="Action name, e.g. 'isolate_device'")
    inputs: dict[str, Any] = Field(default_factory=dict)

    idempotency_key: IdempotencyKey
    requested_by: str = Field(..., description="Actor requesting the action")
    requested_at: datetime = Field(default_factory=utcnow)

    # Context for policy evaluation
    device_tags: list[str] = Field(default_factory=list)
    risk_level: str | None = None


class ToolResult(BaseModel):
    """Result from executing a tool intent."""

    intent_id: str
    correlation_id: CorrelationId
    status: ToolResultStatus
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    executed_at: datetime = Field(default_factory=utcnow)
    duration_ms: int | None = None
    artifacts: list[str] = Field(
        default_factory=list,
        description="Object storage keys for produced artifacts",
    )
