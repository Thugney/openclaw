"""Tool Runner – Consumes workflow.step.intent from NATS, executes tools,
emits workflow.step.result.

CRITICAL: The tool-runner REFUSES to execute any action unless a valid
policy_decision_id is present in the intent message AND that decision exists
in Postgres with decision="allow".  This makes the OPA policy gate the single
choke point – bypassing it is structurally impossible.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from msclaw_shared.audit import append_audit
from msclaw_shared.bus import (
    SUBJECT_STEP_INTENT,
    SUBJECT_STEP_RESULT,
    BusMessage,
    MessageBus,
)
from msclaw_shared.config import load_config
from msclaw_shared.db import (
    PolicyDecision,
    Step,
    ToolExecution,
    get_session,
)

logger = logging.getLogger("msclaw.tool_runner")

bus = MessageBus()

# Tool registry – maps tool names to adapter callables
_tool_registry: dict[str, object] = {}


def register_tool(name: str, adapter: object) -> None:
    _tool_registry[name] = adapter


async def start() -> None:
    """Boot the tool-runner: connect NATS, register tools, subscribe."""
    cfg = load_config()
    await bus.connect(cfg.nats)

    # Register Microsoft adapters based on mode
    _register_adapters(cfg.microsoft.mode)

    await bus.subscribe(
        SUBJECT_STEP_INTENT,
        _handle_step_intent,
        durable_name="tool-runner-step-intent",
    )
    logger.info("Tool Runner started (adapter mode: %s)", cfg.microsoft.mode)


async def shutdown() -> None:
    await bus.close()


def _register_adapters(mode: str) -> None:
    """Register tool adapters based on configured mode (real/mock)."""
    if mode == "real":
        from msclaw_shared.adapters.microsoft.real.defender import (
            resolve_device_from_incident,
            isolate_device,
            collect_investigation_package,
        )
        register_tool("resolve_device_from_incident", resolve_device_from_incident)
        register_tool("isolate_device", isolate_device)
        register_tool("collect_investigation_package", collect_investigation_package)
    else:
        from msclaw_shared.adapters.microsoft.mock.defender import (
            resolve_device_from_incident,
            isolate_device,
            collect_investigation_package,
        )
        register_tool("resolve_device_from_incident", resolve_device_from_incident)
        register_tool("isolate_device", isolate_device)
        register_tool("collect_investigation_package", collect_investigation_package)

    logger.info("Registered %d tools in %s mode", len(_tool_registry), mode)


# ---------------------------------------------------------------------------
# Intent handler
# ---------------------------------------------------------------------------

async def _handle_step_intent(msg: BusMessage) -> None:
    """Process a step intent: verify policy, execute tool, emit result."""
    tool_name = msg.payload.get("tool_name")
    step_name = msg.payload.get("step_name")
    params = msg.payload.get("params", {})
    policy_decision_id = msg.payload.get("policy_decision_id")
    initiated_by = msg.payload.get("initiated_by", "system")
    step_id = msg.step_id
    run_id = msg.run_id
    correlation_id = msg.correlation_id

    logger.info(
        "Received step intent: tool=%s step=%s run=%s corr=%s",
        tool_name, step_name, run_id, correlation_id,
    )

    # -------------------------------------------------------------------
    # POLICY VERIFICATION – THE SINGLE CHOKE POINT
    # Tool-runner will NOT execute without a valid, durable policy decision.
    # -------------------------------------------------------------------
    if not policy_decision_id:
        error = "REJECTED: No policy_decision_id in intent – possible bypass attempt"
        logger.error(error)
        await _emit_failure(msg, error)
        await append_audit(
            correlation_id=correlation_id,
            run_id=run_id,
            step_id=step_id,
            actor="tool-runner",
            action="step.rejected.no_policy",
            detail={"tool": tool_name, "error": error},
            policy_decision="reject",
        )
        return

    # Verify the policy decision exists in Postgres and is "allow"
    async with get_session() as session:
        result = await session.execute(
            select(PolicyDecision).where(
                PolicyDecision.id == uuid.UUID(policy_decision_id)
            )
        )
        decision = result.scalar_one_or_none()

    if not decision:
        error = f"REJECTED: policy_decision_id {policy_decision_id} not found in database"
        logger.error(error)
        await _emit_failure(msg, error)
        await append_audit(
            correlation_id=correlation_id,
            run_id=run_id,
            step_id=step_id,
            actor="tool-runner",
            action="step.rejected.invalid_policy",
            detail={"policy_decision_id": policy_decision_id, "error": error},
            policy_decision="reject",
        )
        return

    if decision.decision != "allow":
        error = f"REJECTED: policy decision is '{decision.decision}', not 'allow'"
        logger.error(error)
        await _emit_failure(msg, error)
        await append_audit(
            correlation_id=correlation_id,
            run_id=run_id,
            step_id=step_id,
            actor="tool-runner",
            action="step.rejected.policy_not_allow",
            detail={"decision": decision.decision, "reasons": decision.reasons},
            policy_decision="reject",
        )
        return

    # -------------------------------------------------------------------
    # Tool execution
    # -------------------------------------------------------------------
    adapter = _tool_registry.get(tool_name)
    if not adapter:
        error = f"Unknown tool: {tool_name}"
        await _emit_failure(msg, error)
        await append_audit(
            correlation_id=correlation_id,
            run_id=run_id,
            step_id=step_id,
            actor="tool-runner",
            action="step.failed.unknown_tool",
            detail={"tool": tool_name},
        )
        return

    cfg = load_config()
    adapter_mode = cfg.microsoft.mode

    # Record tool execution start
    exec_id = uuid.uuid4()
    async with get_session() as session:
        tool_exec = ToolExecution(
            id=exec_id,
            step_id=uuid.UUID(step_id) if step_id else uuid.uuid4(),
            run_id=uuid.UUID(run_id) if run_id else uuid.uuid4(),
            correlation_id=uuid.UUID(correlation_id),
            tool_name=tool_name,
            adapter_mode=adapter_mode,
            input_params=params,
            status="running",
        )
        session.add(tool_exec)
        await session.flush()

    await append_audit(
        correlation_id=correlation_id,
        run_id=run_id,
        step_id=step_id,
        actor="tool-runner",
        action="step.executing",
        tool=tool_name,
        adapter_mode=adapter_mode,
        detail={"adapter_mode": adapter_mode, "policy_decision_id": policy_decision_id},
    )

    try:
        output = await adapter(params)

        # Record completion
        artifact_keys = output.pop("_artifact_keys", []) if isinstance(output, dict) else []
        async with get_session() as session:
            r = await session.execute(
                select(ToolExecution).where(ToolExecution.id == exec_id).with_for_update()
            )
            te = r.scalar_one()
            te.status = "completed"
            te.output_metadata = output if isinstance(output, dict) else {"result": output}
            te.artifact_keys = artifact_keys
            te.completed_at = datetime.now(timezone.utc)
            await session.flush()

        await append_audit(
            correlation_id=correlation_id,
            run_id=run_id,
            step_id=step_id,
            actor="tool-runner",
            action="step.completed",
            tool=tool_name,
            adapter_mode=adapter_mode,
            detail={
                "output_keys": list(output.keys()) if isinstance(output, dict) else [],
                "artifact_count": len(artifact_keys),
            },
        )

        # Emit result to NATS
        await bus.publish(BusMessage(
            subject=SUBJECT_STEP_RESULT,
            correlation_id=correlation_id,
            run_id=run_id,
            step_id=step_id,
            payload={
                "status": "completed",
                "output": output if isinstance(output, dict) else {"result": output},
                "artifact_keys": artifact_keys,
                "tool_name": tool_name,
                "adapter_mode": adapter_mode,
            },
        ))

        logger.info("Tool %s completed for step %s", tool_name, step_id)

    except Exception as exc:
        error_msg = str(exc)
        logger.exception("Tool %s failed: %s", tool_name, error_msg)

        async with get_session() as session:
            r = await session.execute(
                select(ToolExecution).where(ToolExecution.id == exec_id).with_for_update()
            )
            te = r.scalar_one()
            te.status = "failed"
            te.error = error_msg
            te.completed_at = datetime.now(timezone.utc)
            await session.flush()

        await append_audit(
            correlation_id=correlation_id,
            run_id=run_id,
            step_id=step_id,
            actor="tool-runner",
            action="step.failed",
            tool=tool_name,
            adapter_mode=adapter_mode,
            detail={"error": error_msg},
        )

        await _emit_failure(msg, error_msg)


async def _emit_failure(msg: BusMessage, error: str) -> None:
    """Emit a failure result back to NATS."""
    await bus.publish(BusMessage(
        subject=SUBJECT_STEP_RESULT,
        correlation_id=msg.correlation_id,
        run_id=msg.run_id,
        step_id=msg.step_id,
        payload={"status": "failed", "error": error},
    ))
