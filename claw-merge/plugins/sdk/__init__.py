"""MSClaw Plugin SDK – strict contract for all plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class IdempotencyStrategy(StrEnum):
    """How the plugin handles repeated calls with the same idempotency key."""

    CHECK_AND_SKIP = "check_and_skip"       # Check state, skip if already done
    SAFE_TO_RETRY = "safe_to_retry"         # Action is naturally idempotent
    REQUIRE_LOCK = "require_lock"           # Must acquire a lock first


class ActionDefinition(BaseModel):
    """Contract for a single plugin action."""

    name: str = Field(..., description="Action name, e.g. 'isolate_device'")
    description: str = Field(default="")
    input_schema: dict[str, Any] = Field(..., description="JSONSchema for inputs")
    required_permissions: list[str] = Field(
        default_factory=list,
        description="MS Graph permissions / app roles required",
    )
    idempotency_strategy: IdempotencyStrategy
    rollback_action: str | None = Field(
        default=None,
        description="Name of the reverse action, if feasible",
    )
    requires_approval: bool = Field(
        default=False,
        description="Whether this action always requires approval (policy may add more)",
    )
    audit_fields: list[str] = Field(
        default_factory=list,
        description="Additional fields to capture in audit log",
    )


class PluginMetadata(BaseModel):
    """Metadata describing a plugin and its actions."""

    name: str = Field(..., description="Plugin name, e.g. 'defender_xdr'")
    version: str = Field(default="0.1.0")
    description: str = Field(default="")
    actions: list[ActionDefinition] = Field(default_factory=list)


class PluginBase(ABC):
    """Base class for all MSClaw plugins.

    Every plugin must:
    1. Declare its metadata (actions, permissions, schemas)
    2. Implement execute() for each action
    3. Handle idempotency per its declared strategy
    """

    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata including all action definitions."""
        ...

    @abstractmethod
    async def execute(
        self,
        action: str,
        inputs: dict[str, Any],
        context: PluginContext,
    ) -> dict[str, Any]:
        """Execute an action with the given inputs.

        Must respect the idempotency strategy declared in metadata.
        Must raise PluginError on failure (never swallow exceptions).
        """
        ...

    def get_action(self, action_name: str) -> ActionDefinition | None:
        """Look up an action definition by name."""
        for a in self.metadata().actions:
            if a.name == action_name:
                return a
        return None


class PluginContext(BaseModel):
    """Context injected into plugin execution."""

    correlation_id: str
    idempotency_key: str
    actor: str
    dev_mode: bool = False
    access_token: str | None = None  # Injected per-job, short-lived
    extra: dict[str, Any] = Field(default_factory=dict)
