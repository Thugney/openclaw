"""Audit Service – standalone service that:
  1. Subscribes to all workflow.> subjects on NATS and logs them to audit
  2. Provides a CLI for verifying the hash chain
  3. Ensures every workflow event produces >= 1 audit entry

This is a supplementary audit sink. Primary audit writes happen inline
in each service (control-api, orchestrator, tool-runner), but the audit-service
provides an independent observer that catches any missed events.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from msclaw.shared.audit import append_audit, verify_chain
from msclaw.shared.bus import BusMessage, MessageBus
from msclaw.shared.config import load_config
from msclaw.shared.db import get_session

logger = logging.getLogger("msclaw.audit_service")

bus = MessageBus()


async def start() -> None:
    """Boot the audit service."""
    cfg = load_config()
    await bus.connect(cfg.nats)

    # Subscribe to ALL workflow subjects as an independent audit observer
    await bus.subscribe(
        "workflow.>",
        _handle_any_event,
        durable_name="audit-service-all",
    )

    logger.info("Audit service started – observing all workflow events")


async def shutdown() -> None:
    await bus.close()


async def _handle_any_event(msg: BusMessage) -> None:
    """Log every NATS workflow event to the audit ledger."""
    # Avoid double-logging DLQ entries
    if "dlq" in msg.subject:
        action = "dlq.received"
    else:
        action = f"bus.{msg.subject}"

    await append_audit(
        correlation_id=msg.correlation_id,
        run_id=msg.run_id,
        step_id=msg.step_id,
        actor="audit-service",
        action=action,
        detail={"subject": msg.subject, "payload_keys": list(msg.payload.keys())},
    )


# ---------------------------------------------------------------------------
# CLI: verify chain
# ---------------------------------------------------------------------------

async def cli_verify() -> bool:
    """Verify the audit chain and report results."""
    print("Verifying audit ledger hash chain...")

    from sqlalchemy import select, func
    from msclaw.shared.db import AuditEntry

    async with get_session() as session:
        count_result = await session.execute(select(func.count(AuditEntry.id)))
        total = count_result.scalar()
        print(f"Total audit entries: {total}")

    ok, errors = await verify_chain()

    if ok:
        print(f"PASS: All {total} entries verified – chain intact")
        return True
    else:
        print(f"FAIL: {len(errors)} integrity errors detected:")
        for err in errors:
            print(f"  - {err}")
        return False


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="MSClaw Audit Service")
    parser.add_argument(
        "command",
        choices=["serve", "verify"],
        help="serve: run audit service, verify: check chain integrity",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.command == "verify":
        result = asyncio.run(cli_verify())
        sys.exit(0 if result else 1)
    elif args.command == "serve":
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(start())
            loop.run_forever()
        except KeyboardInterrupt:
            loop.run_until_complete(shutdown())


if __name__ == "__main__":
    main()
