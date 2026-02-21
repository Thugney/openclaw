"""NATS subscribers for the orchestrator."""

from __future__ import annotations

import logging
from typing import Any

from msclaw_shared.bus import MessageBus, SUBJECTS

logger = logging.getLogger("msclaw.orchestrator.subscriber")


class OrchestratorSubscriber:
    """Subscribes to workflow and approval events."""

    def __init__(self, engine: Any):
        self._engine = engine
        self._bus: MessageBus | None = None

    async def start(self) -> None:
        self._bus = self._engine._bus
        await self._bus.subscribe(
            SUBJECTS["workflow_submitted"],
            handler=self._handle_workflow_submitted,
            durable="orchestrator",
            queue="orchestrator-workers",
        )
        await self._bus.subscribe(
            SUBJECTS["approval_decided"],
            handler=self._handle_approval_decided,
            durable="orchestrator-approvals",
            queue="orchestrator-workers",
        )
        logger.info("Orchestrator subscriber started")

    async def stop(self) -> None:
        pass  # Bus lifecycle managed by engine

    async def _handle_workflow_submitted(self, data: dict[str, Any]) -> None:
        try:
            await self._engine.execute_workflow(data)
        except Exception:
            logger.exception("Failed to execute workflow")
            raise

    async def _handle_approval_decided(self, data: dict[str, Any]) -> None:
        try:
            await self._engine.handle_approval_decision(data)
        except Exception:
            logger.exception("Failed to handle approval decision")
            raise
