"""Orchestrator workflow engine.

The orchestrator produces TOOL-INTENTS, not raw commands.
The LLM is treated as untrusted: it proposes intents, policy decides,
the runner executes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from ...shared.contracts import (
    ApprovalRequest,
    AuditAction,
    AuditEntry,
    CorrelationContext,
    PolicyDecision,
    PolicyInput,
    ToolExecutionStatus,
    ToolIntent,
    ToolResult,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStatus,
    WorkflowStep,
)
from ...shared.errors import (
    ApprovalRequiredError,
    PolicyDeniedError,
    WorkflowError,
)

logger = logging.getLogger("msclaw.orchestrator")


class WorkflowEngine:
    """Executes workflow definitions step by step.

    Responsibilities:
    - Resolve workflow steps into tool intents
    - Check policy for each intent
    - Handle approval gates
    - Publish intents to tool-runner via message bus
    - Track progress and produce audit entries
    """

    def __init__(
        self,
        *,
        policy_evaluator: PolicyEvaluator | None = None,
        dev_mode: bool = True,
    ):
        self._policy = policy_evaluator or PolicyEvaluator(dev_mode=dev_mode)
        self._dev_mode = dev_mode
        self._workflow_registry: dict[str, WorkflowDefinition] = {}
        self._runs: dict[str, WorkflowRun] = {}
        self._audit_log: list[AuditEntry] = []

    def register_workflow(self, workflow: WorkflowDefinition) -> None:
        self._workflow_registry[workflow.workflow_id] = workflow
        logger.info("Registered workflow: %s", workflow.workflow_id)

    async def start_workflow(
        self,
        workflow_id: str,
        inputs: dict[str, Any],
        correlation: CorrelationContext,
        idempotency_key: str,
    ) -> WorkflowRun:
        """Start a new workflow run."""
        workflow = self._workflow_registry.get(workflow_id)
        if not workflow:
            raise WorkflowError(workflow_id, 0, f"Unknown workflow: {workflow_id}",
                                correlation_id=correlation.correlation_id)

        run = WorkflowRun(
            workflow_id=workflow_id,
            inputs=inputs,
            correlation=correlation,
            idempotency_key=idempotency_key,
            status=WorkflowStatus.RUNNING,
        )
        self._runs[run.run_id] = run

        self._emit_audit(
            AuditAction.WORKFLOW_STARTED,
            actor=correlation.operator_id or "system",
            correlation_id=correlation.correlation_id,
            workflow_run_id=run.run_id,
        )

        # Execute steps in order, respecting dependencies
        try:
            for step in workflow.steps:
                await self._execute_step(run, step, workflow)

            run.status = WorkflowStatus.COMPLETED
            run.completed_at = datetime.utcnow()
            self._emit_audit(
                AuditAction.WORKFLOW_COMPLETED,
                actor="system",
                correlation_id=correlation.correlation_id,
                workflow_run_id=run.run_id,
            )

        except PolicyDeniedError as e:
            run.status = WorkflowStatus.FAILED
            run.error = str(e)
            self._emit_audit(
                AuditAction.WORKFLOW_FAILED,
                actor="system",
                correlation_id=correlation.correlation_id,
                workflow_run_id=run.run_id,
                error=str(e),
            )

        except ApprovalRequiredError:
            run.status = WorkflowStatus.AWAITING_APPROVAL

        except Exception as e:
            run.status = WorkflowStatus.FAILED
            run.error = str(e)
            self._emit_audit(
                AuditAction.WORKFLOW_FAILED,
                actor="system",
                correlation_id=correlation.correlation_id,
                workflow_run_id=run.run_id,
                error=str(e),
            )
            logger.exception("Workflow %s failed", workflow_id)

        return run

    async def _execute_step(
        self,
        run: WorkflowRun,
        step: WorkflowStep,
        workflow: WorkflowDefinition,
    ) -> ToolResult:
        """Execute a single workflow step."""
        correlation = CorrelationContext(
            correlation_id=run.correlation.correlation_id,
            workflow_run_id=run.run_id,
            step_index=step.step_index,
            operator_id=run.correlation.operator_id,
            source="orchestrator",
        )

        # Resolve dynamic parameters from previous step results
        resolved_params = self._resolve_parameters(step.parameters, run)

        # Create tool intent
        intent = ToolIntent(
            plugin=step.plugin,
            action=step.action,
            parameters=resolved_params,
            idempotency_key=f"{run.idempotency_key}-step-{step.step_index}",
            correlation=correlation,
        )

        self._emit_audit(
            AuditAction.TOOL_INTENT_CREATED,
            actor="orchestrator",
            correlation_id=correlation.correlation_id,
            workflow_run_id=run.run_id,
            plugin=step.plugin,
            tool_action=step.action,
            inputs=resolved_params,
        )

        # Policy check
        policy_decision = await self._policy.evaluate(
            PolicyInput(
                operator={"id": correlation.operator_id or "system", "roles": ["operator"]},
                action=f"{step.plugin}.{step.action}",
                plugin=step.plugin,
                parameters=resolved_params,
                device_tags=resolved_params.get("device_tags"),
            )
        )

        self._emit_audit(
            AuditAction.TOOL_POLICY_CHECKED,
            actor="policy-gate",
            correlation_id=correlation.correlation_id,
            workflow_run_id=run.run_id,
            plugin=step.plugin,
            tool_action=step.action,
            policy_decision="allow" if policy_decision.allowed else "deny",
        )

        if not policy_decision.allowed and not policy_decision.require_approval:
            raise PolicyDeniedError(
                f"{step.plugin}.{step.action}",
                policy_decision.deny_reason or "Policy denied",
                correlation_id=correlation.correlation_id,
            )

        if policy_decision.require_approval:
            intent.requires_approval = True
            intent.approval_reason = policy_decision.approval_reason
            # Create approval request
            approval = ApprovalRequest(
                workflow_run_id=run.run_id,
                step_index=step.step_index,
                intent=intent,
                reason=policy_decision.approval_reason or "Approval required by policy",
            )
            self._emit_audit(
                AuditAction.TOOL_APPROVAL_REQUESTED,
                actor="policy-gate",
                correlation_id=correlation.correlation_id,
                workflow_run_id=run.run_id,
                plugin=step.plugin,
                tool_action=step.action,
            )
            raise ApprovalRequiredError(
                f"{step.plugin}.{step.action}",
                approval.reason,
                approval.approval_id,
                correlation_id=correlation.correlation_id,
            )

        # Execute via tool runner (in production, publish to NATS)
        result = ToolResult(
            intent_id=intent.intent_id,
            plugin=step.plugin,
            action=step.action,
            status=ToolExecutionStatus.COMPLETED,
            result={"mock": True, "message": f"Executed {step.plugin}.{step.action}"},
            correlation=correlation,
        )

        self._emit_audit(
            AuditAction.TOOL_EXECUTED,
            actor="tool-runner",
            correlation_id=correlation.correlation_id,
            workflow_run_id=run.run_id,
            plugin=step.plugin,
            tool_action=step.action,
            outputs=result.result,
        )

        run.steps_completed.append(step.step_index)
        run.step_results[step.step_index] = result
        run.updated_at = datetime.utcnow()

        return result

    def _resolve_parameters(
        self,
        params: dict[str, Any],
        run: WorkflowRun,
    ) -> dict[str, Any]:
        """Resolve parameter references like ${step.0.result.deviceId}."""
        resolved: dict[str, Any] = {}
        for key, value in params.items():
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                ref = value[2:-1]
                parts = ref.split(".")
                if parts[0] == "input":
                    resolved[key] = run.inputs.get(parts[1], value)
                elif parts[0] == "step":
                    step_idx = int(parts[1])
                    step_result = run.step_results.get(step_idx)
                    if step_result and step_result.result:
                        resolved[key] = step_result.result.get(parts[3], value) if len(parts) > 3 else step_result.result
                    else:
                        resolved[key] = value
                else:
                    resolved[key] = value
            else:
                resolved[key] = value
        return resolved

    def _emit_audit(self, action: AuditAction, actor: str, correlation_id: str, **kwargs: Any) -> None:
        entry = AuditEntry(
            correlation_id=correlation_id,
            action=action,
            actor=actor,
            **kwargs,
        )
        self._audit_log.append(entry)
        logger.info("AUDIT: %s by %s [%s]", action.value, actor, correlation_id)

    def get_run(self, run_id: str) -> WorkflowRun | None:
        return self._runs.get(run_id)


class PolicyEvaluator:
    """Evaluates OPA/Rego policies for tool intents.

    In production, calls the OPA server. In dev mode, uses simple rules.
    """

    def __init__(self, *, opa_url: str = "http://localhost:8181", dev_mode: bool = True):
        self._opa_url = opa_url
        self._dev_mode = dev_mode

    async def evaluate(self, input_data: PolicyInput) -> PolicyDecision:
        """Evaluate a policy for a tool intent."""
        if self._dev_mode:
            return self._dev_evaluate(input_data)

        # Production: call OPA REST API
        try:
            import httpx  # type: ignore[import-untyped]

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._opa_url}/v1/data/msclaw/authz",
                    json={"input": input_data.model_dump()},
                    timeout=5.0,
                )
                result = response.json().get("result", {})
                return PolicyDecision(
                    allowed=result.get("allow", False),
                    require_approval=result.get("require_approval", False),
                    approval_reason=result.get("approval_reason"),
                    deny_reason=result.get("deny_reason"),
                    policy_name="msclaw.authz",
                )
        except Exception as e:
            logger.error("OPA evaluation failed: %s", e)
            # Default deny on policy failure
            return PolicyDecision(
                allowed=False,
                deny_reason=f"Policy evaluation failed: {e}",
                policy_name="msclaw.authz",
            )

    def _dev_evaluate(self, input_data: PolicyInput) -> PolicyDecision:
        """Simple dev-mode policy rules."""
        # Check for VIP device tags requiring approval
        if input_data.device_tags and "VIP" in input_data.device_tags:
            if input_data.action in ("defender_xdr.isolate_device", "entra.disable_user"):
                return PolicyDecision(
                    allowed=True,
                    require_approval=True,
                    approval_reason=f"Device/user is tagged VIP - approval required for {input_data.action}",
                    policy_name="dev.vip_approval",
                )

        # Approval-gated actions
        approval_required = {
            "entra.revoke_signin_sessions",
            "entra.disable_user",
        }
        if input_data.action in approval_required:
            return PolicyDecision(
                allowed=True,
                require_approval=True,
                approval_reason=f"Action {input_data.action} requires explicit approval",
                policy_name="dev.approval_gate",
            )

        # Default allow in dev mode
        return PolicyDecision(allowed=True, policy_name="dev.default_allow")
