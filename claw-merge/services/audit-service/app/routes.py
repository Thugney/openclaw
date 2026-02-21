"""Audit service HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Query

from msclaw_shared.models.audit import AuditEntry

router = APIRouter(tags=["audit"])


@router.get("/entries", response_model=list[AuditEntry])
async def list_entries(
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    action: str | None = Query(None),
):
    db = request.app.state.db
    return await db.list_entries(offset=offset, limit=limit, action=action)


@router.get("/entries/{entry_id}", response_model=AuditEntry)
async def get_entry(request: Request, entry_id: str):
    db = request.app.state.db
    entry = await db.get_by_id(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Audit entry not found")
    return entry


@router.get("/correlation/{correlation_id}", response_model=list[AuditEntry])
async def get_by_correlation(request: Request, correlation_id: str):
    db = request.app.state.db
    return await db.get_by_correlation_id(correlation_id)


@router.get("/verify")
async def verify_chain(request: Request, limit: int = Query(100, ge=1, le=10000)):
    db = request.app.state.db
    valid, message = await db.verify_chain(limit=limit)
    return {"valid": valid, "message": message}
