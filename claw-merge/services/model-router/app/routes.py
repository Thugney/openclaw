"""Model router HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.router import CompletionRequest, CompletionResponse
from msclaw_shared.errors import ModelRouterError

router = APIRouter(tags=["model"])


class CompletionRequestBody(BaseModel):
    prompt: str
    system: str = ""
    model: str | None = None
    temperature: float = Field(default=0.1, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=1, le=16384)
    payload_metadata: dict[str, Any] = Field(default_factory=dict)


class CompletionResponseBody(BaseModel):
    text: str
    model: str
    provider: str
    usage: dict[str, int] = Field(default_factory=dict)


@router.post("/complete", response_model=CompletionResponseBody)
async def complete(request: Request, body: CompletionRequestBody):
    model_router = request.app.state.model_router
    req = CompletionRequest(
        prompt=body.prompt,
        system=body.system,
        model=body.model,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        payload_metadata=body.payload_metadata,
    )
    try:
        result: CompletionResponse = await model_router.complete(req)
        return CompletionResponseBody(
            text=result.text,
            model=result.model,
            provider=result.provider,
            usage=result.usage,
        )
    except ModelRouterError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/health")
async def health():
    return {"status": "ok", "service": "model-router"}
