"""MSAL client credentials flow for Microsoft Graph / Defender APIs.

Implements app-only auth with client credentials.
Tokens are cached and refreshed automatically by MSAL.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import msal  # type: ignore[import-untyped]

logger = logging.getLogger("msclaw.auth")


@dataclass
class MSALConfig:
    """Configuration for MSAL client credentials auth."""

    tenant_id: str
    client_id: str
    client_secret: str  # In production, use certificate or managed identity
    scopes: list[str] = field(default_factory=lambda: ["https://graph.microsoft.com/.default"])


class MSALClient:
    """Wraps MSAL ConfidentialClientApplication for app-only auth."""

    def __init__(self, config: MSALConfig):
        self._config = config
        self._app = msal.ConfidentialClientApplication(
            client_id=config.client_id,
            client_credential=config.client_secret,
            authority=f"https://login.microsoftonline.com/{config.tenant_id}",
        )

    def acquire_token(self, scopes: list[str] | None = None) -> str:
        """Acquire an access token using client credentials flow.

        Returns the access token string.
        Raises AuthenticationError on failure.
        """
        target_scopes = scopes or self._config.scopes
        result = self._app.acquire_token_for_client(scopes=target_scopes)

        if "access_token" in result:
            logger.debug("Acquired token for scopes: %s", target_scopes)
            return result["access_token"]

        error_desc = result.get("error_description", "Unknown error")
        error_code = result.get("error", "unknown")
        raise RuntimeError(
            f"MSAL token acquisition failed: [{error_code}] {error_desc}"
        )


class DevMSALClient:
    """Mock MSAL client for dev mode – returns a fake token."""

    def acquire_token(self, scopes: list[str] | None = None) -> str:
        logger.info("DEV MODE: Returning mock token")
        return "dev-mock-token-not-for-production"
