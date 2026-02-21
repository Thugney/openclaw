"""Workflow engine – executes registered workflows step by step.

The engine:
1. Receives workflow submissions from NATS
2. Loads the workflow definition
3. Executes steps sequentially, producing ToolIntents
4. Sends intents through policy gate -> tool runner
5. Handles approval waits
6. Records audit entries for every action
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from ulid import ULID

from msclaw_shared.bus import MessageBus, SUBJECTS
from msclaw_shared.models.approval import ApprovalRequest, ApprovalStatus
from msclaw_shared.models.audit import AuditDecision, AuditEntry
from msclaw_shared.models.common import CorrelationId, IdempotencyKey, new_correlation_id
from msclaw_shared.models.policy import PolicyVerdict
from msclaw_shared.models.tool_intent import ToolIntent, ToolResult, ToolResultStatus
from msclaw_shared.models.workflow import WorkflowRun, WorkflowStatus, WorkflowStep, StepStatus

logger = logging.getLogger("msclaw.orchestrator.engine")


class WorkflowEngine:
    def __init__(
        self,
        nats_url: str,
        control_api_url: str,
        tool_runner_url: str,
        model_router_url: str,
        opa_url: str,
        dev_mode: bool = True,
    ):
        self._bus = MessageBus(url=nats_url)
        self._control_api_url = control_api_url.rstrip("/")
        self._tool_runner_url = tool_runner_url.rstrip("/")
        self._model_router_url = model_router_url.rstrip("/")
        self._opa_url = opa_url.rstrip("/")
        self._dev_mode = dev_mode
        self._pending_approvals: dict[str, dict[str, Any]] = {}

    async def start(self) -> None:
        await self._bus.connect()

    async def stop(self) -> None:
        await self._bus.disconnect()

    async def execute_workflow(self, run_data: dict[str, Any]) -> None:
        """Execute a workflow from submission data."""
        run = WorkflowRun.model_validate(run_data)
        logger.info("Executing workflow: %s (run_id=%s)", run.workflow_name, run.run_id)

        try:
            # Update status to running
            await self._update_workflow_status(run.run_id, WorkflowStatus.RUNNING)

            if run.workflow_name == "contain_device_from_incident":
                from app.workflows.contain_device import ContainDeviceWorkflow
                workflow = ContainDeviceWorkflow(engine=self)
                await workflow.execute(run)
            else:
                raise ValueError(f"Unknown workflow: {run.workflow_name}")

        except Exception as exc:
            logger.exception("Workflow failed: %s", run.run_id)
            await self._update_workflow_status(
                run.run_id, WorkflowStatus.FAILED, error=str(exc)
            )
            await self._emit_audit(
                correlation_id=run.correlation_id,
                actor=run.submitted_by,
                action=f"workflow.{run.workflow_name}.failed",
                service="orchestrator",
                error=str(exc),
            )

    async def execute_tool_intent(
        self, intent: ToolIntent, actor_roles: list[str]
    ) -> ToolResult:
        """Execute a tool intent through the full pipeline:
        1. Policy check
        2. Approval (if required)
        3. Tool execution
        4. Audit
        """
        # Step 1: Policy check
        policy_decision = await self._check_policy(intent, actor_roles)

        if policy_decision["verdict"] == "deny":
            await self._emit_audit(
                correlation_id=intent.correlation_id,
                actor=intent.requested_by,
                action=f"{intent.plugin}.{intent.action}",
                service="orchestrator",
                inputs=intent.inputs,
                policy_decision=AuditDecision.DENIED,
                policy_rule=policy_decision.get("rule", ""),
                policy_reason=policy_decision.get("reason", ""),
                tool_name=f"{intent.plugin}.{intent.action}",
                idempotency_key=intent.idempotency_key,
            )
            return ToolResult(
                intent_id=intent.intent_id,
                correlation_id=intent.correlation_id,
                status=ToolResultStatus.DENIED,
                error=f"Policy denied: {policy_decision.get('reason', '')}",
            )

        # Step 2: Handle approval if required
        if policy_decision["verdict"] == "require_approval":
            approval_id = str(ULID())
            approval = ApprovalRequest(
                approval_id=approval_id,
                correlation_id=intent.correlation_id,
                workflow_run_id=intent.workflow_run_id,
                step_id=intent.step_id,
                intent_id=intent.intent_id,
                plugin=intent.plugin,
                action=intent.action,
                inputs=intent.inputs,
                requested_by=intent.requested_by,
                required_approvers=policy_decision.get("required_approvers", []),
                policy_reason=policy_decision.get("reason", ""),
            )

            # Store approval request via control API
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self._control_api_url}/api/v1/approvals",
                    content=approval.model_dump_json(),
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code not in (200, 201):
                    logger.warning("Failed to create approval via API, using bus")

            # Also publish to bus for UI notification
            await self._bus.publish(SUBJECTS["approval_requested"], approval)

            await self._emit_audit(
                correlation_id=intent.correlation_id,
                actor=intent.requested_by,
                action=f"{intent.plugin}.{intent.action}",
                service="orchestrator",
                inputs=intent.inputs,
                policy_decision=AuditDecision.APPROVAL_REQUIRED,
                policy_rule=policy_decision.get("rule", ""),
                policy_reason=policy_decision.get("reason", ""),
                tool_name=f"{intent.plugin}.{intent.action}",
                idempotency_key=intent.idempotency_key,
            )

            return ToolResult(
                intent_id=intent.intent_id,
                correlation_id=intent.correlation_id,
                status=ToolResultStatus.APPROVAL_PENDING,
                outputs={"approval_id": approval_id},
            )

        # Step 3: Execute tool via tool-runner
        result = await self._execute_via_runner(intent)

        # Step 4: Audit
        await self._emit_audit(
            correlation_id=intent.correlation_id,
            actor=intent.requested_by,
            action=f"{intent.plugin}.{intent.action}",
            service="orchestrator",
            inputs=intent.inputs,
            outputs=result.outputs,
            policy_decision=AuditDecision.ALLOWED,
            policy_rule=policy_decision.get("rule", ""),
            tool_name=f"{intent.plugin}.{intent.action}",
            idempotency_key=intent.idempotency_key,
            error=result.error,
        )

        return result

    async def handle_approval_decision(self, decision_data: dict[str, Any]) -> None:
        """Handle an approval decision and resume the workflow if approved."""
        approval_id = decision_data["approval_id"]
        status = decision_data["status"]
        correlation_id = decision_data.get("correlation_id", "")
        workflow_run_id = decision_data.get("workflow_run_id")

        logger.info("Approval %s decided: %s", approval_id, status)

        if status == "approved" and workflow_run_id:
            # Re-trigger workflow continuation
            # In a full implementation, the workflow would be resumed from the approval step
            await self._emit_audit(
                correlation_id=CorrelationId(correlation_id),
                actor=decision_data.get("decided_by", "system"),
                action="approval.approved",
                service="orchestrator",
                policy_decision=AuditDecision.APPROVED,
                inputs={"approval_id": approval_id, "workflow_run_id": workflow_run_id},
            )

    async def _check_policy(
        self, intent: ToolIntent, actor_roles: list[str]
    ) -> dict[str, Any]:
        """Check OPA policy for a tool intent."""
        policy_input = {
            "plugin": intent.plugin,
            "action": intent.action,
            "inputs": intent.inputs,
            "requested_by": intent.requested_by,
            "actor_roles": actor_roles,
            "device_tags": intent.device_tags,
            "risk_level": intent.risk_level,
        }

        if self._dev_mode:
            # In dev mode, simulate policy based on device tags
            if "VIP" in intent.device_tags:
                return {
                    "verdict": "require_approval",
                    "rule": "dev_vip_approval",
                    "reason": "Device is tagged VIP – approval required",
                    "required_approvers": ["security-lead"],
                }
            return {
                "verdict": "allow",
                "rule": "dev_default_allow",
                "reason": "Dev mode: default allow",
            }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{self._opa_url}/v1/data/msclaw/tool_policy",
                    json={"input": policy_input},
                )
                resp.raise_for_status()
                return resp.json().get("result", {"verdict": "deny", "rule": "default_deny"})
        except httpx.HTTPError as exc:
            logger.error("OPA check failed: %s – defaulting to deny", exc)
            return {"verdict": "deny", "rule": "opa_error", "reason": str(exc)}

    async def _execute_via_runner(self, intent: ToolIntent) -> ToolResult:
        """Send a tool intent to the tool-runner for execution."""
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self._tool_runner_url}/api/v1/execute",
                    content=intent.model_dump_json(),
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                return ToolResult.model_validate(resp.json())
        except httpx.HTTPError as exc:
            logger.error("Tool runner execution failed: %s", exc)
            return ToolResult(
                intent_id=intent.intent_id,
                correlation_id=intent.correlation_id,
                status=ToolResultStatus.FAILURE,
                error=f"Tool runner error: {exc}",
            )

    async def _update_workflow_status(
        self, run_id: str, status: WorkflowStatus, **kwargs: Any
    ) -> None:
        """Update workflow status via control API."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.patch(
                    f"{self._control_api_url}/api/v1/workflows/{run_id}/status",
                    json={"status": status.value, **kwargs},
                )
        except httpx.HTTPError as exc:
            logger.error("Failed to update workflow status: %s", exc)

    async def _emit_audit(self, **kwargs: Any) -> None:
        """Emit an audit entry via NATS."""
        entry = AuditEntry(
            id=str(ULID()),
            **kwargs,
        )
        try:
            await self._bus.publish(SUBJECTS["audit_append"], entry)
        except Exception:
            logger.exception("Failed to emit audit entry")
