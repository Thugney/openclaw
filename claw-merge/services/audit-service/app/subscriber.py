"""NATS subscriber for audit events."""

from __future__ import annotations

import logging
from typing import Any

from msclaw_shared.bus import MessageBus, SUBJECTS
from msclaw_shared.models.audit import AuditEntry
from app.db import AuditDB

logger = logging.getLogger("msclaw.audit.subscriber")


class AuditSubscriber:
    """Subscribes to audit events on NATS and appends to the ledger."""

    def __init__(self, db: AuditDB, nats_url: str):
        self._db = db
        self._bus = MessageBus(url=nats_url)

    async def start(self) -> None:
        await self._bus.connect()
        await self._bus.subscribe(
            SUBJECTS["audit_append"],
            handler=self._handle_audit_entry,
            durable="audit-service",
            queue="audit-workers",
        )
        logger.info("Audit subscriber started")

    async def stop(self) -> None:
        await self._bus.disconnect()

    async def _handle_audit_entry(self, data: dict[str, Any]) -> None:
        try:
            entry = AuditEntry.model_validate(data)
            await self._db.append(entry)
        except Exception:
            logger.exception("Failed to process audit entry")
            raise
