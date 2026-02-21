"""Control API entrypoint."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import ControlDB
from app.routers import workflows, approvals, health
from msclaw_shared.bus import MessageBus

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("msclaw.control_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = ControlDB(dsn=os.getenv(
        "DATABASE_URL",
        "postgresql://msclaw:msclaw-dev-only@postgres:5432/msclaw",
    ))
    await db.connect()
    await db.ensure_schema()
    app.state.db = db

    bus = MessageBus(url=os.getenv("NATS_URL", "nats://nats:4222"))
    await bus.connect()
    app.state.bus = bus

    app.state.dev_mode = os.getenv("DEV_MODE", "true").lower() == "true"

    logger.info("Control API started (dev_mode=%s)", app.state.dev_mode)
    yield

    await bus.disconnect()
    await db.disconnect()
    logger.info("Control API stopped")


app = FastAPI(
    title="MSClaw Control API",
    version="0.1.0",
    description="MSClaw agent runtime control plane – workflow submission, approvals, and RBAC",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["health"])
app.include_router(workflows.router, prefix="/api/v1/workflows", tags=["workflows"])
app.include_router(approvals.router, prefix="/api/v1/approvals", tags=["approvals"])
