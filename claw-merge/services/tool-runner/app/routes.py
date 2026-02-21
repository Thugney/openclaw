"""Tool runner HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from msclaw_shared.models.tool_intent import ToolIntent, ToolResult

router = APIRouter(tags=["tool-runner"])


@router.post("/execute", response_model=ToolResult)
async def execute_tool(request: Request, intent: ToolIntent):
    """Execute a tool intent. Must have already passed policy gate."""
    executor = request.app.state.executor
    return await executor.execute(intent)


@router.get("/tools")
async def list_tools(request: Request):
    """List all registered tools on the allowlist."""
    executor = request.app.state.executor
    tools = []
    for plugin_name, plugin in executor._plugins.items():
        meta = plugin.metadata()
        for action in meta.actions:
            tools.append({
                "plugin": plugin_name,
                "action": action.name,
                "description": action.description,
                "required_permissions": action.required_permissions,
                "idempotency_strategy": action.idempotency_strategy.value,
                "rollback_action": action.rollback_action,
                "requires_approval": action.requires_approval,
            })
    return {"tools": tools}


@router.get("/health")
async def health():
    return {"status": "ok", "service": "tool-runner"}
