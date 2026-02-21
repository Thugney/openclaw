"""Workflow submission and management endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class WorkflowSubmitRequest(BaseModel):
    workflow_id: str
    inputs: dict[str, Any]
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()))
    operator_id: str = "operator-default"


class WorkflowSubmitResponse(BaseModel):
    run_id: str
    correlation_id: str
    status: str
    message: str


class WorkflowStatusResponse(BaseModel):
    run_id: str
    workflow_id: str
    status: str
    steps_completed: list[int]
    step_results: dict[str, Any]
    artifacts: list[str]
    created_at: str
    updated_at: str
    error: str | None = None


class WorkflowListItem(BaseModel):
    run_id: str
    workflow_id: str
    status: str
    created_at: str
    operator_id: str


# ---------------------------------------------------------------------------
# In-memory store (replaced by Postgres in production)
# ---------------------------------------------------------------------------

_workflow_runs: dict[str, dict[str, Any]] = {}
_idempotency_store: dict[str, str] = {}  # key -> run_id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=WorkflowSubmitResponse)
async def submit_workflow(request: WorkflowSubmitRequest) -> WorkflowSubmitResponse:
    """Submit a workflow for execution.

    The workflow is validated, then published to the orchestrator
    via the message bus. Returns immediately with a run_id.
    """
    # Idempotency check
    if request.idempotency_key in _idempotency_store:
        existing_run_id = _idempotency_store[request.idempotency_key]
        existing = _workflow_runs.get(existing_run_id)
        if existing:
            return WorkflowSubmitResponse(
                run_id=existing_run_id,
                correlation_id=existing["correlation_id"],
                status=existing["status"],
                message="Duplicate request - returning existing run",
            )

    # Create workflow run
    run_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())

    run = {
        "run_id": run_id,
        "workflow_id": request.workflow_id,
        "status": "pending",
        "inputs": request.inputs,
        "correlation_id": correlation_id,
        "idempotency_key": request.idempotency_key,
        "operator_id": request.operator_id,
        "steps_completed": [],
        "step_results": {},
        "artifacts": [],
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "error": None,
    }

    _workflow_runs[run_id] = run
    _idempotency_store[request.idempotency_key] = run_id

    # TODO: Publish to NATS topic "workflow.submit"
    # await nats_publish("workflow.submit", run)

    return WorkflowSubmitResponse(
        run_id=run_id,
        correlation_id=correlation_id,
        status="pending",
        message="Workflow submitted for execution",
    )


@router.get("/{run_id}", response_model=WorkflowStatusResponse)
async def get_workflow_status(run_id: str) -> WorkflowStatusResponse:
    """Get the current status of a workflow run."""
    run = _workflow_runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Workflow run {run_id} not found")

    return WorkflowStatusResponse(
        run_id=run["run_id"],
        workflow_id=run["workflow_id"],
        status=run["status"],
        steps_completed=run["steps_completed"],
        step_results=run["step_results"],
        artifacts=run["artifacts"],
        created_at=run["created_at"],
        updated_at=run["updated_at"],
        error=run.get("error"),
    )


@router.get("", response_model=list[WorkflowListItem])
async def list_workflows(limit: int = 50, status: str | None = None) -> list[WorkflowListItem]:
    """List recent workflow runs."""
    runs = list(_workflow_runs.values())
    if status:
        runs = [r for r in runs if r["status"] == status]
    runs.sort(key=lambda r: r["created_at"], reverse=True)
    return [
        WorkflowListItem(
            run_id=r["run_id"],
            workflow_id=r["workflow_id"],
            status=r["status"],
            created_at=r["created_at"],
            operator_id=r["operator_id"],
        )
        for r in runs[:limit]
    ]


@router.post("/{run_id}/cancel")
async def cancel_workflow(run_id: str) -> dict[str, str]:
    """Cancel a running workflow."""
    run = _workflow_runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Workflow run {run_id} not found")
    if run["status"] in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel workflow in status '{run['status']}'")

    run["status"] = "cancelled"
    run["updated_at"] = datetime.utcnow().isoformat()
    return {"status": "cancelled", "run_id": run_id}
