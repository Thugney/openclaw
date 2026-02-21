"""Model routing logic – local-first with policy-gated cloud fallback."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from msclaw_shared.errors import ModelRouterError

logger = logging.getLogger("msclaw.model_router.router")


class CompletionRequest:
    """Structured request for model completion."""

    def __init__(
        self,
        prompt: str,
        system: str = "",
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        payload_metadata: dict[str, Any] | None = None,
    ):
        self.prompt = prompt
        self.system = system
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.payload_metadata = payload_metadata or {}


class CompletionResponse:
    """Structured response from model completion."""

    def __init__(
        self,
        text: str,
        model: str,
        provider: str,
        usage: dict[str, int] | None = None,
    ):
        self.text = text
        self.model = model
        self.provider = provider
        self.usage = usage or {}


class ModelRouter:
    """Routes completion requests to local Ollama first, cloud fallback if needed."""

    def __init__(
        self,
        ollama_url: str = "http://ollama:11434",
        default_model: str = "llama3.2",
        cloud_fallback_enabled: bool = False,
        opa_url: str = "http://opa:8181",
    ):
        self._ollama_url = ollama_url.rstrip("/")
        self._default_model = default_model
        self._cloud_fallback_enabled = cloud_fallback_enabled
        self._opa_url = opa_url.rstrip("/")

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Route a completion request. Tries local first, falls back to cloud if allowed."""
        model = request.model or self._default_model

        # Try local (Ollama) first
        try:
            return await self._complete_ollama(request, model)
        except Exception as local_err:
            logger.warning("Local model failed: %s", local_err)

            if not self._cloud_fallback_enabled:
                raise ModelRouterError(
                    f"Local model failed and cloud fallback is disabled: {local_err}",
                    provider="ollama",
                ) from local_err

            # Check cloud policy before sending to cloud
            cloud_allowed = await self._check_cloud_policy(request)
            if not cloud_allowed:
                raise ModelRouterError(
                    "Local model failed and cloud model blocked by policy (PII detected)",
                    provider="policy",
                ) from local_err

            logger.info("Falling back to cloud model")
            return await self._complete_cloud(request)

    async def _complete_ollama(self, request: CompletionRequest, model: str) -> CompletionResponse:
        """Send completion to local Ollama instance."""
        payload: dict[str, Any] = {
            "model": model,
            "prompt": request.prompt,
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }
        if request.system:
            payload["system"] = request.system

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self._ollama_url}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()

        return CompletionResponse(
            text=data.get("response", ""),
            model=model,
            provider="ollama",
            usage={
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            },
        )

    async def _complete_cloud(self, request: CompletionRequest) -> CompletionResponse:
        """Placeholder for cloud provider completion.

        In production, this would route to Anthropic/OpenAI/Azure OpenAI
        based on configuration. For MVP, this raises an error.
        """
        raise ModelRouterError(
            "Cloud model completion not yet implemented in MVP",
            provider="cloud",
        )

    async def _check_cloud_policy(self, request: CompletionRequest) -> bool:
        """Check OPA policy for whether cloud model usage is allowed."""
        policy_input = {
            "payload": request.payload_metadata,
            "cloud_pii_approved": False,
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{self._opa_url}/v1/data/msclaw/model_policy",
                    json={"input": policy_input},
                )
                resp.raise_for_status()
                result = resp.json().get("result", {})
                return result.get("allow_cloud", False)
        except httpx.HTTPError as exc:
            logger.error("Cloud policy check failed: %s – denying", exc)
            return False
