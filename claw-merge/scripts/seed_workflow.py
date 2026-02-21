"""Seed the 'Contain device from incident' workflow into the database."""

import asyncio
import sys
import os

# Ensure the msclaw package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from msclaw_shared.config import load_config
from msclaw_shared.db import Workflow, get_session, Base
from sqlalchemy import select


CONTAIN_DEVICE_WORKFLOW = {
    "name": "contain_device_from_incident",
    "description": "Contain a device identified in a Defender incident: resolve device, isolate, collect investigation package.",
    "steps": [
        {
            "name": "resolve_device",
            "tool": "resolve_device_from_incident",
            "params": {},
            "description": "Resolve the device from the incident ID via Defender XDR/MDE",
        },
        {
            "name": "isolate_device",
            "tool": "isolate_device",
            "params": {"isolation_type": "Full"},
            "description": "Isolate the device to contain the threat",
        },
        {
            "name": "collect_package",
            "tool": "collect_investigation_package",
            "params": {},
            "description": "Collect a forensic investigation package from the device",
        },
    ],
}


async def seed():
    cfg = load_config()
    async with get_session() as session:
        # Check if already exists
        result = await session.execute(
            select(Workflow).where(Workflow.name == CONTAIN_DEVICE_WORKFLOW["name"])
        )
        existing = result.scalar_one_or_none()
        if existing:
            print(f"Workflow '{existing.name}' already exists (id={existing.id})")
            return str(existing.id)

        wf = Workflow(
            name=CONTAIN_DEVICE_WORKFLOW["name"],
            description=CONTAIN_DEVICE_WORKFLOW["description"],
            steps_definition=CONTAIN_DEVICE_WORKFLOW["steps"],
        )
        session.add(wf)
        await session.flush()
        print(f"Created workflow '{wf.name}' with id={wf.id}")
        return str(wf.id)


if __name__ == "__main__":
    asyncio.run(seed())
