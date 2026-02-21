"""NATS message bus – the ONLY cross-service communication channel.

Subjects (v1):
  workflow.run.requested.v1      – control-api → orchestrator
  workflow.run.approved.v1       – control-api → orchestrator (after approval)
  workflow.step.intent.v1        – orchestrator → tool-runner
  workflow.step.result.v1        – tool-runner → orchestrator / control-api
  workflow.run.status.v1         – orchestrator → control-api (status updates)
  workflow.approval.required.v1  – orchestrator → control-api
  workflow.dlq.v1                – dead-letter for failed processing

Every message carries: correlation_id, run_id, step_id (if applicable),
timestamp, version, and a typed payload.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import nats
from nats.aio.client import Client as NatsClient
from nats.js import JetStreamContext

from ..config import NatsConfig, load_config

logger = logging.getLogger("msclaw.bus")

# ---------------------------------------------------------------------------
# Message envelope
# ---------------------------------------------------------------------------

MESSAGE_VERSION = "1"


@dataclass
class BusMessage:
    """Canonical envelope for every NATS message."""

    subject: str
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str | None = None
    step_id: str | None = None
    version: str = MESSAGE_VERSION
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    payload: dict[str, Any] = field(default_factory=dict)

    def encode(self) -> bytes:
        return json.dumps(asdict(self), default=str).encode()

    @classmethod
    def decode(cls, data: bytes) -> "BusMessage":
        d = json.loads(data.decode())
        return cls(**d)


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------

SUBJECT_RUN_REQUESTED = "workflow.run.requested.v1"
SUBJECT_RUN_APPROVED = "workflow.run.approved.v1"
SUBJECT_STEP_INTENT = "workflow.step.intent.v1"
SUBJECT_STEP_RESULT = "workflow.step.result.v1"
SUBJECT_RUN_STATUS = "workflow.run.status.v1"
SUBJECT_APPROVAL_REQUIRED = "workflow.approval.required.v1"
SUBJECT_DLQ = "workflow.dlq.v1"

ALL_SUBJECTS = [
    SUBJECT_RUN_REQUESTED,
    SUBJECT_RUN_APPROVED,
    SUBJECT_STEP_INTENT,
    SUBJECT_STEP_RESULT,
    SUBJECT_RUN_STATUS,
    SUBJECT_APPROVAL_REQUIRED,
    SUBJECT_DLQ,
]

# ---------------------------------------------------------------------------
# JetStream stream config
# ---------------------------------------------------------------------------

STREAM_NAME = "MSCLAW"


async def _ensure_stream(js: JetStreamContext) -> None:
    """Create or update the JetStream stream for MSClaw subjects."""
    from nats.js.api import RetentionPolicy, StorageType, StreamConfig

    cfg = StreamConfig(
        name=STREAM_NAME,
        subjects=["workflow.>"],
        retention=RetentionPolicy.WORK_QUEUE,
        storage=StorageType.FILE,
        max_msgs=-1,
        max_bytes=-1,
        max_age=7 * 24 * 3600 * 1_000_000_000,  # 7 days in nanoseconds
        num_replicas=1,
        duplicate_window=300 * 1_000_000_000,  # 5 min dedup window in ns
    )
    try:
        await js.find_stream_name_by_subject("workflow.>")
        await js.update_stream(cfg)
        logger.info("JetStream stream %s updated", STREAM_NAME)
    except Exception:
        await js.add_stream(cfg)
        logger.info("JetStream stream %s created", STREAM_NAME)


# ---------------------------------------------------------------------------
# Bus wrapper
# ---------------------------------------------------------------------------


class MessageBus:
    """Thin wrapper around a NATS JetStream connection.

    Provides:
      - publish(subject, message) with dedup via Nats-Msg-Id
      - subscribe(subject, handler, durable_name)  for durable consumers
      - request/reply for synchronous RPC
      - automatic dead-letter on handler failure
    """

    def __init__(self) -> None:
        self._nc: NatsClient | None = None
        self._js: JetStreamContext | None = None
        self._subscriptions: list = []

    async def connect(self, cfg: NatsConfig | None = None) -> None:
        if cfg is None:
            cfg = load_config().nats
        self._nc = await nats.connect(
            cfg.url,
            connect_timeout=cfg.connect_timeout,
            max_reconnect_attempts=cfg.max_reconnect_attempts,
            reconnect_time_wait=cfg.reconnect_time_wait,
            error_cb=self._on_error,
            disconnected_cb=self._on_disconnect,
            reconnected_cb=self._on_reconnect,
        )
        self._js = self._nc.jetstream()
        await _ensure_stream(self._js)
        logger.info("NATS connected to %s", cfg.url)

    async def close(self) -> None:
        for sub in self._subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        if self._nc:
            await self._nc.close()
            logger.info("NATS connection closed")

    # -- publish ---------------------------------------------------------------

    async def publish(self, msg: BusMessage) -> None:
        """Publish a message to JetStream with dedup ID."""
        assert self._js, "Bus not connected"
        msg_id = f"{msg.correlation_id}:{msg.subject}:{msg.run_id}:{msg.step_id}"
        ack = await self._js.publish(
            msg.subject,
            msg.encode(),
            headers={"Nats-Msg-Id": msg_id},
        )
        logger.debug(
            "Published %s  corr=%s  seq=%s",
            msg.subject,
            msg.correlation_id,
            ack.seq,
        )

    # -- subscribe (durable) ---------------------------------------------------

    async def subscribe(
        self,
        subject: str,
        handler: Callable[[BusMessage], Awaitable[None]],
        durable_name: str,
        *,
        max_deliver: int = 3,
    ) -> None:
        """Create a durable pull subscription with automatic ack/nak + DLQ."""
        assert self._js, "Bus not connected"

        from nats.js.api import ConsumerConfig, AckPolicy, DeliverPolicy

        consumer_cfg = ConsumerConfig(
            durable_name=durable_name,
            ack_policy=AckPolicy.EXPLICIT,
            deliver_policy=DeliverPolicy.ALL,
            max_deliver=max_deliver,
            filter_subject=subject,
            ack_wait=60,  # seconds
        )

        sub = await self._js.subscribe(
            subject,
            durable=durable_name,
            config=consumer_cfg,
            manual_ack=True,
        )
        self._subscriptions.append(sub)

        async def _process():
            async for raw_msg in sub.messages:
                try:
                    bus_msg = BusMessage.decode(raw_msg.data)
                    await handler(bus_msg)
                    await raw_msg.ack()
                except Exception as exc:
                    logger.exception(
                        "Handler failed for %s corr=%s: %s",
                        subject,
                        getattr(bus_msg, "correlation_id", "?"),
                        exc,
                    )
                    # If max deliveries exhausted, NATS moves to DLQ stream
                    # We also explicitly publish a DLQ entry for visibility
                    metadata = raw_msg.metadata
                    if metadata and metadata.num_delivered >= max_deliver:
                        await self._send_to_dlq(raw_msg.data, str(exc))
                    await raw_msg.nak()

        import asyncio
        asyncio.create_task(_process())
        logger.info("Subscribed to %s (durable=%s)", subject, durable_name)

    # -- request / reply -------------------------------------------------------

    async def request(
        self, subject: str, msg: BusMessage, timeout: float = 10.0
    ) -> BusMessage:
        """Synchronous request/reply over core NATS (not JetStream)."""
        assert self._nc, "Bus not connected"
        resp = await self._nc.request(subject, msg.encode(), timeout=timeout)
        return BusMessage.decode(resp.data)

    # -- DLQ -------------------------------------------------------------------

    async def _send_to_dlq(self, original_data: bytes, error: str) -> None:
        try:
            original = json.loads(original_data.decode())
        except Exception:
            original = {"raw": original_data.decode(errors="replace")}
        dlq_msg = BusMessage(
            subject=SUBJECT_DLQ,
            correlation_id=original.get("correlation_id", str(uuid.uuid4())),
            run_id=original.get("run_id"),
            step_id=original.get("step_id"),
            payload={"original": original, "error": error},
        )
        if self._js:
            await self._js.publish(SUBJECT_DLQ, dlq_msg.encode())
            logger.warning("Sent message to DLQ: corr=%s", dlq_msg.correlation_id)

    # -- callbacks -------------------------------------------------------------

    @staticmethod
    async def _on_error(exc: Exception) -> None:
        logger.error("NATS error: %s", exc)

    @staticmethod
    async def _on_disconnect() -> None:
        logger.warning("NATS disconnected")

    @staticmethod
    async def _on_reconnect() -> None:
        logger.info("NATS reconnected")
