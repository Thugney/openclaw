"""Common value types used across MSClaw."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Annotated, NewType

from pydantic import BaseModel, Field
from ulid import ULID


IdempotencyKey = NewType("IdempotencyKey", str)
CorrelationId = NewType("CorrelationId", str)


def new_correlation_id() -> CorrelationId:
    """Generate a new ULID-based correlation ID."""
    return CorrelationId(str(ULID()))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ServiceIdentity(BaseModel):
    """Identifies a service in the system."""

    service: str = Field(..., description="Service name, e.g. 'control-api'")
    instance_id: str = Field(..., description="Instance identifier")
    version: str = Field(default="0.1.0")


class PagedResponse(BaseModel):
    """Generic paged response wrapper."""

    total: int
    offset: int
    limit: int
