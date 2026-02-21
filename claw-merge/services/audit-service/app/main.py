"""Audit service entrypoint."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import AuditDB
from app.routes import router
from app.subscriber import AuditSubscriber

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("msclaw.audit")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = AuditDB(dsn=os.getenv(
        "DATABASE_URL",
        "postgresql://msclaw:msclaw-dev-only@postgres:5432/msclaw",
    ))
    await db.connect()
    await db.ensure_schema()
    app.state.db = db

    subscriber = AuditSubscriber(
        db=db,
        nats_url=os.getenv("NATS_URL", "nats://nats:4222"),
    )
    await subscriber.start()
    app.state.subscriber = subscriber

    logger.info("Audit service started")
    yield

    await subscriber.stop()
    await db.disconnect()
    logger.info("Audit service stopped")


app = FastAPI(
    title="MSClaw Audit Service",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router, prefix="/api/v1/audit")
