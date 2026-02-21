"""Orchestrator – Consumes workflow.run.requested / workflow.run.approved from NATS,
walks the step graph, emits workflow.step.intent for each step, waits for results.

The orchestrator:
  1. Consumes run requests from NATS (NOT direct HTTP calls)
  2. For each step: evaluates OPA policy, then emits step.intent to NATS
  3. Waits for step.result from tool-runner via NATS
  4. Updates run status via NATS (workflow.run.status)
  5. All state is in Postgres – orchestrator is stateless and restartable
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from msclaw.shared.audit import append_audit
from msclaw.shared.bus import (
    SUBJECT_APPROVAL_REQUIRED,
    SUBJECT_RUN_APPROVED,
    SUBJECT_RUN_REQUESTED,
    SUBJECT_RUN_STATUS,
    SUBJECT_STEP_INTENT,
    SUBJECT_STEP_RESULT,
    BusMessage,
    MessageBus,
)
from msclaw.shared.config import load_config
from msclaw.shared.db import (
    Approval,
    Run,
    RunStatus,
    Step,
    StepStatus,
    get_session,
)
from msclaw.shared.policy import ApprovalRequired, PolicyDenied, evaluate_policy

logger = logging.getLogger("msclaw.orchestrator")

bus = MessageBus()

# Track pending step completions in-memory (ephemeral cache only –
# on restart we re-check Postgres for incomplete runs)
_step_waiters: dict[str, asyncio.Event] = {}
_step_results: dict[str, dict] = {}


async def start() -> None:
    """Boot the orchestrator: connect NATS, subscribe, recover incomplete runs."""
    cfg = load_config()
    await bus.connect(cfg.nats)

    await bus.subscribe(
        SUBJECT_RUN_REQUESTED,
        _handle_run_requested,
        durable_name="orchestrator-run-requested",
    )
    await bus.subscribe(
        SUBJECT_RUN_APPROVED,
        _handle_run_approved,
        durable_name="orchestrator-run-approved",
    )
    await bus.subscribe(
        SUBJECT_STEP_RESULT,
        _handle_step_result,
        durable_name="orchestrator-step-result",
    )

    # Recover runs that were in-progress before restart
    asyncio.create_task(_recover_incomplete_runs())

    logger.info("Orchestrator started")


async def shutdown() -> None:
    await bus.close()


# ---------------------------------------------------------------------------
# NATS handlers
# ---------------------------------------------------------------------------

async def _handle_run_requested(msg: BusMessage) -> None:
    """A new run has been submitted and policy-approved by control-api."""
    run_id = msg.payload.get("run_id")
    if not run_id:
        logger.error("run.requested missing run_id")
        return

    logger.info("Processing run %s (corr=%s)", run_id, msg.correlation_id)
    asyncio.create_task(_execute_run(
        run_id=run_id,
        correlation_id=msg.correlation_id,
        steps_def=msg.payload.get("steps", []),
        params=msg.payload.get("params", {}),
        initiated_by=msg.payload.get("initiated_by", "system"),
        policy_decision_id=msg.payload.get("policy_decision_id"),
    ))


async def _handle_run_approved(msg: BusMessage) -> None:
    """A previously pending run has been approved."""
    run_id = msg.payload.get("run_id")
    if not run_id:
        return

    logger.info("Run %s approved, starting execution", run_id)
    asyncio.create_task(_execute_run(
        run_id=run_id,
        correlation_id=msg.correlation_id,
        steps_def=msg.payload.get("steps", []),
        params=msg.payload.get("params", {}),
        initiated_by=msg.payload.get("initiated_by", "system"),
        policy_decision_id=msg.payload.get("policy_decision_id"),
    ))


async def _handle_step_result(msg: BusMessage) -> None:
    """Tool-runner completed a step – signal the waiter."""
    step_id = msg.step_id
    if step_id and step_id in _step_waiters:
        _step_results[step_id] = msg.payload
        _step_waiters[step_id].set()

    logger.info("Step result received: step=%s status=%s", step_id, msg.payload.get("status"))


# ---------------------------------------------------------------------------
# Run execution
# ---------------------------------------------------------------------------

async def _execute_run(
    *,
    run_id: str,
    correlation_id: str,
    steps_def: list[dict],
    params: dict,
    initiated_by: str,
    policy_decision_id: str | None,
) -> None:
    """Execute all steps in a run sequentially."""

    # Mark run as running
    await _update_run_status(run_id, "running", correlation_id)

    await append_audit(
        correlation_id=correlation_id,
        run_id=run_id,
        actor="orchestrator",
        action="run.started",
    )

    # Load steps from Postgres
    async with get_session() as session:
        result = await session.execute(
            select(Step).where(Step.run_id == uuid.UUID(run_id)).order_by(Step.seq)
        )
        steps = list(result.scalars().all())

    accumulated_outputs: dict[str, dict] = {}

    for step in steps:
        step_id = str(step.id)

        # Skip already completed steps (recovery scenario)
        if step.status in (StepStatus.COMPLETED, StepStatus.SKIPPED):
            if step.output:
                accumulated_outputs[step.name] = step.output
            continue

        logger.info(
            "Executing step %d/%d: %s (tool=%s) for run %s",
            step.seq + 1, len(steps), step.name, step.tool_name, run_id,
        )

        # Evaluate OPA policy for this specific step
        try:
            step_decision = await evaluate_policy(
                actor=initiated_by,
                action=step.tool_name,
                resource={
                    "run_id": run_id,
                    "step_name": step.name,
                    "params": {**params, **step.input_params, "prior_outputs": accumulated_outputs},
                },
                correlation_id=correlation_id,
                run_id=run_id,
                step_id=step_id,
            )
        except PolicyDenied as exc:
            await _fail_step(step_id, run_id, correlation_id, f"Policy denied: {exc.reasons}")
            await _update_run_status(run_id, "failed", correlation_id, error=f"Step {step.name} denied by policy")
            return
        except ApprovalRequired as exc:
            # Create approval request and pause
            async with get_session() as session:
                approval = Approval(
                    run_id=uuid.UUID(run_id),
                    step_id=step.id,
                    reason=f"Step {step.name} requires approval: {exc.reasons}",
                    correlation_id=uuid.UUID(correlation_id),
                )
                session.add(approval)

                s = await session.execute(
                    select(Step).where(Step.id == step.id).with_for_update()
                )
                s_obj = s.scalar_one()
                s_obj.status = StepStatus.AWAITING_APPROVAL
                await session.flush()

            await bus.publish(BusMessage(
                subject=SUBJECT_APPROVAL_REQUIRED,
                correlation_id=correlation_id,
                run_id=run_id,
                step_id=step_id,
                payload={"step_name": step.name, "reasons": exc.reasons},
            ))
            await _update_run_status(run_id, "awaiting_approval", correlation_id)
            # The run will resume when approval comes via _handle_run_approved
            return

        # Emit step intent to NATS for tool-runner
        # Include the policy_decision_id – tool-runner MUST verify this exists
        merged_params = {**step.input_params, "prior_outputs": accumulated_outputs}
        for k, v in params.items():
            merged_params.setdefault(k, v)

        await bus.publish(BusMessage(
            subject=SUBJECT_STEP_INTENT,
            correlation_id=correlation_id,
            run_id=run_id,
            step_id=step_id,
            payload={
                "tool_name": step.tool_name,
                "step_name": step.name,
                "params": merged_params,
                "policy_decision_id": str(step_decision.id),
                "initiated_by": initiated_by,
            },
        ))

        # Mark step as running
        async with get_session() as session:
            s = await session.execute(
                select(Step).where(Step.id == step.id).with_for_update()
            )
            s_obj = s.scalar_one()
            s_obj.status = StepStatus.RUNNING
            s_obj.started_at = datetime.now(timezone.utc)
            await session.flush()

        # Wait for result from tool-runner
        event = asyncio.Event()
        _step_waiters[step_id] = event
        try:
            await asyncio.wait_for(event.wait(), timeout=300)  # 5 min timeout
        except asyncio.TimeoutError:
            await _fail_step(step_id, run_id, correlation_id, "Step timed out after 300s")
            await _update_run_status(run_id, "failed", correlation_id, error=f"Step {step.name} timed out")
            return
        finally:
            _step_waiters.pop(step_id, None)

        result_payload = _step_results.pop(step_id, {})

        if result_payload.get("status") == "failed":
            await _fail_step(step_id, run_id, correlation_id, result_payload.get("error", "Unknown error"))
            await _update_run_status(run_id, "failed", correlation_id, error=f"Step {step.name} failed")
            return

        # Mark step completed
        async with get_session() as session:
            s = await session.execute(
                select(Step).where(Step.id == step.id).with_for_update()
            )
            s_obj = s.scalar_one()
            s_obj.status = StepStatus.COMPLETED
            s_obj.output = result_payload.get("output", {})
            s_obj.completed_at = datetime.now(timezone.utc)
            await session.flush()

        accumulated_outputs[step.name] = result_payload.get("output", {})

        await append_audit(
            correlation_id=correlation_id,
            run_id=run_id,
            step_id=step_id,
            actor="orchestrator",
            action="step.completed",
            tool=step.tool_name,
            detail={"output_keys": list(result_payload.get("output", {}).keys())},
        )

    # All steps done
    await _update_run_status(
        run_id, "completed", correlation_id,
        result=accumulated_outputs,
    )
    await append_audit(
        correlation_id=correlation_id,
        run_id=run_id,
        actor="orchestrator",
        action="run.completed",
    )
    logger.info("Run %s completed successfully", run_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _update_run_status(
    run_id: str, status: str, correlation_id: str,
    error: str | None = None, result: dict | None = None,
) -> None:
    """Update run in Postgres AND publish status update to NATS."""
    async with get_session() as session:
        r = await session.execute(
            select(Run).where(Run.id == uuid.UUID(run_id)).with_for_update()
        )
        run = r.scalar_one_or_none()
        if run:
            run.status = RunStatus(status)
            if error:
                run.error = error
            if result:
                run.result = result
            run.updated_at = datetime.now(timezone.utc)
            await session.flush()

    await bus.publish(BusMessage(
        subject=SUBJECT_RUN_STATUS,
        correlation_id=correlation_id,
        run_id=run_id,
        payload={"status": status, "error": error, "result": result},
    ))


async def _fail_step(step_id: str, run_id: str, correlation_id: str, error: str) -> None:
    async with get_session() as session:
        s = await session.execute(
            select(Step).where(Step.id == uuid.UUID(step_id)).with_for_update()
        )
        step = s.scalar_one_or_none()
        if step:
            step.status = StepStatus.FAILED
            step.error = error
            step.completed_at = datetime.now(timezone.utc)
            await session.flush()

    await append_audit(
        correlation_id=correlation_id,
        run_id=run_id,
        step_id=step_id,
        actor="orchestrator",
        action="step.failed",
        detail={"error": error},
    )


async def _recover_incomplete_runs() -> None:
    """On startup, find any runs stuck in 'running' and re-drive them."""
    await asyncio.sleep(2)  # Wait for NATS subscriptions to be ready
    async with get_session() as session:
        result = await session.execute(
            select(Run).where(Run.status == RunStatus.RUNNING)
        )
        stuck_runs = result.scalars().all()

    for run in stuck_runs:
        logger.warning("Recovering stuck run: %s", run.id)
        # Re-load workflow to get step definitions
        async with get_session() as session:
            from msclaw.shared.db import Workflow
            wf_result = await session.execute(
                select(Workflow).where(Workflow.id == run.workflow_id)
            )
            wf = wf_result.scalar_one_or_none()
            if wf:
                asyncio.create_task(_execute_run(
                    run_id=str(run.id),
                    correlation_id=str(run.correlation_id),
                    steps_def=wf.steps_definition,
                    params=run.input_params or {},
                    initiated_by=run.initiated_by,
                    policy_decision_id=str(run.policy_decision_id) if run.policy_decision_id else None,
                ))
