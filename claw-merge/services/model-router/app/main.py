"""Model router entrypoint."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.router import ModelRouter
from app.routes import router

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("msclaw.model_router")


@asynccontextmanager
async def lifespan(app: FastAPI):
    model_router = ModelRouter(
        ollama_url=os.getenv("OLLAMA_URL", "http://ollama:11434"),
        default_model=os.getenv("DEFAULT_MODEL", "llama3.2"),
        cloud_fallback_enabled=os.getenv("CLOUD_FALLBACK_ENABLED", "false").lower() == "true",
        opa_url=os.getenv("OPA_URL", "http://opa:8181"),
    )
    app.state.model_router = model_router
    logger.info("Model router started")
    yield
    logger.info("Model router stopped")


app = FastAPI(
    title="MSClaw Model Router",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router, prefix="/api/v1/model")
