"""MSClaw typed error hierarchy.

Every error is typed and carries context. No silent failures."""

from __future__ import annotations


class MSClawError(Exception):
    """Base error for all MSClaw operations."""
    def __init__(self, message: str, correlation_id: str | None = None, details: dict | None = None):
        self.correlation_id = correlation_id
        self.details = details or {}
        super().__init__(message)


class PolicyDeniedError(MSClawError):
    """Raised when OPA policy denies an action."""
    def __init__(self, action: str, reason: str, correlation_id: str | None = None):
        super().__init__(
            f"Policy denied action '{action}': {reason}",
            correlation_id=correlation_id,
            details={"action": action, "reason": reason},
        )


class ApprovalRequiredError(MSClawError):
    """Raised when an action requires operator approval."""
    def __init__(self, action: str, reason: str, approval_id: str, correlation_id: str | None = None):
        super().__init__(
            f"Approval required for '{action}': {reason}",
            correlation_id=correlation_id,
            details={"action": action, "reason": reason, "approval_id": approval_id},
        )


class ApprovalDeniedError(MSClawError):
    """Raised when an operator denies an approval request."""
    def __init__(self, approval_id: str, correlation_id: str | None = None):
        super().__init__(
            f"Approval {approval_id} was denied",
            correlation_id=correlation_id,
            details={"approval_id": approval_id},
        )


class ToolExecutionError(MSClawError):
    """Raised when a tool action fails to execute."""
    def __init__(self, plugin: str, action: str, message: str, correlation_id: str | None = None):
        super().__init__(
            f"Tool execution failed [{plugin}.{action}]: {message}",
            correlation_id=correlation_id,
            details={"plugin": plugin, "action": action},
        )


class IdempotencyConflictError(MSClawError):
    """Raised when an idempotency key has already been used with different parameters."""
    def __init__(self, idempotency_key: str, correlation_id: str | None = None):
        super().__init__(
            f"Idempotency conflict for key '{idempotency_key}'",
            correlation_id=correlation_id,
            details={"idempotency_key": idempotency_key},
        )


class AuthenticationError(MSClawError):
    """Raised when Microsoft Graph / Defender auth fails."""
    def __init__(self, provider: str, message: str, correlation_id: str | None = None):
        super().__init__(
            f"Auth failed for {provider}: {message}",
            correlation_id=correlation_id,
            details={"provider": provider},
        )


class WorkflowError(MSClawError):
    """Raised when a workflow execution encounters an unrecoverable error."""
    def __init__(self, workflow_id: str, step_index: int, message: str, correlation_id: str | None = None):
        super().__init__(
            f"Workflow '{workflow_id}' failed at step {step_index}: {message}",
            correlation_id=correlation_id,
            details={"workflow_id": workflow_id, "step_index": step_index},
        )


class ModelRouterError(MSClawError):
    """Raised when model routing fails (all providers unavailable, budget exceeded, etc.)."""
    def __init__(self, message: str, correlation_id: str | None = None):
        super().__init__(
            f"Model router error: {message}",
            correlation_id=correlation_id,
        )


class ConfigurationError(MSClawError):
    """Raised for invalid configuration."""
    def __init__(self, message: str):
        super().__init__(f"Configuration error: {message}")
