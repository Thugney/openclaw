"""Policy gate models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PolicyVerdict(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class PolicyDecision(BaseModel):
    """Result of evaluating a tool intent against OPA policies."""

    verdict: PolicyVerdict
    rule: str = Field(..., description="Rego rule that produced this verdict")
    reason: str = Field(default="")
    required_approvers: list[str] = Field(
        default_factory=list,
        description="Roles or users who must approve, if verdict is require_approval",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context from policy evaluation",
    )
