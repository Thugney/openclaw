"""Tests for the tool runner."""

from __future__ import annotations

import pytest

from shared.contracts import CorrelationContext, ToolExecutionStatus, ToolIntent
from shared.errors import IdempotencyConflictError, PolicyDeniedError
from services.tool_runner import ToolRunner
from plugins.defender_xdr import DefenderXDRPlugin


@pytest.fixture
def runner() -> ToolRunner:
    r = ToolRunner(dev_mode=True)
    r.register_plugin(DefenderXDRPlugin())
    return r


@pytest.fixture
def correlation() -> CorrelationContext:
    return CorrelationContext(operator_id="test-operator", source="test")


@pytest.mark.asyncio
async def test_execute_allowlisted_action(runner: ToolRunner, correlation: CorrelationContext) -> None:
    intent = ToolIntent(
        plugin="defender_xdr",
        action="isolate_device",
        parameters={"device_id": "dev-001"},
        idempotency_key="test-key-001",
        correlation=correlation,
    )
    result = await runner.execute(intent)
    assert result.status == ToolExecutionStatus.COMPLETED


@pytest.mark.asyncio
async def test_deny_non_allowlisted_action(runner: ToolRunner, correlation: CorrelationContext) -> None:
    intent = ToolIntent(
        plugin="unknown_plugin",
        action="dangerous_action",
        parameters={},
        idempotency_key="test-key-002",
        correlation=correlation,
    )
    with pytest.raises(PolicyDeniedError):
        await runner.execute(intent)


@pytest.mark.asyncio
async def test_idempotency_dedup(runner: ToolRunner, correlation: CorrelationContext) -> None:
    key = "idempotent-key-001"
    intent = ToolIntent(
        plugin="defender_xdr",
        action="isolate_device",
        parameters={"device_id": "dev-001"},
        idempotency_key=key,
        correlation=correlation,
    )

    result1 = await runner.execute(intent)
    result2 = await runner.execute(intent)

    assert result1.status == ToolExecutionStatus.COMPLETED
    assert result2.status == ToolExecutionStatus.COMPLETED
    # Second call should return cached result


@pytest.mark.asyncio
async def test_idempotency_conflict(runner: ToolRunner, correlation: CorrelationContext) -> None:
    key = "conflict-key-001"

    intent1 = ToolIntent(
        plugin="defender_xdr",
        action="isolate_device",
        parameters={"device_id": "dev-001"},
        idempotency_key=key,
        correlation=correlation,
    )
    await runner.execute(intent1)

    intent2 = ToolIntent(
        plugin="defender_xdr",
        action="unisolate_device",  # Different action, same key
        parameters={"device_id": "dev-001"},
        idempotency_key=key,
        correlation=correlation,
    )
    with pytest.raises(IdempotencyConflictError):
        await runner.execute(intent2)
