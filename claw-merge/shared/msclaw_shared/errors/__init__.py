"""Typed errors for MSClaw – no silent failures."""

from __future__ import annotations


class MSClawError(Exception):
    """Base error for all MSClaw errors."""

    def __init__(self, message: str, *, code: str = "INTERNAL_ERROR", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class PolicyDeniedError(MSClawError):
    """Raised when a policy evaluation denies a tool intent."""

    def __init__(self, message: str, *, rule: str, reason: str = ""):
        super().__init__(message, code="POLICY_DENIED", details={"rule": rule, "reason": reason})
        self.rule = rule
        self.reason = reason


class ApprovalRequiredError(MSClawError):
    """Raised when a tool intent requires human approval."""

    def __init__(self, message: str, *, approval_id: str, required_approvers: list[str]):
        super().__init__(
            message,
            code="APPROVAL_REQUIRED",
            details={"approval_id": approval_id, "required_approvers": required_approvers},
        )
        self.approval_id = approval_id
        self.required_approvers = required_approvers


class IdempotentSkipError(MSClawError):
    """Raised when an action was already executed with same idempotency key."""

    def __init__(self, message: str, *, idempotency_key: str, original_result: dict | None = None):
        super().__init__(
            message,
            code="IDEMPOTENT_SKIP",
            details={"idempotency_key": idempotency_key},
        )
        self.idempotency_key = idempotency_key
        self.original_result = original_result or {}


class PluginError(MSClawError):
    """Raised by plugins when an action fails."""

    def __init__(self, message: str, *, plugin: str, action: str, upstream_error: str = ""):
        super().__init__(
            message,
            code="PLUGIN_ERROR",
            details={"plugin": plugin, "action": action, "upstream_error": upstream_error},
        )


class ToolNotAllowedError(MSClawError):
    """Raised when a tool is not on the allowlist."""

    def __init__(self, plugin: str, action: str):
        super().__init__(
            f"Tool {plugin}.{action} is not on the allowlist",
            code="TOOL_NOT_ALLOWED",
            details={"plugin": plugin, "action": action},
        )


class AuthenticationError(MSClawError):
    """Raised for auth failures."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, code="AUTHENTICATION_ERROR")


class AuthorizationError(MSClawError):
    """Raised when user lacks required role."""

    def __init__(self, message: str = "Insufficient permissions", *, required_role: str = ""):
        super().__init__(message, code="AUTHORIZATION_ERROR", details={"required_role": required_role})


class WorkflowError(MSClawError):
    """Raised for workflow execution errors."""

    def __init__(self, message: str, *, workflow_name: str, run_id: str = ""):
        super().__init__(
            message,
            code="WORKFLOW_ERROR",
            details={"workflow_name": workflow_name, "run_id": run_id},
        )


class ModelRouterError(MSClawError):
    """Raised when model routing fails."""

    def __init__(self, message: str, *, provider: str = ""):
        super().__init__(message, code="MODEL_ROUTER_ERROR", details={"provider": provider})
