"""Orchestrator entrypoint."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.engine.workflow_engine import WorkflowEngine
from app.subscriber import OrchestratorSubscriber

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("msclaw.orchestrator")


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = WorkflowEngine(
        nats_url=os.getenv("NATS_URL", "nats://nats:4222"),
        control_api_url=os.getenv("CONTROL_API_URL", "http://control-api:8000"),
        tool_runner_url=os.getenv("TOOL_RUNNER_URL", "http://tool-runner:8003"),
        model_router_url=os.getenv("MODEL_ROUTER_URL", "http://model-router:8002"),
        opa_url=os.getenv("OPA_URL", "http://opa:8181"),
        dev_mode=os.getenv("DEV_MODE", "true").lower() == "true",
    )
    await engine.start()
    app.state.engine = engine

    subscriber = OrchestratorSubscriber(engine=engine)
    await subscriber.start()
    app.state.subscriber = subscriber

    logger.info("Orchestrator started")
    yield

    await subscriber.stop()
    await engine.stop()
    logger.info("Orchestrator stopped")


app = FastAPI(
    title="MSClaw Orchestrator",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "orchestrator"}
