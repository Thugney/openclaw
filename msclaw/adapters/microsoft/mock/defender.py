"""Mock Microsoft Defender adapters – for dev/test without a real tenant.

Returns realistic-looking responses.  Every mock invocation is logged
in audit with adapter_mode="mock" so it's never confused with real data.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from msclaw.shared.artifacts import upload_artifact

logger = logging.getLogger("msclaw.adapters.microsoft.mock.defender")


async def resolve_device_from_incident(params: dict[str, Any]) -> dict[str, Any]:
    """Mock: Resolve device from incident."""
    incident_id = params.get("incident_id", "INC-MOCK-001")

    logger.info("[MOCK] Resolving device from incident %s", incident_id)

    device_id = f"mock-device-{uuid.uuid4().hex[:8]}"

    return {
        "device_id": device_id,
        "device_name": "DESKTOP-MOCK01.contoso.com",
        "os_platform": "Windows10",
        "health_status": "Active",
        "risk_score": "High",
        "exposure_level": "Medium",
        "tags": ["VIP", "Finance"],
        "ip_addresses": ["10.0.1.42", "192.168.1.100"],
        "incident_id": incident_id,
        "all_device_ids": [device_id],
        "_mock": True,
    }


async def isolate_device(params: dict[str, Any]) -> dict[str, Any]:
    """Mock: Isolate device."""
    device_id = params.get("device_id")
    if not device_id:
        prior = params.get("prior_outputs", {})
        resolve_output = prior.get("resolve_device", {})
        device_id = resolve_output.get("device_id", "mock-device-unknown")

    isolation_type = params.get("isolation_type", "Full")

    logger.info("[MOCK] Isolating device %s (type=%s)", device_id, isolation_type)

    action_id = str(uuid.uuid4())

    return {
        "action_id": action_id,
        "device_id": device_id,
        "status": "Pending",
        "type": "Isolate",
        "isolation_type": isolation_type,
        "requestor": "MSClaw-Mock",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "_mock": True,
    }


async def collect_investigation_package(params: dict[str, Any]) -> dict[str, Any]:
    """Mock: Collect investigation package."""
    device_id = params.get("device_id")
    if not device_id:
        prior = params.get("prior_outputs", {})
        resolve_output = prior.get("resolve_device", {})
        device_id = resolve_output.get("device_id", "mock-device-unknown")

    logger.info("[MOCK] Collecting investigation package from device %s", device_id)

    action_id = str(uuid.uuid4())

    # Upload a mock artifact to MinIO
    mock_package = {
        "device_id": device_id,
        "action_id": action_id,
        "status": "Pending",
        "type": "CollectInvestigationPackage",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mock_data": {
            "processes": ["svchost.exe", "explorer.exe", "suspicious.exe"],
            "network_connections": [
                {"dest": "10.0.1.1", "port": 443, "protocol": "TCP"},
                {"dest": "203.0.113.42", "port": 8443, "protocol": "TCP"},
            ],
            "registry_changes": ["HKLM\\Software\\MockMalware"],
        },
        "_mock": True,
    }

    artifact_key = f"investigations/{device_id}/{action_id}/metadata.json"
    try:
        upload_artifact(
            artifact_key,
            json.dumps(mock_package, default=str).encode(),
            content_type="application/json",
            metadata={"device_id": device_id, "action_id": action_id, "mock": "true"},
        )
        artifact_keys = [artifact_key]
    except Exception as e:
        logger.warning("Failed to upload mock artifact (MinIO may not be running): %s", e)
        artifact_keys = []

    return {
        "action_id": action_id,
        "device_id": device_id,
        "status": "Pending",
        "type": "CollectInvestigationPackage",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "_artifact_keys": artifact_keys,
        "_mock": True,
    }
