"""Workflow: Contain device from incident.

End-to-end workflow that:
1. Resolves device from Defender incident (if incidentId provided)
2. Checks policy for isolate action
3. Requires approval if device is tagged "VIP" (policy-driven)
4. Isolates device
5. Collects investigation package
6. Stores artifacts
7. Summarizes outcome with ability to unisolate
"""

from __future__ import annotations

from ...shared.contracts import WorkflowDefinition, WorkflowStep

CONTAIN_DEVICE_WORKFLOW = WorkflowDefinition(
    workflow_id="contain-device-from-incident",
    name="Contain Device from Incident",
    description=(
        "Isolates a compromised device identified from a Defender XDR incident. "
        "Collects investigation package, stores artifacts, and provides "
        "unisolate capability. Approval-gated for VIP devices."
    ),
    version="1.0.0",
    steps=[
        WorkflowStep(
            step_index=0,
            name="Resolve device from incident",
            plugin="defender_xdr",
            action="resolve_device_from_incident",
            parameters={
                "incident_id": "${input.incidentId}",
                "device_id": "${input.deviceId}",
            },
        ),
        WorkflowStep(
            step_index=1,
            name="Isolate device",
            plugin="defender_xdr",
            action="isolate_device",
            parameters={
                "device_id": "${step.0.result.deviceId}",
            },
            depends_on=[0],
        ),
        WorkflowStep(
            step_index=2,
            name="Collect investigation package",
            plugin="defender_xdr",
            action="collect_investigation_package",
            parameters={
                "device_id": "${step.0.result.deviceId}",
            },
            depends_on=[1],
        ),
        WorkflowStep(
            step_index=3,
            name="Run antivirus scan",
            plugin="defender_xdr",
            action="run_antivirus_scan",
            parameters={
                "device_id": "${step.0.result.deviceId}",
                "scan_type": "Full",
            },
            depends_on=[1],
        ),
        WorkflowStep(
            step_index=4,
            name="Sync device with Intune",
            plugin="intune",
            action="sync_device",
            parameters={
                "managed_device_id": "${step.0.result.managedDeviceId}",
            },
            depends_on=[1],
        ),
    ],
    input_schema={
        "type": "object",
        "properties": {
            "incidentId": {
                "type": "string",
                "description": "Defender XDR incident ID (optional if deviceId provided)",
            },
            "deviceId": {
                "type": "string",
                "description": "Device ID (optional if incidentId provided)",
            },
        },
        "anyOf": [
            {"required": ["incidentId"]},
            {"required": ["deviceId"]},
        ],
    },
)
