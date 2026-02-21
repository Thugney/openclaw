"""Defender XDR plugin – device isolation, investigation packages, AV scans.

Uses Microsoft Defender for Endpoint API (app-only auth).
API base: https://api.securitycenter.microsoft.com/api
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

logger = logging.getLogger("msclaw.plugins.defender_xdr")

MDE_API_BASE = "https://api.securitycenter.microsoft.com/api"


class DefenderXDRPlugin(PluginBase):
    def __init__(self, dev_mode: bool = True):
        self._dev_mode = dev_mode

    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="defender_xdr",
            version="0.1.0",
            description="Microsoft Defender for Endpoint / Defender XDR operations",
            actions=[
                ActionDefinition(
                    name="isolate_device",
                    description="Isolate a device from the network via Defender for Endpoint",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "deviceId": {"type": "string", "description": "MDE machine ID"},
                            "comment": {"type": "string", "default": "Isolated by MSClaw"},
                            "isolationType": {
                                "type": "string",
                                "enum": ["Full", "Selective"],
                                "default": "Full",
                            },
                        },
                        "required": ["deviceId"],
                    },
                    required_permissions=["Machine.Isolate"],
                    idempotency_strategy=IdempotencyStrategy.CHECK_AND_SKIP,
                    rollback_action="unisolate_device",
                    audit_fields=["deviceId", "isolationType"],
                ),
                ActionDefinition(
                    name="unisolate_device",
                    description="Release a device from network isolation",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "deviceId": {"type": "string"},
                            "comment": {"type": "string", "default": "Released by MSClaw"},
                        },
                        "required": ["deviceId"],
                    },
                    required_permissions=["Machine.Isolate"],
                    idempotency_strategy=IdempotencyStrategy.CHECK_AND_SKIP,
                    rollback_action="isolate_device",
                    audit_fields=["deviceId"],
                ),
                ActionDefinition(
                    name="collect_investigation_package",
                    description="Collect forensic investigation package from device",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "deviceId": {"type": "string"},
                            "comment": {"type": "string", "default": "Collected by MSClaw"},
                        },
                        "required": ["deviceId"],
                    },
                    required_permissions=["Machine.CollectForensics"],
                    idempotency_strategy=IdempotencyStrategy.SAFE_TO_RETRY,
                    audit_fields=["deviceId"],
                ),
                ActionDefinition(
                    name="run_antivirus_scan",
                    description="Run antivirus scan on device",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "deviceId": {"type": "string"},
                            "scanType": {
                                "type": "string",
                                "enum": ["Quick", "Full"],
                                "default": "Quick",
                            },
                            "comment": {"type": "string", "default": "Scan by MSClaw"},
                        },
                        "required": ["deviceId"],
                    },
                    required_permissions=["Machine.Scan"],
                    idempotency_strategy=IdempotencyStrategy.SAFE_TO_RETRY,
                    audit_fields=["deviceId", "scanType"],
                ),
                ActionDefinition(
                    name="get_incident_devices",
                    description="Get devices associated with a Defender incident",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "incidentId": {"type": "string"},
                        },
                        "required": ["incidentId"],
                    },
                    required_permissions=["Incident.Read.All"],
                    idempotency_strategy=IdempotencyStrategy.SAFE_TO_RETRY,
                    audit_fields=["incidentId"],
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
        """Dev mode – return mock responses."""
        logger.info("DEV MODE: %s.%s inputs=%s", "defender_xdr", action, inputs)

        if action == "isolate_device":
            return {
                "status": "succeeded",
                "machineId": inputs["deviceId"],
                "type": "Isolate",
                "requestor": context.actor,
                "requestorComment": inputs.get("comment", "Isolated by MSClaw"),
                "_dev_mock": True,
            }
        elif action == "unisolate_device":
            return {
                "status": "succeeded",
                "machineId": inputs["deviceId"],
                "type": "Unisolate",
                "requestor": context.actor,
                "_dev_mock": True,
            }
        elif action == "collect_investigation_package":
            return {
                "status": "succeeded",
                "machineId": inputs["deviceId"],
                "type": "CollectInvestigationPackage",
                "_dev_mock": True,
                "_artifacts": {
                    "investigation_package.zip": {
                        "type": "mock",
                        "deviceId": inputs["deviceId"],
                        "content": "mock investigation package data",
                    },
                },
            }
        elif action == "run_antivirus_scan":
            return {
                "status": "succeeded",
                "machineId": inputs["deviceId"],
                "scanType": inputs.get("scanType", "Quick"),
                "_dev_mock": True,
            }
        elif action == "get_incident_devices":
            return {
                "devices": [
                    {
                        "deviceId": f"mock-device-{inputs['incidentId']}",
                        "deviceName": "MOCK-PC-001",
                        "osPlatform": "Windows10",
                        "tags": [],
                    }
                ],
                "_dev_mock": True,
            }
        else:
            raise PluginError(
                f"Unknown action: {action}",
                plugin="defender_xdr",
                action=action,
            )

    async def _execute_real(
        self, action: str, inputs: dict[str, Any], context: PluginContext
    ) -> dict[str, Any]:
        """Real execution against Microsoft Defender for Endpoint API."""
        if not context.access_token:
            raise PluginError(
                "No access token provided",
                plugin="defender_xdr",
                action=action,
            )

        headers = {
            "Authorization": f"Bearer {context.access_token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            if action == "isolate_device":
                resp = await client.post(
                    f"{MDE_API_BASE}/machines/{inputs['deviceId']}/isolate",
                    headers=headers,
                    json={
                        "Comment": inputs.get("comment", "Isolated by MSClaw"),
                        "IsolationType": inputs.get("isolationType", "Full"),
                    },
                )
            elif action == "unisolate_device":
                resp = await client.post(
                    f"{MDE_API_BASE}/machines/{inputs['deviceId']}/unisolate",
                    headers=headers,
                    json={"Comment": inputs.get("comment", "Released by MSClaw")},
                )
            elif action == "collect_investigation_package":
                resp = await client.post(
                    f"{MDE_API_BASE}/machines/{inputs['deviceId']}/collectInvestigationPackage",
                    headers=headers,
                    json={"Comment": inputs.get("comment", "Collected by MSClaw")},
                )
            elif action == "run_antivirus_scan":
                resp = await client.post(
                    f"{MDE_API_BASE}/machines/{inputs['deviceId']}/runAntiVirusScan",
                    headers=headers,
                    json={
                        "Comment": inputs.get("comment", "Scan by MSClaw"),
                        "ScanType": inputs.get("scanType", "Quick"),
                    },
                )
            elif action == "get_incident_devices":
                # Use Defender XDR incidents API
                resp = await client.get(
                    f"{MDE_API_BASE}/incidents/{inputs['incidentId']}",
                    headers=headers,
                )
            else:
                raise PluginError(
                    f"Unknown action: {action}",
                    plugin="defender_xdr",
                    action=action,
                )

            if resp.status_code >= 400:
                raise PluginError(
                    f"API error {resp.status_code}: {resp.text}",
                    plugin="defender_xdr",
                    action=action,
                    upstream_error=resp.text,
                )

            return resp.json()
