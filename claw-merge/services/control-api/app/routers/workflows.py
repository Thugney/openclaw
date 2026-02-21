"""Workflow submission and management routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Query, Header
from pydantic import BaseModel, Field
from ulid import ULID

from msclaw_shared.bus import SUBJECTS
from msclaw_shared.models.common import CorrelationId, IdempotencyKey, new_correlation_id
from msclaw_shared.models.workflow import WorkflowRun, WorkflowStatus

logger = logging.getLogger("msclaw.control_api.workflows")

router = APIRouter()

# Registered workflow names (in production, loaded from registry)
REGISTERED_WORKFLOWS = {
    "contain_device_from_incident",
}


class WorkflowSubmitRequest(BaseModel):
    workflow_name: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    tags: dict[str, str] = Field(default_factory=dict)


class WorkflowSubmitResponse(BaseModel):
    run_id: str
    correlation_id: str
    status: str
    message: str


@router.post("", response_model=WorkflowSubmitResponse, status_code=201)
async def submit_workflow(
    request: Request,
    body: WorkflowSubmitRequest,
    x_actor: str = Header(..., description="Username or service principal"),
):
    """Submit a workflow for execution.

    Requires Idempotency-Key. Re-submitting with the same key returns the original result.
    """
    db = request.app.state.db
    bus = request.app.state.bus

    # Validate workflow name
    if body.workflow_name not in REGISTERED_WORKFLOWS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown workflow: {body.workflow_name}. Available: {sorted(REGISTERED_WORKFLOWS)}",
        )

    # Check idempotency
    existing = await db.check_idempotency(body.idempotency_key)
    if existing:
        logger.info("Idempotent skip for key=%s", body.idempotency_key)
        return WorkflowSubmitResponse(
            run_id=existing["run_id"],
            correlation_id=existing["correlation_id"],
            status="idempotent_skip",
            message="Workflow already submitted with this idempotency key",
        )

    # Create workflow run
    run_id = str(ULID())
    correlation_id = new_correlation_id()

    run = WorkflowRun(
        run_id=run_id,
        correlation_id=correlation_id,
        workflow_name=body.workflow_name,
        status=WorkflowStatus.PENDING,
        idempotency_key=IdempotencyKey(body.idempotency_key),
        submitted_by=x_actor,
        inputs=body.inputs,
        tags=body.tags,
    )

    await db.create_workflow_run(run)
    await db.store_idempotency(
        body.idempotency_key,
        {"run_id": run_id, "correlation_id": correlation_id},
    )

    # Publish to orchestrator
    await bus.publish(SUBJECTS["workflow_submitted"], run)

    logger.info("Workflow submitted: run_id=%s workflow=%s", run_id, body.workflow_name)

    return WorkflowSubmitResponse(
        run_id=run_id,
        correlation_id=correlation_id,
        status="pending",
        message="Workflow submitted successfully",
    )


@router.get("/{run_id}")
async def get_workflow(request: Request, run_id: str):
    db = request.app.state.db
    run = await db.get_workflow_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return run


@router.get("")
async def list_workflows(
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
):
    db = request.app.state.db
    return await db.list_workflow_runs(offset=offset, limit=limit, status=status)
