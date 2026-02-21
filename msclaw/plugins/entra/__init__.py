"""Entra ID Plugin.

Provides actions for Microsoft Entra ID (Azure AD):
- revoke_signin_sessions(userId) - approval-gated
- disable_user(userId) - approval-gated

These are high-impact identity actions and always require approval.
Uses app-only auth where possible.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from ...shared.auth import MSGraphClient
from ...shared.contracts import (
    AuthType,
    CorrelationContext,
    IdempotencyStrategy,
    RollbackStrategy,
    ToolExecutionStatus,
    ToolResult,
)
from ...shared.plugin_sdk import ActionDefinition, ActionPermission, PluginBase

logger = logging.getLogger("msclaw.plugins.entra")


class EntraPlugin(PluginBase):
    """Microsoft Entra ID plugin."""

    def __init__(self, graph_client: MSGraphClient | None = None):
        self._client = graph_client

    @property
    def name(self) -> str:
        return "entra"

    @property
    def description(self) -> str:
        return "Microsoft Entra ID identity operations"

    @property
    def version(self) -> str:
        return "1.0.0"

    def actions(self) -> dict[str, ActionDefinition]:
        return {
            "revoke_signin_sessions": ActionDefinition(
                name="revoke_signin_sessions",
                description="Revoke all sign-in sessions for a user (forces re-authentication)",
                input_schema={
                    "type": "object",
                    "required": ["user_id"],
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "Entra user ID or UPN",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Reason for session revocation",
                        },
                    },
                },
                required_permissions=[
                    ActionPermission(
                        permission="User.ReadWrite.All",
                        type=AuthType.APP_ONLY,
                        description="Revoke user sign-in sessions",
                    ),
                ],
                idempotency_strategy=IdempotencyStrategy.SAFE_TO_RETRY,
                rollback_strategy=RollbackStrategy.NONE,  # Cannot un-revoke sessions
                audit_fields=["user_id", "reason"],
                requires_approval=True,
                approval_reason_template="Revoking sign-in sessions for user {user_id}",
            ),
            "disable_user": ActionDefinition(
                name="disable_user",
                description="Disable a user account in Entra ID",
                input_schema={
                    "type": "object",
                    "required": ["user_id"],
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "Entra user ID or UPN",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Reason for disabling the account",
                        },
                    },
                },
                required_permissions=[
                    ActionPermission(
                        permission="User.ReadWrite.All",
                        type=AuthType.APP_ONLY,
                        description="Disable user account",
                    ),
                ],
                idempotency_strategy=IdempotencyStrategy.CHECK_AND_APPLY,
                rollback_action="enable_user",
                rollback_strategy=RollbackStrategy.REVERSE_ACTION,
                audit_fields=["user_id", "reason"],
                requires_approval=True,
                approval_reason_template="Disabling user account {user_id}",
            ),
            "enable_user": ActionDefinition(
                name="enable_user",
                description="Re-enable a disabled user account in Entra ID",
                input_schema={
                    "type": "object",
                    "required": ["user_id"],
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "Entra user ID or UPN",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Reason for re-enabling the account",
                        },
                    },
                },
                required_permissions=[
                    ActionPermission(
                        permission="User.ReadWrite.All",
                        type=AuthType.APP_ONLY,
                        description="Enable user account",
                    ),
                ],
                idempotency_strategy=IdempotencyStrategy.CHECK_AND_APPLY,
                rollback_strategy=RollbackStrategy.NONE,
                audit_fields=["user_id", "reason"],
                requires_approval=True,
                approval_reason_template="Re-enabling user account {user_id}",
            ),
        }

    async def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        correlation: CorrelationContext,
        *,
        dev_mode: bool = False,
    ) -> ToolResult:
        handlers = {
            "revoke_signin_sessions": self._revoke_signin_sessions,
            "disable_user": self._disable_user,
            "enable_user": self._enable_user,
        }

        handler = handlers.get(action)
        if not handler:
            return ToolResult(
                intent_id=str(uuid.uuid4()),
                plugin=self.name,
                action=action,
                status=ToolExecutionStatus.FAILED,
                error=f"Unknown action: {action}",
                correlation=correlation,
            )

        return await handler(parameters, correlation, dev_mode=dev_mode)

    async def _revoke_signin_sessions(
        self, params: dict[str, Any], correlation: CorrelationContext, *, dev_mode: bool = False,
    ) -> ToolResult:
        user_id = params["user_id"]
        reason = params.get("reason", "Session revocation by MSClaw")

        if dev_mode or not self._client:
            logger.info("[DEV] Revoking sign-in sessions for user %s", user_id)
            result = {"revoked": True, "user_id": user_id, "reason": reason}
        else:
            # POST /users/{id}/revokeSignInSessions
            api_result = await self._client.graph_post(
                f"/users/{user_id}/revokeSignInSessions",
                {},
            )
            result = {"revoked": api_result.get("value", True), "user_id": user_id, "reason": reason}

        return ToolResult(
            intent_id=str(uuid.uuid4()),
            plugin=self.name,
            action="revoke_signin_sessions",
            status=ToolExecutionStatus.COMPLETED,
            result=result,
            correlation=correlation,
        )

    async def _disable_user(
        self, params: dict[str, Any], correlation: CorrelationContext, *, dev_mode: bool = False,
    ) -> ToolResult:
        user_id = params["user_id"]
        reason = params.get("reason", "Account disabled by MSClaw")

        if dev_mode or not self._client:
            logger.info("[DEV] Disabling user %s", user_id)
            result = {"disabled": True, "user_id": user_id, "reason": reason, "account_enabled": False}
        else:
            # Check current state (idempotent)
            user = await self._client.graph_get(f"/users/{user_id}?$select=accountEnabled")
            if not user.get("accountEnabled", True):
                return ToolResult(
                    intent_id=str(uuid.uuid4()),
                    plugin=self.name,
                    action="disable_user",
                    status=ToolExecutionStatus.COMPLETED,
                    result={"disabled": True, "user_id": user_id, "already_disabled": True},
                    correlation=correlation,
                )

            # PATCH /users/{id}
            await self._client.graph_post(  # Would be PATCH in production
                f"/users/{user_id}",
                {"accountEnabled": False},
            )
            result = {"disabled": True, "user_id": user_id, "reason": reason, "account_enabled": False}

        return ToolResult(
            intent_id=str(uuid.uuid4()),
            plugin=self.name,
            action="disable_user",
            status=ToolExecutionStatus.COMPLETED,
            result=result,
            correlation=correlation,
        )

    async def _enable_user(
        self, params: dict[str, Any], correlation: CorrelationContext, *, dev_mode: bool = False,
    ) -> ToolResult:
        user_id = params["user_id"]
        reason = params.get("reason", "Account re-enabled by MSClaw")

        if dev_mode or not self._client:
            logger.info("[DEV] Enabling user %s", user_id)
            result = {"enabled": True, "user_id": user_id, "reason": reason, "account_enabled": True}
        else:
            await self._client.graph_post(
                f"/users/{user_id}",
                {"accountEnabled": True},
            )
            result = {"enabled": True, "user_id": user_id, "reason": reason, "account_enabled": True}

        return ToolResult(
            intent_id=str(uuid.uuid4()),
            plugin=self.name,
            action="enable_user",
            status=ToolExecutionStatus.COMPLETED,
            result=result,
            correlation=correlation,
        )
