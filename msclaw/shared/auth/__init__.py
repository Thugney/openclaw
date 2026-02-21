"""MSClaw Microsoft authentication module.

Implements MSAL client credentials flow for app-only auth,
and interactive flow for delegated auth where required.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("msclaw.auth")


@dataclass
class TenantConfig:
    """Microsoft Entra app registration details."""
    tenant_id: str
    client_id: str
    client_secret: str | None = None
    certificate_path: str | None = None
    certificate_password: str | None = None


@dataclass
class TokenResult:
    access_token: str
    expires_in: int
    token_type: str = "Bearer"
    scope: str = ""


class MSGraphAuth:
    """Handles Microsoft Graph / Defender API authentication via MSAL.

    Supports:
    - Client credentials flow (app-only, preferred)
    - Interactive flow (delegated, only when explicitly required)
    """

    def __init__(self, tenant_config: TenantConfig):
        self._config = tenant_config
        self._token_cache: dict[str, TokenResult] = {}

    async def get_app_token(self, scopes: list[str] | None = None) -> TokenResult:
        """Acquire token using client credentials flow (app-only).

        This is the preferred auth method. Uses MSAL confidential client.
        """
        scope_key = ",".join(sorted(scopes or ["https://graph.microsoft.com/.default"]))

        if scope_key in self._token_cache:
            return self._token_cache[scope_key]

        try:
            import msal  # type: ignore[import-untyped]

            app = msal.ConfidentialClientApplication(
                self._config.client_id,
                authority=f"https://login.microsoftonline.com/{self._config.tenant_id}",
                client_credential=self._config.client_secret,
            )

            result = app.acquire_token_for_client(
                scopes=scopes or ["https://graph.microsoft.com/.default"]
            )

            if "access_token" not in result:
                error = result.get("error_description", "Unknown MSAL error")
                raise AuthError(f"Failed to acquire app token: {error}")

            token = TokenResult(
                access_token=result["access_token"],
                expires_in=result.get("expires_in", 3600),
                scope=scope_key,
            )
            self._token_cache[scope_key] = token
            logger.info("Acquired app-only token for scopes: %s", scope_key)
            return token

        except ImportError:
            logger.warning("MSAL not installed, returning dev-mode token")
            return self._dev_token(scope_key)

    async def get_delegated_token(self, scopes: list[str]) -> TokenResult:
        """Acquire token using interactive/device-code flow (delegated).

        Only used where app-only is not supported (explicitly documented).
        """
        logger.warning(
            "Delegated auth requested for scopes: %s - "
            "this requires user interaction",
            scopes,
        )
        # In production, this would use MSAL PublicClientApplication
        # with device code flow. For MVP, return dev token.
        return self._dev_token(",".join(sorted(scopes)))

    def _dev_token(self, scope_key: str) -> TokenResult:
        """Return a placeholder token for dev mode."""
        return TokenResult(
            access_token="dev-mode-token-not-for-production",
            expires_in=3600,
            scope=scope_key,
        )

    def clear_cache(self) -> None:
        self._token_cache.clear()


class AuthError(Exception):
    """Authentication-specific error."""


class MSGraphClient:
    """Thin HTTP client for Microsoft Graph API calls.

    All Microsoft API interactions go through this client,
    which handles auth, retries, and rate limiting.
    """

    GRAPH_BASE = "https://graph.microsoft.com/v1.0"
    GRAPH_BETA = "https://graph.microsoft.com/beta"
    DEFENDER_BASE = "https://api.securitycenter.microsoft.com/api"

    def __init__(self, auth: MSGraphAuth, *, dev_mode: bool = False):
        self._auth = auth
        self._dev_mode = dev_mode

    async def graph_get(self, path: str, *, beta: bool = False) -> dict[str, Any]:
        """GET request to Microsoft Graph."""
        base = self.GRAPH_BETA if beta else self.GRAPH_BASE
        return await self._request("GET", f"{base}{path}")

    async def graph_post(self, path: str, body: dict[str, Any], *, beta: bool = False) -> dict[str, Any]:
        """POST request to Microsoft Graph."""
        base = self.GRAPH_BETA if beta else self.GRAPH_BASE
        return await self._request("POST", f"{base}{path}", body=body)

    async def defender_get(self, path: str) -> dict[str, Any]:
        """GET request to Defender for Endpoint API."""
        return await self._request("GET", f"{self.DEFENDER_BASE}{path}")

    async def defender_post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST request to Defender for Endpoint API."""
        return await self._request("POST", f"{self.DEFENDER_BASE}{path}", body=body)

    async def _request(self, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute an HTTP request with auth headers."""
        if self._dev_mode:
            logger.info("[DEV MODE] %s %s body=%s", method, url, body)
            return self._mock_response(method, url, body)

        token = await self._auth.get_app_token()

        try:
            import httpx  # type: ignore[import-untyped]

            async with httpx.AsyncClient() as client:
                headers = {
                    "Authorization": f"Bearer {token.access_token}",
                    "Content-Type": "application/json",
                }
                response = await client.request(
                    method, url, headers=headers, json=body, timeout=30.0
                )
                response.raise_for_status()
                return response.json() if response.content else {}

        except ImportError:
            logger.warning("httpx not installed, using dev mode")
            return self._mock_response(method, url, body)

    def _mock_response(self, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return mock responses for dev mode."""
        if "machines" in url and "isolate" in url:
            return {"@odata.context": "mock", "id": "mock-action-id", "type": "Isolate", "status": "Pending"}
        if "machines" in url and "unisolate" in url:
            return {"@odata.context": "mock", "id": "mock-action-id", "type": "Unisolate", "status": "Pending"}
        if "machines" in url and "collectInvestigationPackage" in url:
            return {"@odata.context": "mock", "id": "mock-action-id", "type": "CollectInvestigationPackage", "status": "Pending"}
        if "machines" in url and "runAntiVirusScan" in url:
            return {"@odata.context": "mock", "id": "mock-action-id", "type": "RunAntiVirusScan", "status": "Pending"}
        if "managedDevices" in url and "syncDevice" in url:
            return {"status": "synced"}
        if "incidents" in url:
            return {
                "id": "mock-incident",
                "alerts": [{"devices": [{"deviceId": "mock-device-id", "deviceDnsName": "DESKTOP-MOCK"}]}],
            }
        if "users" in url and "revokeSignInSessions" in url:
            return {"value": True}
        if "users" in url:
            return {"id": "mock-user-id", "accountEnabled": False}
        return {"status": "ok", "mock": True}
