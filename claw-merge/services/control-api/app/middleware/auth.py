"""Authentication and RBAC middleware.

For MVP, uses a simple API key + role header approach.
In production, replace with JWT validation from Entra ID / your IdP.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import HTTPException, Header, Depends

logger = logging.getLogger("msclaw.control_api.auth")

# Dev mode: accept any X-Actor header and X-Roles header
# Production: validate JWT and extract roles from token claims

DEV_MODE = os.getenv("DEV_MODE", "true").lower() == "true"

VALID_ROLES = {"security-analyst", "security-lead", "soc-manager", "admin"}


def get_actor_roles(
    x_actor: str = Header(...),
    x_roles: str = Header(default="security-analyst"),
) -> dict[str, Any]:
    """Extract actor and roles from request headers.

    In production, these come from a validated JWT token.
    """
    if DEV_MODE:
        roles = [r.strip() for r in x_roles.split(",") if r.strip() in VALID_ROLES]
        if not roles:
            roles = ["security-analyst"]
        return {"actor": x_actor, "roles": roles}

    raise HTTPException(status_code=501, detail="Production auth not yet implemented")


def require_role(required: str):
    """Dependency that requires a specific role."""
    def _check(auth: dict[str, Any] = Depends(get_actor_roles)) -> dict[str, Any]:
        if required not in auth["roles"]:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{required}' required. You have: {auth['roles']}",
            )
        return auth
    return _check
