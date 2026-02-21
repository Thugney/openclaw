"""MSClaw shared type definitions.

Central type registry for all services. Every contract between services
is defined here to enforce strict typing at boundaries.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class WorkflowStatus(str, Enum):
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    DENIED = "denied"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolExecutionStatus(str, Enum):
    PENDING = "pending"
    POLICY_CHECK = "policy_check"
    POLICY_DENIED = "policy_denied"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class ScanType(str, Enum):
    QUICK = "Quick"
    FULL = "Full"


class IdempotencyStrategy(str, Enum):
    """How a plugin action handles duplicate requests."""
    SKIP_IF_DONE = "skip_if_done"          # Check state, skip if already applied
    SAFE_TO_RETRY = "safe_to_retry"        # Action is inherently idempotent
    CHECK_AND_APPLY = "check_and_apply"    # Check precondition, apply if needed


class RollbackStrategy(str, Enum):
    NONE = "none"
    REVERSE_ACTION = "reverse_action"      # e.g. unisolate after isolate
    MANUAL = "manual"                      # Requires human intervention


class AuthType(str, Enum):
    APP_ONLY = "app_only"                  # Client credentials flow
    DELEGATED = "delegated"                # User delegated (interactive)


class ModelProvider(str, Enum):
    LOCAL_OLLAMA = "ollama"
    LOCAL_LLAMACPP = "llamacpp"
    CLOUD_ANTHROPIC = "anthropic"
    CLOUD_OPENAI = "openai"
    CLOUD_AZURE_OPENAI = "azure_openai"


class AuditAction(str, Enum):
    WORKFLOW_SUBMITTED = "workflow.submitted"
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"
    TOOL_INTENT_CREATED = "tool.intent_created"
    TOOL_POLICY_CHECKED = "tool.policy_checked"
    TOOL_POLICY_DENIED = "tool.policy_denied"
    TOOL_APPROVAL_REQUESTED = "tool.approval_requested"
    TOOL_APPROVED = "tool.approved"
    TOOL_DENIED = "tool.denied"
    TOOL_EXECUTED = "tool.executed"
    TOOL_FAILED = "tool.failed"
    TOOL_ROLLED_BACK = "tool.rolled_back"
    MODEL_INVOKED = "model.invoked"
    MODEL_RESPONSE = "model.response"


# ---------------------------------------------------------------------------
# Core Models
# ---------------------------------------------------------------------------

class CorrelationContext(BaseModel):
    """Threaded through every request for full traceability."""
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_run_id: str | None = None
    step_index: int | None = None
    parent_correlation_id: str | None = None
    operator_id: str | None = None
    source: str = "unknown"


class IdempotencyRecord(BaseModel):
    idempotency_key: str
    action: str
    status: ToolExecutionStatus
    result: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None


# ---------------------------------------------------------------------------
# Tool Intents (Orchestrator -> Tool Runner)
# ---------------------------------------------------------------------------

class ToolIntent(BaseModel):
    """The orchestrator produces intents, not raw commands.
    The tool runner resolves and executes them after policy check."""
    intent_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    plugin: str                          # e.g. "defender_xdr"
    action: str                          # e.g. "isolate_device"
    parameters: dict[str, Any]           # Action-specific input
    idempotency_key: str
    correlation: CorrelationContext
    requires_approval: bool = False
    approval_reason: str | None = None


class ToolResult(BaseModel):
    intent_id: str
    plugin: str
    action: str
    status: ToolExecutionStatus
    result: dict[str, Any] | None = None
    error: str | None = None
    correlation: CorrelationContext
    executed_at: datetime = Field(default_factory=datetime.utcnow)
    duration_ms: int | None = None


# ---------------------------------------------------------------------------
# Workflow Models
# ---------------------------------------------------------------------------

class WorkflowStep(BaseModel):
    step_index: int
    name: str
    plugin: str
    action: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[int] = Field(default_factory=list)
    condition: str | None = None         # Optional expression to evaluate


class WorkflowDefinition(BaseModel):
    workflow_id: str
    name: str
    description: str
    version: str = "1.0.0"
    steps: list[WorkflowStep]
    input_schema: dict[str, Any]         # JSON Schema for workflow inputs


class WorkflowRun(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    inputs: dict[str, Any]
    correlation: CorrelationContext
    idempotency_key: str
    steps_completed: list[int] = Field(default_factory=list)
    step_results: dict[int, ToolResult] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Approval Models
# ---------------------------------------------------------------------------

class ApprovalRequest(BaseModel):
    approval_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_run_id: str
    step_index: int
    intent: ToolIntent
    reason: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    decided_at: datetime | None = None
    decided_by: str | None = None
    decision_note: str | None = None


# ---------------------------------------------------------------------------
# Audit Models
# ---------------------------------------------------------------------------

class AuditEntry(BaseModel):
    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str
    workflow_run_id: str | None = None
    action: AuditAction
    actor: str                           # operator ID or "system"
    target: str | None = None            # e.g. device ID, user ID
    plugin: str | None = None
    tool_action: str | None = None
    inputs: dict[str, Any] | None = None
    outputs: dict[str, Any] | None = None
    policy_decision: str | None = None   # "allow" | "deny" | "require_approval"
    model_used: str | None = None
    approval_chain: list[str] | None = None
    error: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    prev_hash: str | None = None         # Hash chain for tamper evidence
    entry_hash: str | None = None


# ---------------------------------------------------------------------------
# Model Router Models
# ---------------------------------------------------------------------------

class ModelRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    prompt: str
    system_prompt: str | None = None
    correlation: CorrelationContext
    preferred_provider: ModelProvider | None = None
    max_tokens: int = 4096
    temperature: float = 0.1
    contains_pii: bool = False           # If True, block cloud unless approved


class ModelResponse(BaseModel):
    request_id: str
    provider: ModelProvider
    model: str
    content: str
    usage: dict[str, int] | None = None
    duration_ms: int | None = None
    correlation: CorrelationContext


# ---------------------------------------------------------------------------
# Policy Models
# ---------------------------------------------------------------------------

class PolicyInput(BaseModel):
    """Input to OPA policy evaluation."""
    operator: dict[str, Any]             # {id, roles, groups}
    action: str                          # plugin.action
    plugin: str
    parameters: dict[str, Any]
    device_tags: list[str] | None = None
    user_tags: list[str] | None = None
    contains_pii: bool = False


class PolicyDecision(BaseModel):
    allowed: bool
    require_approval: bool = False
    approval_reason: str | None = None
    deny_reason: str | None = None
    policy_name: str | None = None
    evaluated_at: datetime = Field(default_factory=datetime.utcnow)
