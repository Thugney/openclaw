"""Intune plugin – device sync and ASR policy assignment.

Uses Microsoft Graph API (app-only auth).
API base: https://graph.microsoft.com/v1.0
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

logger = logging.getLogger("msclaw.plugins.intune")

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


class IntunePlugin(PluginBase):
    def __init__(self, dev_mode: bool = True):
        self._dev_mode = dev_mode

    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="intune",
            version="0.1.0",
            description="Microsoft Intune device management operations",
            actions=[
                ActionDefinition(
                    name="sync_device",
                    description="Trigger Intune device sync (check-in)",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "managedDeviceId": {"type": "string", "description": "Intune managed device ID"},
                        },
                        "required": ["managedDeviceId"],
                    },
                    required_permissions=["DeviceManagementManagedDevices.ReadWrite.All"],
                    idempotency_strategy=IdempotencyStrategy.SAFE_TO_RETRY,
                    audit_fields=["managedDeviceId"],
                ),
                ActionDefinition(
                    name="assign_asr_policy",
                    description="Assign an ASR (Attack Surface Reduction) policy to a group. Idempotent: adding an already-assigned group is a no-op.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "groupId": {"type": "string", "description": "Entra ID group to assign to"},
                            "policyId": {"type": "string", "description": "Intune configuration policy ID"},
                        },
                        "required": ["groupId", "policyId"],
                    },
                    required_permissions=["DeviceManagementConfiguration.ReadWrite.All"],
                    idempotency_strategy=IdempotencyStrategy.CHECK_AND_SKIP,
                    audit_fields=["groupId", "policyId"],
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
        logger.info("DEV MODE: intune.%s inputs=%s", action, inputs)

        if action == "sync_device":
            return {
                "status": "succeeded",
                "managedDeviceId": inputs["managedDeviceId"],
                "_dev_mock": True,
            }
        elif action == "assign_asr_policy":
            return {
                "status": "succeeded",
                "groupId": inputs["groupId"],
                "policyId": inputs["policyId"],
                "assignment": "created",
                "_dev_mock": True,
            }
        else:
            raise PluginError(f"Unknown action: {action}", plugin="intune", action=action)

    async def _execute_real(
        self, action: str, inputs: dict[str, Any], context: PluginContext
    ) -> dict[str, Any]:
        if not context.access_token:
            raise PluginError("No access token provided", plugin="intune", action=action)

        headers = {
            "Authorization": f"Bearer {context.access_token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            if action == "sync_device":
                resp = await client.post(
                    f"{GRAPH_API_BASE}/deviceManagement/managedDevices/{inputs['managedDeviceId']}/syncDevice",
                    headers=headers,
                )
                if resp.status_code == 204:
                    return {"status": "succeeded", "managedDeviceId": inputs["managedDeviceId"]}

            elif action == "assign_asr_policy":
                # Check existing assignments first (idempotent)
                resp = await client.get(
                    f"{GRAPH_API_BASE}/deviceManagement/configurationPolicies/{inputs['policyId']}/assignments",
                    headers=headers,
                )
                resp.raise_for_status()
                existing = resp.json().get("value", [])
                already_assigned = any(
                    a.get("target", {}).get("groupId") == inputs["groupId"]
                    for a in existing
                )
                if already_assigned:
                    return {
                        "status": "already_assigned",
                        "groupId": inputs["groupId"],
                        "policyId": inputs["policyId"],
                    }

                # Add new assignment
                new_assignments = existing + [{
                    "target": {
                        "@odata.type": "#microsoft.graph.groupAssignmentTarget",
                        "groupId": inputs["groupId"],
                    }
                }]
                resp = await client.post(
                    f"{GRAPH_API_BASE}/deviceManagement/configurationPolicies/{inputs['policyId']}/assign",
                    headers=headers,
                    json={"assignments": new_assignments},
                )
                resp.raise_for_status()
                return {
                    "status": "succeeded",
                    "groupId": inputs["groupId"],
                    "policyId": inputs["policyId"],
                    "assignment": "created",
                }

            else:
                raise PluginError(f"Unknown action: {action}", plugin="intune", action=action)

            if resp.status_code >= 400:
                raise PluginError(
                    f"API error {resp.status_code}: {resp.text}",
                    plugin="intune",
                    action=action,
                    upstream_error=resp.text,
                )
            return resp.json()
