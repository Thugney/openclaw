"""Workflow models – submission, run state, and step tracking."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from msclaw_shared.models.common import CorrelationId, IdempotencyKey, utcnow


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowSubmission(BaseModel):
    """What the operator submits to start a workflow."""

    workflow_name: str = Field(..., description="Registered workflow name")
    inputs: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: IdempotencyKey
    submitted_by: str = Field(..., description="Username or service principal")
    tags: dict[str, str] = Field(default_factory=dict)


class WorkflowStep(BaseModel):
    """Single step within a workflow run."""

    step_id: str
    name: str
    status: StepStatus = StepStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    tool_intent_id: str | None = None
    approval_id: str | None = None


class WorkflowRun(BaseModel):
    """Full state of a workflow execution."""

    run_id: str = Field(..., description="ULID for this run")
    correlation_id: CorrelationId
    workflow_name: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    idempotency_key: IdempotencyKey
    submitted_by: str
    submitted_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    steps: list[WorkflowStep] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
