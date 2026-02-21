"""Tests for msclaw_shared.errors."""

import pytest

from msclaw_shared.errors import (
    ApprovalRequiredError,
    AuthenticationError,
    AuthorizationError,
    IdempotentSkipError,
    ModelRouterError,
    MSClawError,
    PluginError,
    PolicyDeniedError,
    ToolNotAllowedError,
    WorkflowError,
)


# ---------------------------------------------------------------------------
# MSClawError (base)
# ---------------------------------------------------------------------------


def test_msclaw_error_default_code():
    err = MSClawError("something went wrong")
    assert str(err) == "something went wrong"
    assert err.code == "INTERNAL_ERROR"
    assert err.details == {}


def test_msclaw_error_custom_code_and_details():
    err = MSClawError("oops", code="CUSTOM", details={"key": "value"})
    assert err.code == "CUSTOM"
    assert err.details == {"key": "value"}


def test_msclaw_error_is_exception():
    err = MSClawError("fail")
    assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# PolicyDeniedError
# ---------------------------------------------------------------------------


def test_policy_denied_error_instantiation():
    err = PolicyDeniedError("Access denied", rule="deny_prod_wipe", reason="Production devices protected")
    assert str(err) == "Access denied"
    assert err.code == "POLICY_DENIED"
    assert err.rule == "deny_prod_wipe"
    assert err.reason == "Production devices protected"


def test_policy_denied_error_details():
    err = PolicyDeniedError("Denied", rule="block_all", reason="nope")
    assert err.details["rule"] == "block_all"
    assert err.details["reason"] == "nope"


def test_policy_denied_error_is_msclaw_error():
    err = PolicyDeniedError("Denied", rule="r1")
    assert isinstance(err, MSClawError)
    assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# ApprovalRequiredError
# ---------------------------------------------------------------------------


def test_approval_required_error_instantiation():
    err = ApprovalRequiredError(
        "Approval needed",
        approval_id="01HAPPR",
        required_approvers=["soc-lead", "manager"],
    )
    assert str(err) == "Approval needed"
    assert err.code == "APPROVAL_REQUIRED"
    assert err.approval_id == "01HAPPR"
    assert err.required_approvers == ["soc-lead", "manager"]


def test_approval_required_error_details():
    err = ApprovalRequiredError(
        "Need approval",
        approval_id="01HAPPR2",
        required_approvers=["admin"],
    )
    assert err.details["approval_id"] == "01HAPPR2"
    assert err.details["required_approvers"] == ["admin"]


# ---------------------------------------------------------------------------
# IdempotentSkipError
# ---------------------------------------------------------------------------


def test_idempotent_skip_error_instantiation():
    err = IdempotentSkipError(
        "Already executed",
        idempotency_key="idem-001",
        original_result={"status": "completed"},
    )
    assert str(err) == "Already executed"
    assert err.code == "IDEMPOTENT_SKIP"
    assert err.idempotency_key == "idem-001"
    assert err.original_result == {"status": "completed"}


def test_idempotent_skip_error_details():
    err = IdempotentSkipError("Skip", idempotency_key="idem-002")
    assert err.details["idempotency_key"] == "idem-002"


def test_idempotent_skip_error_default_original_result():
    err = IdempotentSkipError("Skip", idempotency_key="idem-003")
    assert err.original_result == {}


# ---------------------------------------------------------------------------
# PluginError
# ---------------------------------------------------------------------------


def test_plugin_error_instantiation():
    err = PluginError(
        "Plugin failed",
        plugin="defender_xdr",
        action="isolate_device",
        upstream_error="HTTP 503",
    )
    assert str(err) == "Plugin failed"
    assert err.code == "PLUGIN_ERROR"


def test_plugin_error_details():
    err = PluginError(
        "Failed",
        plugin="sentinel",
        action="run_query",
        upstream_error="timeout",
    )
    assert err.details["plugin"] == "sentinel"
    assert err.details["action"] == "run_query"
    assert err.details["upstream_error"] == "timeout"


def test_plugin_error_default_upstream_error():
    err = PluginError("Failed", plugin="p", action="a")
    assert err.details["upstream_error"] == ""


# ---------------------------------------------------------------------------
# ToolNotAllowedError
# ---------------------------------------------------------------------------


def test_tool_not_allowed_error_instantiation():
    err = ToolNotAllowedError("defender_xdr", "wipe_device")
    assert "defender_xdr.wipe_device" in str(err)
    assert err.code == "TOOL_NOT_ALLOWED"


def test_tool_not_allowed_error_details():
    err = ToolNotAllowedError("sentinel", "delete_workspace")
    assert err.details["plugin"] == "sentinel"
    assert err.details["action"] == "delete_workspace"


# ---------------------------------------------------------------------------
# AuthenticationError
# ---------------------------------------------------------------------------


def test_authentication_error_default_message():
    err = AuthenticationError()
    assert str(err) == "Authentication failed"
    assert err.code == "AUTHENTICATION_ERROR"
    assert err.details == {}


def test_authentication_error_custom_message():
    err = AuthenticationError("Token expired")
    assert str(err) == "Token expired"
    assert err.code == "AUTHENTICATION_ERROR"


# ---------------------------------------------------------------------------
# AuthorizationError
# ---------------------------------------------------------------------------


def test_authorization_error_default_message():
    err = AuthorizationError()
    assert str(err) == "Insufficient permissions"
    assert err.code == "AUTHORIZATION_ERROR"


def test_authorization_error_details():
    err = AuthorizationError("Not allowed", required_role="soc-admin")
    assert err.details["required_role"] == "soc-admin"


def test_authorization_error_default_required_role():
    err = AuthorizationError()
    assert err.details["required_role"] == ""


# ---------------------------------------------------------------------------
# WorkflowError
# ---------------------------------------------------------------------------


def test_workflow_error_instantiation():
    err = WorkflowError(
        "Workflow timed out",
        workflow_name="isolate_and_scan",
        run_id="01HRUN",
    )
    assert str(err) == "Workflow timed out"
    assert err.code == "WORKFLOW_ERROR"


def test_workflow_error_details():
    err = WorkflowError("Failed", workflow_name="remediate", run_id="01HRUN2")
    assert err.details["workflow_name"] == "remediate"
    assert err.details["run_id"] == "01HRUN2"


def test_workflow_error_default_run_id():
    err = WorkflowError("Failed", workflow_name="scan")
    assert err.details["run_id"] == ""


# ---------------------------------------------------------------------------
# ModelRouterError
# ---------------------------------------------------------------------------


def test_model_router_error_instantiation():
    err = ModelRouterError("No available model", provider="azure_openai")
    assert str(err) == "No available model"
    assert err.code == "MODEL_ROUTER_ERROR"


def test_model_router_error_details():
    err = ModelRouterError("Routing failed", provider="openai")
    assert err.details["provider"] == "openai"


def test_model_router_error_default_provider():
    err = ModelRouterError("Failed")
    assert err.details["provider"] == ""


# ---------------------------------------------------------------------------
# All errors are subclasses of MSClawError
# ---------------------------------------------------------------------------


def test_all_error_types_are_msclaw_errors():
    errors = [
        MSClawError("base"),
        PolicyDeniedError("denied", rule="r"),
        ApprovalRequiredError("approval", approval_id="a", required_approvers=[]),
        IdempotentSkipError("skip", idempotency_key="k"),
        PluginError("plugin", plugin="p", action="a"),
        ToolNotAllowedError("p", "a"),
        AuthenticationError(),
        AuthorizationError(),
        WorkflowError("wf", workflow_name="w"),
        ModelRouterError("mr"),
    ]

    for err in errors:
        assert isinstance(err, MSClawError), f"{type(err).__name__} is not an MSClawError"
        assert isinstance(err, Exception), f"{type(err).__name__} is not an Exception"
        assert hasattr(err, "code"), f"{type(err).__name__} missing 'code' attribute"
        assert hasattr(err, "details"), f"{type(err).__name__} missing 'details' attribute"
        assert isinstance(err.code, str), f"{type(err).__name__}.code is not a str"
        assert isinstance(err.details, dict), f"{type(err).__name__}.details is not a dict"


# ---------------------------------------------------------------------------
# Errors can be raised and caught
# ---------------------------------------------------------------------------


def test_policy_denied_error_can_be_caught():
    with pytest.raises(PolicyDeniedError) as exc_info:
        raise PolicyDeniedError("Blocked", rule="deny_all")

    assert exc_info.value.code == "POLICY_DENIED"


def test_msclaw_error_catches_subclasses():
    with pytest.raises(MSClawError):
        raise PluginError("fail", plugin="p", action="a")
