"""Tests for the Defender XDR plugin."""

from __future__ import annotations

import pytest

from shared.contracts import CorrelationContext, ToolExecutionStatus
from plugins.defender_xdr import DefenderXDRPlugin


@pytest.fixture
def plugin() -> DefenderXDRPlugin:
    return DefenderXDRPlugin()


@pytest.fixture
def correlation() -> CorrelationContext:
    return CorrelationContext(operator_id="test-operator", source="test")


def test_plugin_metadata(plugin: DefenderXDRPlugin) -> None:
    assert plugin.name == "defender_xdr"
    assert plugin.version == "1.0.0"
    assert len(plugin.actions()) == 5


def test_isolate_device_schema(plugin: DefenderXDRPlugin) -> None:
    action = plugin.actions()["isolate_device"]
    assert action.name == "isolate_device"
    assert "device_id" in action.input_schema["required"]
    assert action.rollback_action == "unisolate_device"


def test_validate_action_valid(plugin: DefenderXDRPlugin) -> None:
    errors = plugin.validate_action("isolate_device", {"device_id": "dev-001"})
    assert errors == []


def test_validate_action_missing_required(plugin: DefenderXDRPlugin) -> None:
    errors = plugin.validate_action("isolate_device", {})
    assert len(errors) > 0
    assert "device_id" in errors[0]


def test_validate_action_unknown(plugin: DefenderXDRPlugin) -> None:
    errors = plugin.validate_action("nonexistent_action", {})
    assert len(errors) > 0


def test_get_all_permissions(plugin: DefenderXDRPlugin) -> None:
    perms = plugin.get_all_permissions()
    perm_names = {p.permission for p in perms}
    assert "Machine.Isolate" in perm_names
    assert "Machine.Read.All" in perm_names


@pytest.mark.asyncio
async def test_isolate_device_dev_mode(plugin: DefenderXDRPlugin, correlation: CorrelationContext) -> None:
    result = await plugin.execute(
        "isolate_device",
        {"device_id": "test-device-001"},
        correlation,
        dev_mode=True,
    )
    assert result.status == ToolExecutionStatus.COMPLETED
    assert result.result is not None
    assert result.result["type"] == "Isolate"


@pytest.mark.asyncio
async def test_resolve_device_from_incident_dev_mode(plugin: DefenderXDRPlugin, correlation: CorrelationContext) -> None:
    result = await plugin.execute(
        "resolve_device_from_incident",
        {"incident_id": "INC-42"},
        correlation,
        dev_mode=True,
    )
    assert result.status == ToolExecutionStatus.COMPLETED
    assert result.result is not None
    assert "deviceId" in result.result


@pytest.mark.asyncio
async def test_resolve_device_direct_id(plugin: DefenderXDRPlugin, correlation: CorrelationContext) -> None:
    result = await plugin.execute(
        "resolve_device_from_incident",
        {"device_id": "direct-device-001"},
        correlation,
        dev_mode=True,
    )
    assert result.status == ToolExecutionStatus.COMPLETED
    assert result.result is not None
    assert result.result["deviceId"] == "direct-device-001"


@pytest.mark.asyncio
async def test_resolve_device_missing_params(plugin: DefenderXDRPlugin, correlation: CorrelationContext) -> None:
    result = await plugin.execute(
        "resolve_device_from_incident",
        {},
        correlation,
        dev_mode=True,
    )
    assert result.status == ToolExecutionStatus.FAILED
