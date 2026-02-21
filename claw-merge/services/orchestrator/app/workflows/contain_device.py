"""Contain Device from Incident – the MVP end-to-end workflow.

Steps:
1. Resolve device from Defender incident (if incidentId provided)
2. Policy check for isolate action
3. Require approval if device is tagged "VIP" (policy-driven)
4. Isolate device
5. Collect investigation package
6. Store artifacts
7. Summarize outcome
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from ulid import ULID

from msclaw_shared.models.common import IdempotencyKey
from msclaw_shared.models.tool_intent import ToolIntent, ToolResultStatus
from msclaw_shared.models.workflow import WorkflowRun, WorkflowStatus, WorkflowStep, StepStatus

if TYPE_CHECKING:
    from app.engine.workflow_engine import WorkflowEngine

logger = logging.getLogger("msclaw.orchestrator.workflows.contain_device")


class ContainDeviceWorkflow:
    """Implements the 'Contain device from incident' workflow."""

    def __init__(self, engine: WorkflowEngine):
        self._engine = engine

    async def execute(self, run: WorkflowRun) -> None:
        """Execute the full workflow."""
        inputs = run.inputs
        incident_id = inputs.get("incidentId")
        device_id = inputs.get("deviceId")
        actor_roles = inputs.get("actor_roles", ["security-lead"])

        if not incident_id and not device_id:
            raise ValueError("Either incidentId or deviceId must be provided")

        # Step 1: Resolve device from incident
        if incident_id and not device_id:
            device_id = await self._resolve_device_from_incident(
                run, incident_id, actor_roles
            )

        if not device_id:
            raise ValueError("Could not resolve deviceId from incident")

        # Get device tags for policy decisions
        device_tags = inputs.get("device_tags", [])

        # Step 2+3: Isolate device (policy check + approval happens inside execute_tool_intent)
        isolate_result = await self._engine.execute_tool_intent(
            ToolIntent(
                intent_id=str(ULID()),
                correlation_id=run.correlation_id,
                workflow_run_id=run.run_id,
                step_id="isolate_device",
                plugin="defender_xdr",
                action="isolate_device",
                inputs={"deviceId": device_id},
                idempotency_key=IdempotencyKey(f"{run.idempotency_key}-isolate"),
                requested_by=run.submitted_by,
                device_tags=device_tags,
            ),
            actor_roles=actor_roles,
        )

        if isolate_result.status == ToolResultStatus.APPROVAL_PENDING:
            logger.info("Workflow paused: awaiting approval for device isolation")
            await self._engine._update_workflow_status(
                run.run_id, WorkflowStatus.AWAITING_APPROVAL
            )
            return  # Workflow will be resumed when approval is decided

        if isolate_result.status == ToolResultStatus.DENIED:
            raise RuntimeError(f"Device isolation denied: {isolate_result.error}")

        if isolate_result.status == ToolResultStatus.FAILURE:
            raise RuntimeError(f"Device isolation failed: {isolate_result.error}")

        # Step 5: Collect investigation package
        collect_result = await self._engine.execute_tool_intent(
            ToolIntent(
                intent_id=str(ULID()),
                correlation_id=run.correlation_id,
                workflow_run_id=run.run_id,
                step_id="collect_investigation_package",
                plugin="defender_xdr",
                action="collect_investigation_package",
                inputs={"deviceId": device_id},
                idempotency_key=IdempotencyKey(f"{run.idempotency_key}-collect"),
                requested_by=run.submitted_by,
                device_tags=device_tags,
            ),
            actor_roles=actor_roles,
        )

        # Step 6: Artifacts stored by tool runner (outputs contain storage keys)
        artifacts = collect_result.artifacts

        # Step 7: Complete workflow
        outputs = {
            "deviceId": device_id,
            "isolated": isolate_result.status == ToolResultStatus.SUCCESS,
            "investigation_package": collect_result.status == ToolResultStatus.SUCCESS,
            "artifacts": artifacts,
            "summary": (
                f"Device {device_id} has been isolated. "
                f"Investigation package {'collected' if collect_result.status == ToolResultStatus.SUCCESS else 'failed'}. "
                f"Artifacts: {len(artifacts)} files stored."
            ),
        }

        await self._engine._update_workflow_status(
            run.run_id,
            WorkflowStatus.COMPLETED,
            outputs=outputs,
        )
        logger.info("Workflow completed: %s", run.run_id)

    async def _resolve_device_from_incident(
        self, run: WorkflowRun, incident_id: str, actor_roles: list[str]
    ) -> str | None:
        """Resolve device ID from a Defender incident."""
        result = await self._engine.execute_tool_intent(
            ToolIntent(
                intent_id=str(ULID()),
                correlation_id=run.correlation_id,
                workflow_run_id=run.run_id,
                step_id="resolve_device",
                plugin="defender_xdr",
                action="get_incident_devices",
                inputs={"incidentId": incident_id},
                idempotency_key=IdempotencyKey(f"{run.idempotency_key}-resolve"),
                requested_by=run.submitted_by,
            ),
            actor_roles=actor_roles,
        )

        if result.status == ToolResultStatus.SUCCESS:
            devices = result.outputs.get("devices", [])
            if devices:
                return devices[0].get("deviceId")
        return None
