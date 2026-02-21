"""Tool runner entrypoint."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.executor import ToolExecutor
from app.routes import router

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("msclaw.tool_runner")


@asynccontextmanager
async def lifespan(app: FastAPI):
    executor = ToolExecutor(
        nats_url=os.getenv("NATS_URL", "nats://nats:4222"),
        minio_endpoint=os.getenv("MINIO_ENDPOINT", "minio:9000"),
        minio_access_key=os.getenv("MINIO_ACCESS_KEY", "msclaw"),
        minio_secret_key=os.getenv("MINIO_SECRET_KEY", "msclaw-dev-only"),
        minio_bucket=os.getenv("MINIO_BUCKET", "msclaw-artifacts"),
        dev_mode=os.getenv("DEV_MODE", "true").lower() == "true",
    )
    await executor.start()
    app.state.executor = executor
    logger.info("Tool runner started (dev_mode=%s)", executor._dev_mode)
    yield
    await executor.stop()
    logger.info("Tool runner stopped")


app = FastAPI(
    title="MSClaw Tool Runner",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router, prefix="/api/v1")
