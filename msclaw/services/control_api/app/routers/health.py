"""Health check endpoints."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "control-api"}


@router.get("/ready")
async def readiness_check() -> dict[str, str]:
    # TODO: Check NATS, Postgres, OPA connectivity
    return {"status": "ready"}
