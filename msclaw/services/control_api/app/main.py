"""MSClaw Control API.

The control plane for MSClaw. Handles:
- Workflow submission and status
- Approval queue management
- Audit trail queries
- RBAC enforcement at the API boundary
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import approvals, audit, health, workflows

logger = logging.getLogger("msclaw.control-api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup/shutdown."""
    logger.info("MSClaw Control API starting...")
    # TODO: Initialize NATS connection, DB pool
    yield
    logger.info("MSClaw Control API shutting down...")


def create_app() -> FastAPI:
    app = FastAPI(
        title="MSClaw Control API",
        description="Control plane for Microsoft Security Operations agent runtime",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS for UI
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("MSCLAW_CORS_ORIGINS", "http://localhost:3000").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(health.router)
    app.include_router(workflows.router)
    app.include_router(approvals.router)
    app.include_router(audit.router)

    return app


app = create_app()
