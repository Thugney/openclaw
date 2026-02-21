"""Tool executor – loads plugins, validates allowlist, handles idempotency, stores artifacts."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from miniopy_async import Minio
from ulid import ULID

from msclaw_shared.bus import MessageBus, SUBJECTS
from msclaw_shared.errors import IdempotentSkipError, ToolNotAllowedError
from msclaw_shared.models.tool_intent import ToolIntent, ToolResult, ToolResultStatus

from plugins.sdk import PluginBase, PluginContext

logger = logging.getLogger("msclaw.tool_runner.executor")


class ToolExecutor:
    """Executes tool intents using registered plugins."""

    def __init__(
        self,
        nats_url: str,
        minio_endpoint: str,
        minio_access_key: str,
        minio_secret_key: str,
        minio_bucket: str,
        dev_mode: bool = True,
    ):
        self._bus = MessageBus(url=nats_url)
        self._minio = Minio(
            minio_endpoint,
            access_key=minio_access_key,
            secret_key=minio_secret_key,
            secure=False,
        )
        self._bucket = minio_bucket
        self._dev_mode = dev_mode
        self._plugins: dict[str, PluginBase] = {}
        self._allowlist: set[str] = set()
        self._idempotency_cache: dict[str, ToolResult] = {}

        self._load_plugins()

    def _load_plugins(self) -> None:
        """Load all registered plugins and build the allowlist."""
        from plugins.defender_xdr import DefenderXDRPlugin
        from plugins.intune import IntunePlugin
        from plugins.entra import EntraPlugin

        plugins: list[PluginBase] = [
            DefenderXDRPlugin(dev_mode=self._dev_mode),
            IntunePlugin(dev_mode=self._dev_mode),
            EntraPlugin(dev_mode=self._dev_mode),
        ]

        for plugin in plugins:
            meta = plugin.metadata()
            self._plugins[meta.name] = plugin
            for action in meta.actions:
                fqn = f"{meta.name}.{action.name}"
                self._allowlist.add(fqn)
                logger.info("Registered tool: %s", fqn)

    async def start(self) -> None:
        await self._bus.connect()
        # Ensure MinIO bucket exists
        try:
            exists = await self._minio.bucket_exists(self._bucket)
            if not exists:
                await self._minio.make_bucket(self._bucket)
                logger.info("Created MinIO bucket: %s", self._bucket)
        except Exception as exc:
            logger.warning("MinIO bucket check failed (may not be available): %s", exc)

    async def stop(self) -> None:
        await self._bus.disconnect()

    async def execute(self, intent: ToolIntent) -> ToolResult:
        """Execute a tool intent with full safety checks."""
        fqn = f"{intent.plugin}.{intent.action}"
        start_time = time.monotonic()

        # Check allowlist
        if fqn not in self._allowlist:
            logger.warning("Tool not allowed: %s", fqn)
            return ToolResult(
                intent_id=intent.intent_id,
                correlation_id=intent.correlation_id,
                status=ToolResultStatus.DENIED,
                error=f"Tool {fqn} is not on the allowlist",
            )

        # Check idempotency
        if intent.idempotency_key in self._idempotency_cache:
            cached = self._idempotency_cache[intent.idempotency_key]
            logger.info("Idempotent skip for key=%s", intent.idempotency_key)
            return ToolResult(
                intent_id=intent.intent_id,
                correlation_id=intent.correlation_id,
                status=ToolResultStatus.IDEMPOTENT_SKIP,
                outputs=cached.outputs,
                artifacts=cached.artifacts,
            )

        # Get plugin
        plugin = self._plugins.get(intent.plugin)
        if not plugin:
            return ToolResult(
                intent_id=intent.intent_id,
                correlation_id=intent.correlation_id,
                status=ToolResultStatus.FAILURE,
                error=f"Plugin not found: {intent.plugin}",
            )

        # Build context
        context = PluginContext(
            correlation_id=intent.correlation_id,
            idempotency_key=intent.idempotency_key,
            actor=intent.requested_by,
            dev_mode=self._dev_mode,
        )

        # Execute
        try:
            outputs = await plugin.execute(intent.action, intent.inputs, context)
            duration_ms = int((time.monotonic() - start_time) * 1000)

            # Store artifacts if any
            artifacts: list[str] = []
            artifact_data = outputs.pop("_artifacts", None)
            if artifact_data and isinstance(artifact_data, dict):
                for name, data in artifact_data.items():
                    key = f"{intent.correlation_id}/{intent.intent_id}/{name}"
                    try:
                        import io
                        content = data if isinstance(data, bytes) else json.dumps(data).encode()
                        await self._minio.put_object(
                            self._bucket, key, io.BytesIO(content), len(content),
                        )
                        artifacts.append(key)
                        logger.info("Stored artifact: %s", key)
                    except Exception as exc:
                        logger.warning("Failed to store artifact %s: %s", name, exc)

            result = ToolResult(
                intent_id=intent.intent_id,
                correlation_id=intent.correlation_id,
                status=ToolResultStatus.SUCCESS,
                outputs=outputs,
                duration_ms=duration_ms,
                artifacts=artifacts,
            )

            # Cache for idempotency
            self._idempotency_cache[intent.idempotency_key] = result
            return result

        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.exception("Tool execution failed: %s", fqn)
            return ToolResult(
                intent_id=intent.intent_id,
                correlation_id=intent.correlation_id,
                status=ToolResultStatus.FAILURE,
                error=str(exc),
                duration_ms=duration_ms,
            )
