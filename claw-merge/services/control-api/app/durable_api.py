"""Control API – FastAPI application.

Responsibilities:
  - Accept workflow run requests from UI/CLI
  - Enforce idempotency
  - Evaluate OPA policy (single choke point)
  - Publish workflow.run.requested to NATS
  - Serve approval queue (approve/deny)
  - Consume workflow.step.result + workflow.run.status from NATS
  - Expose run timeline, audit entries, artifacts
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from msclaw_shared.audit import append_audit, get_audit_by_correlation, get_audit_for_run, verify_chain
from msclaw_shared.bus import (
    SUBJECT_RUN_APPROVED,
    SUBJECT_RUN_REQUESTED,
    SUBJECT_RUN_STATUS,
    SUBJECT_STEP_RESULT,
    BusMessage,
    MessageBus,
)
from msclaw_shared.config import load_config
from msclaw_shared.db import (
    Approval,
    ApprovalStatus,
    Run,
    RunStatus,
    Step,
    Workflow,
    get_session,
)
from msclaw_shared.idempotency import IdempotencyResult, check_and_reserve, mark_completed
from msclaw_shared.policy import ApprovalRequired, PolicyDenied, evaluate_policy

logger = logging.getLogger("msclaw.control_api")

bus = MessageBus()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    await bus.connect(cfg.nats)

    # Subscribe to status updates and step results
    await bus.subscribe(
        SUBJECT_RUN_STATUS,
        _handle_run_status,
        durable_name="control-api-run-status",
    )
    await bus.subscribe(
        SUBJECT_STEP_RESULT,
        _handle_step_result,
        durable_name="control-api-step-result",
    )
    logger.info("Control API started on port %d", cfg.control_api_port)
    yield
    await bus.close()


app = FastAPI(title="MSClaw Control API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

class WorkflowCreate(BaseModel):
    name: str
    description: str = ""
    steps: list[dict[str, Any]]


class RunRequest(BaseModel):
    workflow_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    initiated_by: str = "api_user"


class ApprovalAction(BaseModel):
    decision: str  # "approved" or "denied"
    decided_by: str


# ---------------------------------------------------------------------------
# Workflow CRUD
# ---------------------------------------------------------------------------

@app.post("/api/v1/workflows", status_code=201)
async def create_workflow(body: WorkflowCreate):
    async with get_session() as session:
        wf = Workflow(
            name=body.name,
            description=body.description,
            steps_definition=body.steps,
        )
        session.add(wf)
        await session.flush()
        return {"id": str(wf.id), "name": wf.name}


@app.get("/api/v1/workflows")
async def list_workflows():
    from sqlalchemy import select
    async with get_session() as session:
        result = await session.execute(select(Workflow).order_by(Workflow.created_at.desc()))
        workflows = result.scalars().all()
        return [
            {
                "id": str(w.id),
                "name": w.name,
                "description": w.description,
                "steps": w.steps_definition,
                "created_at": w.created_at.isoformat() if w.created_at else None,
            }
            for w in workflows
        ]


@app.get("/api/v1/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    from sqlalchemy import select
    async with get_session() as session:
        result = await session.execute(
            select(Workflow).where(Workflow.id == uuid.UUID(workflow_id))
        )
        wf = result.scalar_one_or_none()
        if not wf:
            raise HTTPException(404, "Workflow not found")
        return {
            "id": str(wf.id),
            "name": wf.name,
            "description": wf.description,
            "steps": wf.steps_definition,
        }


# ---------------------------------------------------------------------------
# Run submission (idempotent, policy-gated)
# ---------------------------------------------------------------------------

@app.post("/api/v1/runs", status_code=201)
async def submit_run(
    body: RunRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    correlation_id = uuid.uuid4()

    # 1. Idempotency check
    if idempotency_key:
        idem_result: IdempotencyResult = await check_and_reserve(
            key=idempotency_key,
            action="submit_run",
            params={"workflow_id": body.workflow_id, **body.params},
        )
        if idem_result.is_duplicate:
            return {
                "status": "duplicate",
                "prior_result": idem_result.prior_result,
                "prior_status": idem_result.prior_status,
            }
        if idem_result.is_conflict:
            raise HTTPException(
                409,
                "Idempotency key conflict: same key with different payload",
            )

    # 2. Verify workflow exists
    from sqlalchemy import select
    async with get_session() as session:
        result = await session.execute(
            select(Workflow).where(Workflow.id == uuid.UUID(body.workflow_id))
        )
        wf = result.scalar_one_or_none()
        if not wf:
            raise HTTPException(404, "Workflow not found")

    # 3. OPA policy gate
    try:
        policy_decision = await evaluate_policy(
            actor=body.initiated_by,
            action="run_workflow",
            resource={
                "workflow_id": body.workflow_id,
                "workflow_name": wf.name,
                "params": body.params,
            },
            correlation_id=correlation_id,
        )
        requires_approval = False
    except PolicyDenied as exc:
        await append_audit(
            correlation_id=correlation_id,
            actor=body.initiated_by,
            action="run.denied",
            detail={"reasons": exc.reasons},
            policy_decision="deny",
        )
        raise HTTPException(403, f"Policy denied: {exc.reasons}")
    except ApprovalRequired as exc:
        requires_approval = True
        policy_decision_id = exc.decision_id

    # 4. Create Run + Steps in Postgres
    async with get_session() as session:
        run = Run(
            workflow_id=wf.id,
            correlation_id=correlation_id,
            status=RunStatus.AWAITING_APPROVAL if requires_approval else RunStatus.PENDING,
            input_params=body.params,
            initiated_by=body.initiated_by,
            idempotency_key=idempotency_key,
            policy_decision_id=policy_decision.id if not requires_approval else policy_decision_id,
        )
        session.add(run)
        await session.flush()

        for i, step_def in enumerate(wf.steps_definition):
            step = Step(
                run_id=run.id,
                seq=i,
                name=step_def.get("name", f"step_{i}"),
                tool_name=step_def.get("tool", "unknown"),
                input_params=step_def.get("params", {}),
            )
            session.add(step)
        await session.flush()

        if requires_approval:
            approval = Approval(
                run_id=run.id,
                reason=f"Policy requires approval: {exc.reasons}",
                correlation_id=correlation_id,
            )
            session.add(approval)
            await session.flush()

            await append_audit(
                correlation_id=correlation_id,
                run_id=run.id,
                actor=body.initiated_by,
                action="run.awaiting_approval",
                detail={"reasons": exc.reasons},
                policy_decision="require_approval",
                session=session,
            )

            return {
                "id": str(run.id),
                "correlation_id": str(correlation_id),
                "status": "awaiting_approval",
                "approval_id": str(approval.id),
            }

        await append_audit(
            correlation_id=correlation_id,
            run_id=run.id,
            actor=body.initiated_by,
            action="run.submitted",
            policy_decision="allow",
            session=session,
        )

    # 5. Publish to NATS
    await bus.publish(BusMessage(
        subject=SUBJECT_RUN_REQUESTED,
        correlation_id=str(correlation_id),
        run_id=str(run.id),
        payload={
            "workflow_id": str(wf.id),
            "workflow_name": wf.name,
            "run_id": str(run.id),
            "params": body.params,
            "initiated_by": body.initiated_by,
            "policy_decision_id": str(policy_decision.id),
            "steps": wf.steps_definition,
        },
    ))

    if idempotency_key:
        await mark_completed(idempotency_key, {"run_id": str(run.id)})

    return {
        "id": str(run.id),
        "correlation_id": str(correlation_id),
        "status": "pending",
    }


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------

@app.get("/api/v1/approvals")
async def list_approvals(status: str = Query("pending")):
    from sqlalchemy import select
    async with get_session() as session:
        q = select(Approval).order_by(Approval.requested_at.desc())
        if status != "all":
            q = q.where(Approval.status == ApprovalStatus(status))
        result = await session.execute(q)
        approvals = result.scalars().all()
        return [
            {
                "id": str(a.id),
                "run_id": str(a.run_id),
                "step_id": str(a.step_id) if a.step_id else None,
                "reason": a.reason,
                "status": a.status.value if hasattr(a.status, 'value') else a.status,
                "requested_at": a.requested_at.isoformat() if a.requested_at else None,
                "decided_at": a.decided_at.isoformat() if a.decided_at else None,
                "decided_by": a.decided_by,
                "correlation_id": str(a.correlation_id),
            }
            for a in approvals
        ]


@app.post("/api/v1/approvals/{approval_id}")
async def decide_approval(approval_id: str, body: ApprovalAction):
    from sqlalchemy import select
    async with get_session() as session:
        result = await session.execute(
            select(Approval).where(Approval.id == uuid.UUID(approval_id)).with_for_update()
        )
        approval = result.scalar_one_or_none()
        if not approval:
            raise HTTPException(404, "Approval not found")
        if approval.status != ApprovalStatus.PENDING:
            raise HTTPException(409, f"Approval already {approval.status}")

        approval.status = ApprovalStatus(body.decision)
        approval.decided_at = datetime.now(timezone.utc)
        approval.decided_by = body.decided_by
        await session.flush()

        # Update run status
        run_result = await session.execute(
            select(Run).where(Run.id == approval.run_id).with_for_update()
        )
        run = run_result.scalar_one()

        if body.decision == "approved":
            run.status = RunStatus.APPROVED
            await session.flush()

            await append_audit(
                correlation_id=approval.correlation_id,
                run_id=approval.run_id,
                actor=body.decided_by,
                action="run.approved",
                approval_chain=[{"approver": body.decided_by, "at": datetime.now(timezone.utc).isoformat()}],
                session=session,
            )

            # Publish approval to NATS so orchestrator can proceed
            # Load workflow to get step definitions
            wf_result = await session.execute(
                select(Workflow).where(Workflow.id == run.workflow_id)
            )
            wf = wf_result.scalar_one()

            await bus.publish(BusMessage(
                subject=SUBJECT_RUN_APPROVED,
                correlation_id=str(approval.correlation_id),
                run_id=str(run.id),
                payload={
                    "workflow_id": str(wf.id),
                    "workflow_name": wf.name,
                    "run_id": str(run.id),
                    "params": run.input_params,
                    "initiated_by": run.initiated_by,
                    "policy_decision_id": str(run.policy_decision_id) if run.policy_decision_id else None,
                    "steps": wf.steps_definition,
                    "approved_by": body.decided_by,
                },
            ))
        else:
            run.status = RunStatus.REJECTED
            await session.flush()

            await append_audit(
                correlation_id=approval.correlation_id,
                run_id=approval.run_id,
                actor=body.decided_by,
                action="run.rejected",
                session=session,
            )

    return {"status": body.decision}


# ---------------------------------------------------------------------------
# Run queries
# ---------------------------------------------------------------------------

@app.get("/api/v1/runs")
async def list_runs(limit: int = 50):
    from sqlalchemy import select
    async with get_session() as session:
        result = await session.execute(
            select(Run).order_by(Run.created_at.desc()).limit(limit)
        )
        runs = result.scalars().all()
        return [_run_to_dict(r) for r in runs]


@app.get("/api/v1/runs/{run_id}")
async def get_run(run_id: str):
    from sqlalchemy import select
    async with get_session() as session:
        result = await session.execute(
            select(Run).where(Run.id == uuid.UUID(run_id))
        )
        run = result.scalar_one_or_none()
        if not run:
            raise HTTPException(404, "Run not found")
        return _run_to_dict(run, include_steps=True)


@app.get("/api/v1/runs/{run_id}/timeline")
async def get_run_timeline(run_id: str):
    """Step-by-step timeline with status and audit links."""
    from sqlalchemy import select
    async with get_session() as session:
        run_result = await session.execute(
            select(Run).where(Run.id == uuid.UUID(run_id))
        )
        run = run_result.scalar_one_or_none()
        if not run:
            raise HTTPException(404, "Run not found")

        steps_result = await session.execute(
            select(Step).where(Step.run_id == run.id).order_by(Step.seq)
        )
        steps = steps_result.scalars().all()

        audit_entries = await get_audit_for_run(run_id, session=session)

        return {
            "run_id": str(run.id),
            "correlation_id": str(run.correlation_id),
            "status": run.status.value if hasattr(run.status, 'value') else run.status,
            "steps": [
                {
                    "id": str(s.id),
                    "seq": s.seq,
                    "name": s.name,
                    "tool": s.tool_name,
                    "status": s.status.value if hasattr(s.status, 'value') else s.status,
                    "started_at": s.started_at.isoformat() if s.started_at else None,
                    "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                    "output": s.output,
                    "error": s.error,
                }
                for s in steps
            ],
            "audit": [
                {
                    "id": e.id,
                    "action": e.action,
                    "actor": e.actor,
                    "policy_decision": e.policy_decision,
                    "tool": e.tool,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                    "entry_hash": e.entry_hash[:12],
                }
                for e in audit_entries
            ],
        }


# ---------------------------------------------------------------------------
# Audit endpoints
# ---------------------------------------------------------------------------

@app.get("/api/v1/audit")
async def list_audit(
    correlation_id: str | None = None,
    run_id: str | None = None,
    limit: int = 100,
):
    if correlation_id:
        entries = await get_audit_by_correlation(correlation_id)
    elif run_id:
        entries = await get_audit_for_run(run_id)
    else:
        from sqlalchemy import select
        from msclaw_shared.db import AuditEntry
        async with get_session() as session:
            result = await session.execute(
                select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit)
            )
            entries = result.scalars().all()

    return [
        {
            "id": e.id,
            "correlation_id": str(e.correlation_id),
            "run_id": str(e.run_id) if e.run_id else None,
            "step_id": str(e.step_id) if e.step_id else None,
            "actor": e.actor,
            "action": e.action,
            "detail": e.detail,
            "policy_decision": e.policy_decision,
            "approval_chain": e.approval_chain,
            "tool": e.tool,
            "adapter_mode": e.adapter_mode,
            "prev_hash": e.prev_hash,
            "entry_hash": e.entry_hash,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]


@app.post("/api/v1/audit/verify")
async def verify_audit_chain():
    ok, errors = await verify_chain()
    return {"valid": ok, "errors": errors}


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

@app.get("/api/v1/artifacts")
async def list_artifacts(prefix: str = ""):
    from msclaw_shared.artifacts import list_artifacts as _list
    try:
        return _list(prefix=prefix)
    except Exception as e:
        raise HTTPException(500, f"Artifact listing failed: {e}")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "control-api"}


# ---------------------------------------------------------------------------
# NATS handlers
# ---------------------------------------------------------------------------

async def _handle_run_status(msg: BusMessage) -> None:
    """Update run status from orchestrator."""
    from sqlalchemy import select
    run_id = msg.run_id
    new_status = msg.payload.get("status")
    if not run_id or not new_status:
        return

    async with get_session() as session:
        result = await session.execute(
            select(Run).where(Run.id == uuid.UUID(run_id)).with_for_update()
        )
        run = result.scalar_one_or_none()
        if run:
            run.status = RunStatus(new_status)
            if new_status == "completed":
                run.result = msg.payload.get("result")
            elif new_status == "failed":
                run.error = msg.payload.get("error")
            await session.flush()

    logger.info("Run %s status → %s", run_id, new_status)


async def _handle_step_result(msg: BusMessage) -> None:
    """Update step status from tool-runner results."""
    from sqlalchemy import select
    step_id = msg.step_id
    if not step_id:
        return

    async with get_session() as session:
        result = await session.execute(
            select(Step).where(Step.id == uuid.UUID(step_id)).with_for_update()
        )
        step = result.scalar_one_or_none()
        if step:
            status = msg.payload.get("status", "completed")
            step.status = status
            step.output = msg.payload.get("output")
            step.error = msg.payload.get("error")
            step.completed_at = datetime.now(timezone.utc)
            await session.flush()

    logger.info("Step %s result received: %s", step_id, msg.payload.get("status"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_to_dict(run: Run, include_steps: bool = False) -> dict:
    d = {
        "id": str(run.id),
        "workflow_id": str(run.workflow_id),
        "correlation_id": str(run.correlation_id),
        "status": run.status.value if hasattr(run.status, 'value') else run.status,
        "input_params": run.input_params,
        "result": run.result,
        "error": run.error,
        "initiated_by": run.initiated_by,
        "idempotency_key": run.idempotency_key,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }
    if include_steps and run.steps:
        d["steps"] = [
            {
                "id": str(s.id),
                "seq": s.seq,
                "name": s.name,
                "tool": s.tool_name,
                "status": s.status.value if hasattr(s.status, 'value') else s.status,
                "output": s.output,
                "error": s.error,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
            }
            for s in run.steps
        ]
    return d
