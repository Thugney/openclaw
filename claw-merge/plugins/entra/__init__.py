"""Entra ID plugin – user session revocation and account disable.

Uses Microsoft Graph API (app-only auth).
Both actions are approval-gated by policy.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from plugins.sdk import (
    ActionDefinition,
    IdempotencyStrategy,
    PluginBase,
    PluginContext,
    PluginMetadata,
)
from msclaw_shared.errors import PluginError

logger = logging.getLogger("msclaw.plugins.entra")

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


class EntraPlugin(PluginBase):
    def __init__(self, dev_mode: bool = True):
        self._dev_mode = dev_mode

    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="entra",
            version="0.1.0",
            description="Entra ID identity operations (approval-gated)",
            actions=[
                ActionDefinition(
                    name="revoke_signin_sessions",
                    description="Revoke all sign-in sessions for a user (forces re-auth). Approval-gated.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "userId": {"type": "string", "description": "Entra user ID or UPN"},
                        },
                        "required": ["userId"],
                    },
                    required_permissions=["User.ReadWrite.All"],
                    idempotency_strategy=IdempotencyStrategy.SAFE_TO_RETRY,
                    requires_approval=True,
                    audit_fields=["userId"],
                ),
                ActionDefinition(
                    name="disable_user",
                    description="Disable a user account in Entra ID. Approval-gated.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "userId": {"type": "string", "description": "Entra user ID or UPN"},
                        },
                        "required": ["userId"],
                    },
                    required_permissions=["User.ReadWrite.All"],
                    idempotency_strategy=IdempotencyStrategy.CHECK_AND_SKIP,
                    requires_approval=True,
                    rollback_action="enable_user",
                    audit_fields=["userId"],
                ),
            ],
        )

    async def execute(
        self, action: str, inputs: dict[str, Any], context: PluginContext
    ) -> dict[str, Any]:
        if context.dev_mode:
            return await self._execute_dev(action, inputs, context)
        return await self._execute_real(action, inputs, context)

    async def _execute_dev(
        self, action: str, inputs: dict[str, Any], context: PluginContext
    ) -> dict[str, Any]:
        logger.info("DEV MODE: entra.%s inputs=%s", action, inputs)

        if action == "revoke_signin_sessions":
            return {
                "status": "succeeded",
                "userId": inputs["userId"],
                "sessionsRevoked": True,
                "_dev_mock": True,
            }
        elif action == "disable_user":
            return {
                "status": "succeeded",
                "userId": inputs["userId"],
                "accountEnabled": False,
                "_dev_mock": True,
            }
        else:
            raise PluginError(f"Unknown action: {action}", plugin="entra", action=action)

    async def _execute_real(
        self, action: str, inputs: dict[str, Any], context: PluginContext
    ) -> dict[str, Any]:
        if not context.access_token:
            raise PluginError("No access token provided", plugin="entra", action=action)

        headers = {
            "Authorization": f"Bearer {context.access_token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            if action == "revoke_signin_sessions":
                resp = await client.post(
                    f"{GRAPH_API_BASE}/users/{inputs['userId']}/revokeSignInSessions",
                    headers=headers,
                )
                resp.raise_for_status()
                return {
                    "status": "succeeded",
                    "userId": inputs["userId"],
                    "sessionsRevoked": resp.json().get("value", True),
                }

            elif action == "disable_user":
                # Check current state first (idempotent)
                resp = await client.get(
                    f"{GRAPH_API_BASE}/users/{inputs['userId']}?$select=accountEnabled",
                    headers=headers,
                )
                resp.raise_for_status()
                if not resp.json().get("accountEnabled", True):
                    return {
                        "status": "already_disabled",
                        "userId": inputs["userId"],
                        "accountEnabled": False,
                    }

                resp = await client.patch(
                    f"{GRAPH_API_BASE}/users/{inputs['userId']}",
                    headers=headers,
                    json={"accountEnabled": False},
                )
                resp.raise_for_status()
                return {
                    "status": "succeeded",
                    "userId": inputs["userId"],
                    "accountEnabled": False,
                }

            else:
                raise PluginError(f"Unknown action: {action}", plugin="entra", action=action)
