"""Defender XDR Plugin.

Provides actions for Microsoft Defender for Endpoint / Defender XDR:
- isolate_device(deviceId)
- unisolate_device(deviceId)
- collect_investigation_package(deviceId)
- run_antivirus_scan(deviceId, scanType)
- resolve_device_from_incident(incidentId | deviceId)

All actions use app-only auth via Microsoft Graph / Defender APIs.
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

logger = logging.getLogger("msclaw.plugins.defender_xdr")


class DefenderXDRPlugin(PluginBase):
    """Microsoft Defender XDR plugin."""

    def __init__(self, graph_client: MSGraphClient | None = None):
        self._client = graph_client

    @property
    def name(self) -> str:
        return "defender_xdr"

    @property
    def description(self) -> str:
        return "Microsoft Defender for Endpoint / Defender XDR operations"

    @property
    def version(self) -> str:
        return "1.0.0"

    def actions(self) -> dict[str, ActionDefinition]:
        return {
            "isolate_device": ActionDefinition(
                name="isolate_device",
                description="Isolate a device from the network via Defender for Endpoint",
                input_schema={
                    "type": "object",
                    "required": ["device_id"],
                    "properties": {
                        "device_id": {"type": "string", "description": "Defender device ID"},
                        "comment": {"type": "string", "description": "Isolation reason"},
                        "isolation_type": {
                            "type": "string",
                            "enum": ["Full", "Selective"],
                            "default": "Full",
                        },
                    },
                },
                required_permissions=[
                    ActionPermission(
                        permission="Machine.Isolate",
                        type=AuthType.APP_ONLY,
                        description="Isolate machine from network",
                    ),
                ],
                idempotency_strategy=IdempotencyStrategy.CHECK_AND_APPLY,
                rollback_action="unisolate_device",
                rollback_strategy=RollbackStrategy.REVERSE_ACTION,
                audit_fields=["device_id", "isolation_type", "comment"],
            ),
            "unisolate_device": ActionDefinition(
                name="unisolate_device",
                description="Release a device from network isolation",
                input_schema={
                    "type": "object",
                    "required": ["device_id"],
                    "properties": {
                        "device_id": {"type": "string"},
                        "comment": {"type": "string"},
                    },
                },
                required_permissions=[
                    ActionPermission(
                        permission="Machine.Isolate",
                        type=AuthType.APP_ONLY,
                        description="Release machine from isolation",
                    ),
                ],
                idempotency_strategy=IdempotencyStrategy.CHECK_AND_APPLY,
                rollback_action="isolate_device",
                rollback_strategy=RollbackStrategy.REVERSE_ACTION,
                audit_fields=["device_id", "comment"],
            ),
            "collect_investigation_package": ActionDefinition(
                name="collect_investigation_package",
                description="Collect forensic investigation package from a device",
                input_schema={
                    "type": "object",
                    "required": ["device_id"],
                    "properties": {
                        "device_id": {"type": "string"},
                        "comment": {"type": "string"},
                    },
                },
                required_permissions=[
                    ActionPermission(
                        permission="Machine.CollectForensics",
                        type=AuthType.APP_ONLY,
                        description="Collect investigation package",
                    ),
                ],
                idempotency_strategy=IdempotencyStrategy.SAFE_TO_RETRY,
                rollback_strategy=RollbackStrategy.NONE,
                audit_fields=["device_id"],
            ),
            "run_antivirus_scan": ActionDefinition(
                name="run_antivirus_scan",
                description="Run antivirus scan on a device",
                input_schema={
                    "type": "object",
                    "required": ["device_id", "scan_type"],
                    "properties": {
                        "device_id": {"type": "string"},
                        "scan_type": {
                            "type": "string",
                            "enum": ["Quick", "Full"],
                            "description": "Type of AV scan",
                        },
                        "comment": {"type": "string"},
                    },
                },
                required_permissions=[
                    ActionPermission(
                        permission="Machine.Scan",
                        type=AuthType.APP_ONLY,
                        description="Run antivirus scan",
                    ),
                ],
                idempotency_strategy=IdempotencyStrategy.SAFE_TO_RETRY,
                rollback_strategy=RollbackStrategy.NONE,
                audit_fields=["device_id", "scan_type"],
            ),
            "resolve_device_from_incident": ActionDefinition(
                name="resolve_device_from_incident",
                description="Resolve device details from a Defender XDR incident",
                input_schema={
                    "type": "object",
                    "properties": {
                        "incident_id": {"type": "string", "description": "Defender incident ID"},
                        "device_id": {"type": "string", "description": "Direct device ID (skips incident lookup)"},
                    },
                },
                required_permissions=[
                    ActionPermission(
                        permission="Machine.Read.All",
                        type=AuthType.APP_ONLY,
                        description="Read device information",
                    ),
                    ActionPermission(
                        permission="Incident.Read.All",
                        type=AuthType.APP_ONLY,
                        description="Read incident details",
                    ),
                ],
                idempotency_strategy=IdempotencyStrategy.SAFE_TO_RETRY,
                rollback_strategy=RollbackStrategy.NONE,
                audit_fields=["incident_id", "device_id"],
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
            "isolate_device": self._isolate_device,
            "unisolate_device": self._unisolate_device,
            "collect_investigation_package": self._collect_investigation_package,
            "run_antivirus_scan": self._run_antivirus_scan,
            "resolve_device_from_incident": self._resolve_device_from_incident,
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

    async def _isolate_device(
        self, params: dict[str, Any], correlation: CorrelationContext, *, dev_mode: bool = False,
    ) -> ToolResult:
        device_id = params["device_id"]
        comment = params.get("comment", "Isolated by MSClaw")
        isolation_type = params.get("isolation_type", "Full")

        if dev_mode or not self._client:
            logger.info("[DEV] Isolating device %s (type=%s)", device_id, isolation_type)
            result = {"action_id": f"mock-{uuid.uuid4()}", "type": "Isolate", "status": "Pending", "device_id": device_id}
        else:
            result = await self._client.defender_post(
                f"/machines/{device_id}/isolate",
                {"Comment": comment, "IsolationType": isolation_type},
            )

        return ToolResult(
            intent_id=str(uuid.uuid4()),
            plugin=self.name,
            action="isolate_device",
            status=ToolExecutionStatus.COMPLETED,
            result=result,
            correlation=correlation,
        )

    async def _unisolate_device(
        self, params: dict[str, Any], correlation: CorrelationContext, *, dev_mode: bool = False,
    ) -> ToolResult:
        device_id = params["device_id"]
        comment = params.get("comment", "Released by MSClaw")

        if dev_mode or not self._client:
            logger.info("[DEV] Unisolating device %s", device_id)
            result = {"action_id": f"mock-{uuid.uuid4()}", "type": "Unisolate", "status": "Pending", "device_id": device_id}
        else:
            result = await self._client.defender_post(
                f"/machines/{device_id}/unisolate",
                {"Comment": comment},
            )

        return ToolResult(
            intent_id=str(uuid.uuid4()),
            plugin=self.name,
            action="unisolate_device",
            status=ToolExecutionStatus.COMPLETED,
            result=result,
            correlation=correlation,
        )

    async def _collect_investigation_package(
        self, params: dict[str, Any], correlation: CorrelationContext, *, dev_mode: bool = False,
    ) -> ToolResult:
        device_id = params["device_id"]
        comment = params.get("comment", "Collected by MSClaw")

        if dev_mode or not self._client:
            logger.info("[DEV] Collecting investigation package from %s", device_id)
            result = {"action_id": f"mock-{uuid.uuid4()}", "type": "CollectInvestigationPackage", "status": "Pending", "device_id": device_id}
        else:
            result = await self._client.defender_post(
                f"/machines/{device_id}/collectInvestigationPackage",
                {"Comment": comment},
            )

        return ToolResult(
            intent_id=str(uuid.uuid4()),
            plugin=self.name,
            action="collect_investigation_package",
            status=ToolExecutionStatus.COMPLETED,
            result=result,
            correlation=correlation,
        )

    async def _run_antivirus_scan(
        self, params: dict[str, Any], correlation: CorrelationContext, *, dev_mode: bool = False,
    ) -> ToolResult:
        device_id = params["device_id"]
        scan_type = params["scan_type"]
        comment = params.get("comment", "Scan initiated by MSClaw")

        if dev_mode or not self._client:
            logger.info("[DEV] Running %s AV scan on %s", scan_type, device_id)
            result = {"action_id": f"mock-{uuid.uuid4()}", "type": "RunAntiVirusScan", "scan_type": scan_type, "status": "Pending", "device_id": device_id}
        else:
            result = await self._client.defender_post(
                f"/machines/{device_id}/runAntiVirusScan",
                {"Comment": comment, "ScanType": scan_type},
            )

        return ToolResult(
            intent_id=str(uuid.uuid4()),
            plugin=self.name,
            action="run_antivirus_scan",
            status=ToolExecutionStatus.COMPLETED,
            result=result,
            correlation=correlation,
        )

    async def _resolve_device_from_incident(
        self, params: dict[str, Any], correlation: CorrelationContext, *, dev_mode: bool = False,
    ) -> ToolResult:
        incident_id = params.get("incident_id")
        device_id = params.get("device_id")

        if device_id:
            # Direct device lookup
            if dev_mode or not self._client:
                result = {
                    "deviceId": device_id,
                    "deviceDnsName": f"DESKTOP-{device_id[:6].upper()}",
                    "osPlatform": "Windows11",
                    "managedDeviceId": f"intune-{device_id}",
                    "tags": [],
                }
            else:
                result = await self._client.defender_get(f"/machines/{device_id}")
        elif incident_id:
            # Resolve from incident
            if dev_mode or not self._client:
                result = {
                    "deviceId": f"device-from-{incident_id}",
                    "deviceDnsName": f"DESKTOP-INC{incident_id[:4].upper()}",
                    "osPlatform": "Windows11",
                    "incidentId": incident_id,
                    "managedDeviceId": f"intune-from-{incident_id}",
                    "tags": [],
                }
            else:
                incident = await self._client.defender_get(f"/incidents/{incident_id}")
                alerts = incident.get("alerts", [])
                if alerts and alerts[0].get("devices"):
                    device = alerts[0]["devices"][0]
                    result = {
                        "deviceId": device.get("deviceId", ""),
                        "deviceDnsName": device.get("deviceDnsName", ""),
                        "incidentId": incident_id,
                    }
                else:
                    return ToolResult(
                        intent_id=str(uuid.uuid4()),
                        plugin=self.name,
                        action="resolve_device_from_incident",
                        status=ToolExecutionStatus.FAILED,
                        error=f"No devices found in incident {incident_id}",
                        correlation=correlation,
                    )
        else:
            return ToolResult(
                intent_id=str(uuid.uuid4()),
                plugin=self.name,
                action="resolve_device_from_incident",
                status=ToolExecutionStatus.FAILED,
                error="Either incident_id or device_id is required",
                correlation=correlation,
            )

        return ToolResult(
            intent_id=str(uuid.uuid4()),
            plugin=self.name,
            action="resolve_device_from_incident",
            status=ToolExecutionStatus.COMPLETED,
            result=result,
            correlation=correlation,
        )
