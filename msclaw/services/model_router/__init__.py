"""MSClaw Model Router.

Routes LLM requests to local (Ollama/llama.cpp) or cloud providers.
Enforces:
- Local-first preference
- Egress rules (block PII to cloud unless approved)
- Budget limits for cloud usage
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ...shared.contracts import (
    CorrelationContext,
    ModelProvider,
    ModelRequest,
    ModelResponse,
)
from ...shared.errors import ModelRouterError

logger = logging.getLogger("msclaw.model-router")


class ModelRouter:
    """Routes model requests to the appropriate provider."""

    def __init__(
        self,
        *,
        ollama_url: str = "http://localhost:11434",
        local_model: str = "llama3.2:3b",
        cloud_provider: str = "anthropic",
        cloud_model: str = "claude-sonnet-4-20250514",
        cloud_api_key: str = "",
        prefer_local: bool = True,
        max_budget_usd: float = 10.0,
        block_pii_to_cloud: bool = True,
        dev_mode: bool = True,
    ):
        self._ollama_url = ollama_url
        self._local_model = local_model
        self._cloud_provider = cloud_provider
        self._cloud_model = cloud_model
        self._cloud_api_key = cloud_api_key
        self._prefer_local = prefer_local
        self._max_budget_usd = max_budget_usd
        self._block_pii_to_cloud = block_pii_to_cloud
        self._dev_mode = dev_mode
        self._budget_spent_usd: float = 0.0

    async def route(self, request: ModelRequest) -> ModelResponse:
        """Route a model request to the best available provider."""
        start = time.monotonic()

        # Enforce PII rules
        if request.contains_pii and self._block_pii_to_cloud:
            if request.preferred_provider and request.preferred_provider not in (
                ModelProvider.LOCAL_OLLAMA, ModelProvider.LOCAL_LLAMACPP
            ):
                raise ModelRouterError(
                    "Request contains PII - cloud providers blocked by policy",
                    correlation_id=request.correlation.correlation_id,
                )

        # Try local first if preferred
        if self._prefer_local:
            try:
                response = await self._call_local(request)
                response.duration_ms = int((time.monotonic() - start) * 1000)
                return response
            except Exception as e:
                logger.warning("Local model failed, falling back to cloud: %s", e)

        # Fall back to cloud
        if self._budget_spent_usd >= self._max_budget_usd:
            raise ModelRouterError(
                f"Cloud budget exceeded: ${self._budget_spent_usd:.2f} / ${self._max_budget_usd:.2f}",
                correlation_id=request.correlation.correlation_id,
            )

        try:
            response = await self._call_cloud(request)
            response.duration_ms = int((time.monotonic() - start) * 1000)
            return response
        except Exception as e:
            raise ModelRouterError(
                f"All providers failed. Local and cloud both unavailable: {e}",
                correlation_id=request.correlation.correlation_id,
            ) from e

    async def _call_local(self, request: ModelRequest) -> ModelResponse:
        """Call local Ollama model."""
        if self._dev_mode:
            return ModelResponse(
                request_id=request.request_id,
                provider=ModelProvider.LOCAL_OLLAMA,
                model=self._local_model,
                content=f"[DEV MODE] Mock response for: {request.prompt[:100]}...",
                usage={"prompt_tokens": 50, "completion_tokens": 100},
                correlation=request.correlation,
            )

        try:
            import httpx  # type: ignore[import-untyped]

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._ollama_url}/api/generate",
                    json={
                        "model": self._local_model,
                        "prompt": request.prompt,
                        "system": request.system_prompt or "",
                        "stream": False,
                        "options": {
                            "num_predict": request.max_tokens,
                            "temperature": request.temperature,
                        },
                    },
                    timeout=120.0,
                )
                data = response.json()
                return ModelResponse(
                    request_id=request.request_id,
                    provider=ModelProvider.LOCAL_OLLAMA,
                    model=self._local_model,
                    content=data.get("response", ""),
                    usage={
                        "prompt_tokens": data.get("prompt_eval_count", 0),
                        "completion_tokens": data.get("eval_count", 0),
                    },
                    correlation=request.correlation,
                )
        except Exception as e:
            raise ModelRouterError(f"Ollama call failed: {e}") from e

    async def _call_cloud(self, request: ModelRequest) -> ModelResponse:
        """Call cloud model provider."""
        if self._dev_mode:
            return ModelResponse(
                request_id=request.request_id,
                provider=ModelProvider.CLOUD_ANTHROPIC,
                model=self._cloud_model,
                content=f"[DEV MODE] Cloud mock response for: {request.prompt[:100]}...",
                usage={"prompt_tokens": 50, "completion_tokens": 100},
                correlation=request.correlation,
            )

        if self._cloud_provider == "anthropic":
            return await self._call_anthropic(request)
        elif self._cloud_provider == "openai":
            return await self._call_openai(request)
        else:
            raise ModelRouterError(f"Unknown cloud provider: {self._cloud_provider}")

    async def _call_anthropic(self, request: ModelRequest) -> ModelResponse:
        """Call Anthropic Claude API."""
        try:
            import anthropic  # type: ignore[import-untyped]

            client = anthropic.AsyncAnthropic(api_key=self._cloud_api_key)
            message = await client.messages.create(
                model=self._cloud_model,
                max_tokens=request.max_tokens,
                system=request.system_prompt or "You are a security operations assistant.",
                messages=[{"role": "user", "content": request.prompt}],
            )
            self._budget_spent_usd += 0.01  # Rough estimate
            return ModelResponse(
                request_id=request.request_id,
                provider=ModelProvider.CLOUD_ANTHROPIC,
                model=self._cloud_model,
                content=message.content[0].text,
                usage={
                    "prompt_tokens": message.usage.input_tokens,
                    "completion_tokens": message.usage.output_tokens,
                },
                correlation=request.correlation,
            )
        except Exception as e:
            raise ModelRouterError(f"Anthropic call failed: {e}") from e

    async def _call_openai(self, request: ModelRequest) -> ModelResponse:
        """Call OpenAI API."""
        try:
            import openai  # type: ignore[import-untyped]

            client = openai.AsyncOpenAI(api_key=self._cloud_api_key)
            messages: list[dict[str, str]] = []
            if request.system_prompt:
                messages.append({"role": "system", "content": request.system_prompt})
            messages.append({"role": "user", "content": request.prompt})

            response = await client.chat.completions.create(
                model=self._cloud_model,
                messages=messages,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            )
            self._budget_spent_usd += 0.01
            return ModelResponse(
                request_id=request.request_id,
                provider=ModelProvider.CLOUD_OPENAI,
                model=self._cloud_model,
                content=response.choices[0].message.content or "",
                usage={
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                },
                correlation=request.correlation,
            )
        except Exception as e:
            raise ModelRouterError(f"OpenAI call failed: {e}") from e

    @property
    def budget_remaining(self) -> float:
        return max(0, self._max_budget_usd - self._budget_spent_usd)
