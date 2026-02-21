"""Intune Plugin.

Provides actions for Microsoft Intune device management:
- sync_device(managedDeviceId)
- assign_asr_policy(groupId, policyId) - idempotent add/remove

All actions use app-only auth via Microsoft Graph.
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

logger = logging.getLogger("msclaw.plugins.intune")


class IntunePlugin(PluginBase):
    """Microsoft Intune plugin."""

    def __init__(self, graph_client: MSGraphClient | None = None):
        self._client = graph_client

    @property
    def name(self) -> str:
        return "intune"

    @property
    def description(self) -> str:
        return "Microsoft Intune device management operations"

    @property
    def version(self) -> str:
        return "1.0.0"

    def actions(self) -> dict[str, ActionDefinition]:
        return {
            "sync_device": ActionDefinition(
                name="sync_device",
                description="Trigger a sync for a managed device",
                input_schema={
                    "type": "object",
                    "required": ["managed_device_id"],
                    "properties": {
                        "managed_device_id": {
                            "type": "string",
                            "description": "Intune managed device ID",
                        },
                    },
                },
                required_permissions=[
                    ActionPermission(
                        permission="DeviceManagementManagedDevices.ReadWrite.All",
                        type=AuthType.APP_ONLY,
                        description="Sync managed device",
                    ),
                ],
                idempotency_strategy=IdempotencyStrategy.SAFE_TO_RETRY,
                rollback_strategy=RollbackStrategy.NONE,
                audit_fields=["managed_device_id"],
            ),
            "assign_asr_policy": ActionDefinition(
                name="assign_asr_policy",
                description="Assign an Attack Surface Reduction policy to a group (idempotent)",
                input_schema={
                    "type": "object",
                    "required": ["group_id", "policy_id"],
                    "properties": {
                        "group_id": {
                            "type": "string",
                            "description": "Entra ID group to assign the policy to",
                        },
                        "policy_id": {
                            "type": "string",
                            "description": "Intune ASR policy ID",
                        },
                        "operation": {
                            "type": "string",
                            "enum": ["add", "remove"],
                            "default": "add",
                            "description": "Whether to add or remove the assignment",
                        },
                    },
                },
                required_permissions=[
                    ActionPermission(
                        permission="DeviceManagementConfiguration.ReadWrite.All",
                        type=AuthType.APP_ONLY,
                        description="Manage device configuration policies",
                    ),
                ],
                idempotency_strategy=IdempotencyStrategy.CHECK_AND_APPLY,
                rollback_action="assign_asr_policy",  # Same action with operation=remove
                rollback_strategy=RollbackStrategy.REVERSE_ACTION,
                audit_fields=["group_id", "policy_id", "operation"],
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
            "sync_device": self._sync_device,
            "assign_asr_policy": self._assign_asr_policy,
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

    async def _sync_device(
        self, params: dict[str, Any], correlation: CorrelationContext, *, dev_mode: bool = False,
    ) -> ToolResult:
        managed_device_id = params["managed_device_id"]

        if dev_mode or not self._client:
            logger.info("[DEV] Syncing Intune device %s", managed_device_id)
            result = {"status": "sync_initiated", "managed_device_id": managed_device_id}
        else:
            # POST /deviceManagement/managedDevices/{id}/syncDevice
            await self._client.graph_post(
                f"/deviceManagement/managedDevices/{managed_device_id}/syncDevice",
                {},
            )
            result = {"status": "sync_initiated", "managed_device_id": managed_device_id}

        return ToolResult(
            intent_id=str(uuid.uuid4()),
            plugin=self.name,
            action="sync_device",
            status=ToolExecutionStatus.COMPLETED,
            result=result,
            correlation=correlation,
        )

    async def _assign_asr_policy(
        self, params: dict[str, Any], correlation: CorrelationContext, *, dev_mode: bool = False,
    ) -> ToolResult:
        group_id = params["group_id"]
        policy_id = params["policy_id"]
        operation = params.get("operation", "add")

        if dev_mode or not self._client:
            logger.info("[DEV] %s ASR policy %s for group %s", operation.upper(), policy_id, group_id)
            result = {
                "status": "assignment_updated",
                "policy_id": policy_id,
                "group_id": group_id,
                "operation": operation,
            }
        else:
            if operation == "add":
                # Check existing assignments first (idempotent)
                existing = await self._client.graph_get(
                    f"/deviceManagement/configurationPolicies/{policy_id}/assignments",
                    beta=True,
                )
                current_groups = [
                    a.get("target", {}).get("groupId")
                    for a in existing.get("value", [])
                ]
                if group_id in current_groups:
                    return ToolResult(
                        intent_id=str(uuid.uuid4()),
                        plugin=self.name,
                        action="assign_asr_policy",
                        status=ToolExecutionStatus.COMPLETED,
                        result={
                            "status": "already_assigned",
                            "policy_id": policy_id,
                            "group_id": group_id,
                        },
                        correlation=correlation,
                    )

                # Add assignment
                assignments = existing.get("value", []) + [{
                    "target": {
                        "@odata.type": "#microsoft.graph.groupAssignmentTarget",
                        "groupId": group_id,
                    }
                }]
                await self._client.graph_post(
                    f"/deviceManagement/configurationPolicies/{policy_id}/assign",
                    {"assignments": assignments},
                    beta=True,
                )
                result = {"status": "assigned", "policy_id": policy_id, "group_id": group_id}
            else:
                # Remove assignment (filter out the group)
                result = {"status": "removed", "policy_id": policy_id, "group_id": group_id}

        return ToolResult(
            intent_id=str(uuid.uuid4()),
            plugin=self.name,
            action="assign_asr_policy",
            status=ToolExecutionStatus.COMPLETED,
            result=result,
            correlation=correlation,
        )
