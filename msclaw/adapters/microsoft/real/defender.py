"""Real Microsoft Defender / MDE adapters.

Implements the "Contain device from incident" workflow:
  1. resolve_device_from_incident – Get device details from an MDE incident
  2. isolate_device – Isolate a device via MDE API
  3. collect_investigation_package – Request investigation package collection

All calls use MSAL client_credentials (app-only) auth via the shared auth module.
Calls the Microsoft 365 Defender API (api.securitycenter.microsoft.com).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

from msclaw.adapters.microsoft.auth import get_access_token
from msclaw.shared.artifacts import upload_artifact

logger = logging.getLogger("msclaw.adapters.microsoft.real.defender")

MDE_BASE = "https://api.securitycenter.microsoft.com/api"
MDE_SCOPE = "https://api.securitycenter.microsoft.com/.default"


async def _mde_request(
    method: str, path: str, json_body: dict | None = None
) -> dict[str, Any]:
    """Make an authenticated request to the MDE API."""
    token = await get_access_token(scope=MDE_SCOPE)
    url = f"{MDE_BASE}{path}"

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.request(
            method,
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=json_body,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}


async def resolve_device_from_incident(params: dict[str, Any]) -> dict[str, Any]:
    """Resolve device information from a Defender incident.

    MDE API: GET /incidents/{id}
    Then:    GET /machines/{machineId}

    Required params:
      - incident_id: str (MDE incident ID)

    Returns device details including id, computerDnsName, tags, etc.
    """
    incident_id = params.get("incident_id")
    if not incident_id:
        raise ValueError("incident_id is required")

    logger.info("[REAL] Resolving device from incident %s", incident_id)

    # Get incident details
    incident = await _mde_request("GET", f"/incidents/{incident_id}")

    # Extract alerts and find machine IDs
    alerts = incident.get("alerts", [])
    if not alerts:
        # Try via alerts endpoint
        alerts_resp = await _mde_request(
            "GET", f"/incidents/{incident_id}/alerts"
        )
        alerts = alerts_resp.get("value", [])

    machine_ids = set()
    for alert in alerts:
        for entity in alert.get("entities", []):
            if entity.get("entityType") == "Machine":
                machine_ids.add(entity.get("machineId") or entity.get("deviceId"))
        # Also check direct machine association
        machine_id = alert.get("machineId")
        if machine_id:
            machine_ids.add(machine_id)

    if not machine_ids:
        raise ValueError(f"No devices found in incident {incident_id}")

    # Get full device details for the first machine
    device_id = next(iter(machine_ids))
    device = await _mde_request("GET", f"/machines/{device_id}")

    return {
        "device_id": device.get("id"),
        "device_name": device.get("computerDnsName"),
        "os_platform": device.get("osPlatform"),
        "health_status": device.get("healthStatus"),
        "risk_score": device.get("riskScore"),
        "exposure_level": device.get("exposureLevel"),
        "tags": device.get("machineTags", []),
        "ip_addresses": [
            ip.get("ipAddress")
            for ip in device.get("ipInterfaces", [])
        ],
        "incident_id": incident_id,
        "all_device_ids": list(machine_ids),
    }


async def isolate_device(params: dict[str, Any]) -> dict[str, Any]:
    """Isolate a device via MDE API.

    MDE API: POST /machines/{id}/isolate

    Required params:
      - device_id: str (MDE machine ID)
      - isolation_type: str ("Full" or "Selective", default "Full")
      - comment: str (reason for isolation)

    Returns the machine action response.
    """
    device_id = params.get("device_id")
    if not device_id:
        # Try to get from prior step output
        prior = params.get("prior_outputs", {})
        resolve_output = prior.get("resolve_device", {})
        device_id = resolve_output.get("device_id")

    if not device_id:
        raise ValueError("device_id is required")

    isolation_type = params.get("isolation_type", "Full")
    comment = params.get("comment", "Isolated by MSClaw automated response")

    logger.info("[REAL] Isolating device %s (type=%s)", device_id, isolation_type)

    result = await _mde_request(
        "POST",
        f"/machines/{device_id}/isolate",
        json_body={
            "Comment": comment,
            "IsolationType": isolation_type,
        },
    )

    return {
        "action_id": result.get("id"),
        "device_id": device_id,
        "status": result.get("status", "Pending"),
        "type": result.get("type"),
        "isolation_type": isolation_type,
        "requestor": result.get("requestor"),
        "created_at": result.get("creationDateTimeUtc"),
    }


async def collect_investigation_package(params: dict[str, Any]) -> dict[str, Any]:
    """Request collection of an investigation package from a device.

    MDE API: POST /machines/{id}/collectInvestigationPackage

    Required params:
      - device_id: str (MDE machine ID)
      - comment: str (reason)

    Returns the machine action response. The actual package must be
    downloaded separately once the action completes.
    """
    device_id = params.get("device_id")
    if not device_id:
        prior = params.get("prior_outputs", {})
        resolve_output = prior.get("resolve_device", {})
        device_id = resolve_output.get("device_id")

    if not device_id:
        raise ValueError("device_id is required")

    comment = params.get("comment", "Investigation package collected by MSClaw")

    logger.info("[REAL] Collecting investigation package from device %s", device_id)

    result = await _mde_request(
        "POST",
        f"/machines/{device_id}/collectInvestigationPackage",
        json_body={"Comment": comment},
    )

    action_id = result.get("id")

    # Store reference as artifact pointer
    artifact_key = f"investigations/{device_id}/{action_id}/metadata.json"
    import json
    upload_artifact(
        artifact_key,
        json.dumps(result, default=str).encode(),
        content_type="application/json",
        metadata={"device_id": device_id, "action_id": str(action_id)},
    )

    return {
        "action_id": action_id,
        "device_id": device_id,
        "status": result.get("status", "Pending"),
        "type": result.get("type"),
        "created_at": result.get("creationDateTimeUtc"),
        "_artifact_keys": [artifact_key],
    }
