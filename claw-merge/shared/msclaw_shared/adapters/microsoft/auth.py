"""MSAL client-credentials authentication for Microsoft Graph / Defender APIs.

Uses app-only (daemon) flow with client_credentials grant.
Requires: MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET environment variables.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from msclaw_shared.config import MicrosoftConfig, load_config

logger = logging.getLogger("msclaw.microsoft.auth")

# Token cache (ephemeral – this IS an acceptable in-memory cache for tokens)
_token_cache: dict[str, dict[str, Any]] = {}


async def get_access_token(
    scope: str = "https://graph.microsoft.com/.default",
    cfg: MicrosoftConfig | None = None,
) -> str:
    """Acquire an OAuth2 access token via client_credentials grant.

    Args:
        scope: The resource scope. Common values:
          - "https://graph.microsoft.com/.default" for Graph API
          - "https://api.securitycenter.microsoft.com/.default" for MDE/Defender
        cfg: Optional config override.
    """
    if cfg is None:
        cfg = load_config().microsoft

    if not cfg.tenant_id or not cfg.client_id or not cfg.client_secret:
        raise RuntimeError(
            "Microsoft credentials not configured. Set MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET"
        )

    # Check cache
    cached = _token_cache.get(scope)
    if cached and cached["expires_at"] > time.time() + 60:
        return cached["access_token"]

    token_url = f"https://login.microsoftonline.com/{cfg.tenant_id}/oauth2/v2.0/token"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            token_url,
            data={
                "client_id": cfg.client_id,
                "client_secret": cfg.client_secret,
                "scope": scope,
                "grant_type": "client_credentials",
            },
        )
        resp.raise_for_status()
        token_data = resp.json()

    access_token = token_data["access_token"]
    expires_in = token_data.get("expires_in", 3600)

    _token_cache[scope] = {
        "access_token": access_token,
        "expires_at": time.time() + expires_in,
    }

    logger.info("Acquired token for scope %s (expires in %ds)", scope, expires_in)
    return access_token
