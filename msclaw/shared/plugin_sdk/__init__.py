"""MSClaw Plugin SDK.

Every plugin implements the PluginBase interface. Each action is declared
with its input schema, required permissions, idempotency strategy,
rollback strategy, and audit fields. The SDK enforces this contract at
registration time.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from ..contracts import (
    AuthType,
    CorrelationContext,
    IdempotencyStrategy,
    RollbackStrategy,
    ToolResult,
)


@dataclass(frozen=True)
class ActionPermission:
    """A Microsoft Graph / Defender permission required by an action."""
    permission: str            # e.g. "DeviceManagementManagedDevices.ReadWrite.All"
    type: AuthType = AuthType.APP_ONLY
    description: str = ""


@dataclass(frozen=True)
class ActionDefinition:
    """Full declaration of a plugin action."""
    name: str
    description: str
    input_schema: dict[str, Any]          # JSON Schema
    required_permissions: list[ActionPermission]
    idempotency_strategy: IdempotencyStrategy
    rollback_action: str | None = None    # Name of the reverse action
    rollback_strategy: RollbackStrategy = RollbackStrategy.NONE
    audit_fields: list[str] = field(default_factory=list)  # Fields to capture in audit
    requires_approval: bool = False
    approval_reason_template: str | None = None


class PluginBase(abc.ABC):
    """Base class for all MSClaw plugins."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Plugin identifier, e.g. 'defender_xdr'."""

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """Human-readable plugin description."""

    @property
    @abc.abstractmethod
    def version(self) -> str:
        """Plugin version string."""

    @abc.abstractmethod
    def actions(self) -> dict[str, ActionDefinition]:
        """Return all action definitions. Called at registration time."""

    @abc.abstractmethod
    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        correlation: CorrelationContext,
        *,
        dev_mode: bool = False,
    ) -> ToolResult:
        """Execute an action. Must be idempotent per the action's strategy.

        Args:
            action: The action name to execute.
            parameters: Action-specific input parameters (validated against schema).
            correlation: Full correlation context for tracing.
            dev_mode: If True, mock Microsoft API calls.

        Returns:
            ToolResult with execution outcome.

        Raises:
            ToolExecutionError: On unrecoverable failure.
        """

    def validate_action(self, action: str, parameters: dict[str, Any]) -> list[str]:
        """Validate parameters against the action's input schema.

        Returns a list of validation error messages (empty if valid).
        """
        action_def = self.actions().get(action)
        if action_def is None:
            return [f"Unknown action: {action}"]

        # Basic required-field validation (jsonschema can be added for full validation)
        errors: list[str] = []
        schema = action_def.input_schema
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        for req_field in required:
            if req_field not in parameters:
                errors.append(f"Missing required field: {req_field}")

        for param_name, param_value in parameters.items():
            if param_name not in properties:
                errors.append(f"Unknown parameter: {param_name}")

        return errors

    def get_all_permissions(self) -> list[ActionPermission]:
        """Return all unique permissions required by this plugin."""
        seen: set[str] = set()
        permissions: list[ActionPermission] = []
        for action_def in self.actions().values():
            for perm in action_def.required_permissions:
                if perm.permission not in seen:
                    seen.add(perm.permission)
                    permissions.append(perm)
        return permissions
