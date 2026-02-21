"""Unit tests for tool-runner policy enforcement.

Verifies the structural choke point: tool-runner REFUSES to execute
without a valid policy_decision_id backed by an 'allow' decision in Postgres.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bus_message(
    tool_name: str = "isolate_device",
    step_name: str = "step_1",
    params: dict | None = None,
    policy_decision_id: str | None = None,
    initiated_by: str = "responder@contoso.com",
) -> MagicMock:
    """Create a mock BusMessage for step intent."""
    msg = MagicMock()
    msg.subject = "workflow.step.intent"
    msg.correlation_id = str(uuid.uuid4())
    msg.run_id = str(uuid.uuid4())
    msg.step_id = str(uuid.uuid4())
    msg.payload = {
        "tool_name": tool_name,
        "step_name": step_name,
        "params": params or {"device_id": "D-123"},
        "initiated_by": initiated_by,
    }
    if policy_decision_id:
        msg.payload["policy_decision_id"] = policy_decision_id
    return msg


def _make_policy_decision(decision: str = "allow") -> MagicMock:
    """Create a mock PolicyDecision row."""
    pd = MagicMock()
    pd.id = uuid.uuid4()
    pd.decision = decision
    pd.reasons = []
    return pd


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_policy_decision_id_rejected():
    """Intent without policy_decision_id must be rejected."""
    from msclaw.tool_runner.service import _handle_step_intent

    msg = _make_bus_message(policy_decision_id=None)

    with patch("msclaw.tool_runner.service._emit_failure", new_callable=AsyncMock) as mock_fail, \
         patch("msclaw.tool_runner.service.append_audit", new_callable=AsyncMock) as mock_audit:
        await _handle_step_intent(msg)

        mock_fail.assert_called_once()
        error_arg = mock_fail.call_args[0][1]
        assert "No policy_decision_id" in error_arg

        # Should also audit the rejection
        mock_audit.assert_called_once()
        audit_kwargs = mock_audit.call_args[1]
        assert audit_kwargs["action"] == "step.rejected.no_policy"


@pytest.mark.asyncio
async def test_invalid_policy_decision_id_rejected():
    """Intent with policy_decision_id not in DB must be rejected."""
    from msclaw.tool_runner.service import _handle_step_intent

    fake_decision_id = str(uuid.uuid4())
    msg = _make_bus_message(policy_decision_id=fake_decision_id)

    # Mock DB session to return None (decision not found)
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    with patch("msclaw.tool_runner.service._emit_failure", new_callable=AsyncMock) as mock_fail, \
         patch("msclaw.tool_runner.service.append_audit", new_callable=AsyncMock) as mock_audit, \
         patch("msclaw.tool_runner.service.get_session") as mock_get_session:

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False
        mock_get_session.return_value = mock_ctx

        await _handle_step_intent(msg)

        mock_fail.assert_called_once()
        error_arg = mock_fail.call_args[0][1]
        assert "not found in database" in error_arg


@pytest.mark.asyncio
async def test_denied_policy_decision_rejected():
    """Intent with policy decision='deny' must be rejected."""
    from msclaw.tool_runner.service import _handle_step_intent

    fake_decision_id = str(uuid.uuid4())
    msg = _make_bus_message(policy_decision_id=fake_decision_id)

    # Mock DB session to return a deny decision
    denied_decision = _make_policy_decision(decision="deny")
    denied_decision.reasons = ["VIP device requires senior approval"]

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = denied_decision
    mock_session.execute.return_value = mock_result

    with patch("msclaw.tool_runner.service._emit_failure", new_callable=AsyncMock) as mock_fail, \
         patch("msclaw.tool_runner.service.append_audit", new_callable=AsyncMock) as mock_audit, \
         patch("msclaw.tool_runner.service.get_session") as mock_get_session:

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False
        mock_get_session.return_value = mock_ctx

        await _handle_step_intent(msg)

        mock_fail.assert_called_once()
        error_arg = mock_fail.call_args[0][1]
        assert "not 'allow'" in error_arg


@pytest.mark.asyncio
async def test_unknown_tool_rejected():
    """Intent with unregistered tool name must be rejected."""
    from msclaw.tool_runner.service import _handle_step_intent, _tool_registry

    fake_decision_id = str(uuid.uuid4())
    msg = _make_bus_message(
        tool_name="nonexistent_tool",
        policy_decision_id=fake_decision_id,
    )

    # Mock DB session to return an allow decision
    allow_decision = _make_policy_decision(decision="allow")

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = allow_decision
    mock_session.execute.return_value = mock_result

    # Make sure the tool is NOT in the registry
    _tool_registry.pop("nonexistent_tool", None)

    with patch("msclaw.tool_runner.service._emit_failure", new_callable=AsyncMock) as mock_fail, \
         patch("msclaw.tool_runner.service.append_audit", new_callable=AsyncMock) as mock_audit, \
         patch("msclaw.tool_runner.service.get_session") as mock_get_session:

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False
        mock_get_session.return_value = mock_ctx

        await _handle_step_intent(msg)

        mock_fail.assert_called_once()
        error_arg = mock_fail.call_args[0][1]
        assert "Unknown tool" in error_arg
