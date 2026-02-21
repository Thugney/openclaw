"""Tests for msclaw_shared.models."""

import hashlib

from msclaw_shared.models import (
    AuditDecision,
    AuditEntry,
    ApprovalAction,
    ApprovalRequest,
    ApprovalStatus,
    PolicyDecision,
    PolicyVerdict,
    StepStatus,
    ToolIntent,
    ToolResult,
    ToolResultStatus,
    WorkflowRun,
    WorkflowStatus,
    WorkflowStep,
    WorkflowSubmission,
)
from msclaw_shared.models.common import new_correlation_id, sha256_hex


# ---------------------------------------------------------------------------
# AuditEntry
# ---------------------------------------------------------------------------


def test_audit_entry_creation_with_all_fields():
    cid = new_correlation_id()
    entry = AuditEntry(
        id="01HENTRY",
        correlation_id=cid,
        actor="user@contoso.com",
        actor_type="user",
        action="defender_xdr.isolate_device",
        service="control-api",
        inputs={"device_id": "d-123"},
        outputs={"status": "isolated"},
        model_id="gpt-4o",
        model_provider="azure_openai",
        tool_name="defender_xdr.isolate_device",
        idempotency_key="idem-001",
        policy_decision=AuditDecision.ALLOWED,
        policy_rule="allow_isolate",
        policy_reason="device is in scope",
        previous_hash="abc123",
        entry_hash="def456",
        tags={"env": "prod"},
        error=None,
    )

    assert entry.id == "01HENTRY"
    assert entry.correlation_id == cid
    assert entry.actor == "user@contoso.com"
    assert entry.actor_type == "user"
    assert entry.action == "defender_xdr.isolate_device"
    assert entry.service == "control-api"
    assert entry.inputs == {"device_id": "d-123"}
    assert entry.outputs == {"status": "isolated"}
    assert entry.model_id == "gpt-4o"
    assert entry.model_provider == "azure_openai"
    assert entry.tool_name == "defender_xdr.isolate_device"
    assert entry.idempotency_key == "idem-001"
    assert entry.policy_decision == AuditDecision.ALLOWED
    assert entry.policy_rule == "allow_isolate"
    assert entry.policy_reason == "device is in scope"
    assert entry.previous_hash == "abc123"
    assert entry.entry_hash == "def456"
    assert entry.tags == {"env": "prod"}
    assert entry.error is None
    assert entry.timestamp is not None


def test_audit_entry_defaults():
    entry = AuditEntry(
        id="01HMIN",
        correlation_id=new_correlation_id(),
        actor="svc@contoso.com",
        action="scan",
        service="scanner",
    )

    assert entry.actor_type == "user"
    assert entry.inputs == {}
    assert entry.outputs == {}
    assert entry.model_id is None
    assert entry.tool_name is None
    assert entry.policy_decision is None
    assert entry.approval_chain == []
    assert entry.tags == {}
    assert entry.error is None


# ---------------------------------------------------------------------------
# WorkflowRun and status transitions
# ---------------------------------------------------------------------------


def test_workflow_run_creation():
    cid = new_correlation_id()
    run = WorkflowRun(
        run_id="01HRUN",
        correlation_id=cid,
        workflow_name="isolate_and_scan",
        idempotency_key="idem-wf-001",
        submitted_by="operator@contoso.com",
        inputs={"target": "host-42"},
    )

    assert run.run_id == "01HRUN"
    assert run.status == WorkflowStatus.PENDING
    assert run.workflow_name == "isolate_and_scan"
    assert run.submitted_by == "operator@contoso.com"
    assert run.steps == []
    assert run.outputs == {}
    assert run.error is None


def test_workflow_run_status_transitions():
    run = WorkflowRun(
        run_id="01HRUN2",
        correlation_id=new_correlation_id(),
        workflow_name="remediate",
        idempotency_key="idem-wf-002",
        submitted_by="op@contoso.com",
    )

    assert run.status == WorkflowStatus.PENDING

    run.status = WorkflowStatus.RUNNING
    assert run.status == WorkflowStatus.RUNNING

    run.status = WorkflowStatus.AWAITING_APPROVAL
    assert run.status == WorkflowStatus.AWAITING_APPROVAL

    run.status = WorkflowStatus.COMPLETED
    assert run.status == WorkflowStatus.COMPLETED


def test_workflow_run_with_steps():
    step1 = WorkflowStep(
        step_id="s-1",
        name="isolate",
        status=StepStatus.COMPLETED,
        outputs={"result": "ok"},
    )
    step2 = WorkflowStep(
        step_id="s-2",
        name="scan",
        status=StepStatus.RUNNING,
    )

    run = WorkflowRun(
        run_id="01HRUN3",
        correlation_id=new_correlation_id(),
        workflow_name="isolate_and_scan",
        idempotency_key="idem-wf-003",
        submitted_by="op@contoso.com",
        status=WorkflowStatus.RUNNING,
        steps=[step1, step2],
    )

    assert len(run.steps) == 2
    assert run.steps[0].status == StepStatus.COMPLETED
    assert run.steps[1].status == StepStatus.RUNNING


def test_workflow_run_failure():
    run = WorkflowRun(
        run_id="01HFAIL",
        correlation_id=new_correlation_id(),
        workflow_name="remediate",
        idempotency_key="idem-wf-fail",
        submitted_by="op@contoso.com",
        status=WorkflowStatus.FAILED,
        error="Plugin timeout after 30s",
    )

    assert run.status == WorkflowStatus.FAILED
    assert run.error == "Plugin timeout after 30s"


def test_workflow_submission():
    sub = WorkflowSubmission(
        workflow_name="isolate",
        inputs={"device_id": "d-1"},
        idempotency_key="idem-sub-001",
        submitted_by="analyst@contoso.com",
        tags={"priority": "high"},
    )

    assert sub.workflow_name == "isolate"
    assert sub.submitted_by == "analyst@contoso.com"
    assert sub.tags == {"priority": "high"}


# ---------------------------------------------------------------------------
# ToolIntent and ToolResult
# ---------------------------------------------------------------------------


def test_tool_intent_creation():
    cid = new_correlation_id()
    intent = ToolIntent(
        intent_id="01HINTENT",
        correlation_id=cid,
        plugin="defender_xdr",
        action="isolate_device",
        inputs={"device_id": "d-42"},
        idempotency_key="idem-ti-001",
        requested_by="orchestrator",
        device_tags=["critical", "production"],
        risk_level="high",
    )

    assert intent.intent_id == "01HINTENT"
    assert intent.plugin == "defender_xdr"
    assert intent.action == "isolate_device"
    assert intent.inputs == {"device_id": "d-42"}
    assert intent.idempotency_key == "idem-ti-001"
    assert intent.requested_by == "orchestrator"
    assert intent.device_tags == ["critical", "production"]
    assert intent.risk_level == "high"
    assert intent.workflow_run_id is None
    assert intent.step_id is None


def test_tool_intent_defaults():
    intent = ToolIntent(
        intent_id="01HINTENT2",
        correlation_id=new_correlation_id(),
        plugin="sentinel",
        action="run_query",
        idempotency_key="idem-ti-002",
        requested_by="user@contoso.com",
    )

    assert intent.inputs == {}
    assert intent.device_tags == []
    assert intent.risk_level is None
    assert intent.workflow_run_id is None


def test_tool_result_success():
    result = ToolResult(
        intent_id="01HINTENT",
        correlation_id=new_correlation_id(),
        status=ToolResultStatus.SUCCESS,
        outputs={"isolated": True},
        duration_ms=350,
    )

    assert result.status == ToolResultStatus.SUCCESS
    assert result.outputs == {"isolated": True}
    assert result.error is None
    assert result.duration_ms == 350
    assert result.artifacts == []


def test_tool_result_failure():
    result = ToolResult(
        intent_id="01HINTENT",
        correlation_id=new_correlation_id(),
        status=ToolResultStatus.FAILURE,
        error="Upstream API returned 503",
    )

    assert result.status == ToolResultStatus.FAILURE
    assert result.error == "Upstream API returned 503"
    assert result.outputs == {}


def test_tool_result_denied():
    result = ToolResult(
        intent_id="01HINTENT",
        correlation_id=new_correlation_id(),
        status=ToolResultStatus.DENIED,
    )

    assert result.status == ToolResultStatus.DENIED


def test_tool_result_statuses():
    assert ToolResultStatus.SUCCESS == "success"
    assert ToolResultStatus.FAILURE == "failure"
    assert ToolResultStatus.DENIED == "denied"
    assert ToolResultStatus.APPROVAL_PENDING == "approval_pending"
    assert ToolResultStatus.IDEMPOTENT_SKIP == "idempotent_skip"


# ---------------------------------------------------------------------------
# PolicyDecision
# ---------------------------------------------------------------------------


def test_policy_decision_allow():
    decision = PolicyDecision(
        verdict=PolicyVerdict.ALLOW,
        rule="allow_read_only",
        reason="Read-only actions are always allowed",
    )

    assert decision.verdict == PolicyVerdict.ALLOW
    assert decision.rule == "allow_read_only"
    assert decision.reason == "Read-only actions are always allowed"
    assert decision.required_approvers == []
    assert decision.context == {}


def test_policy_decision_deny():
    decision = PolicyDecision(
        verdict=PolicyVerdict.DENY,
        rule="deny_production_wipe",
        reason="Cannot wipe production devices",
        context={"device_env": "production"},
    )

    assert decision.verdict == PolicyVerdict.DENY
    assert decision.context == {"device_env": "production"}


def test_policy_decision_require_approval():
    decision = PolicyDecision(
        verdict=PolicyVerdict.REQUIRE_APPROVAL,
        rule="require_approval_critical",
        reason="Critical device requires SOC lead approval",
        required_approvers=["soc-lead", "manager"],
    )

    assert decision.verdict == PolicyVerdict.REQUIRE_APPROVAL
    assert decision.required_approvers == ["soc-lead", "manager"]


def test_policy_verdict_values():
    assert PolicyVerdict.ALLOW == "allow"
    assert PolicyVerdict.DENY == "deny"
    assert PolicyVerdict.REQUIRE_APPROVAL == "require_approval"


# ---------------------------------------------------------------------------
# ApprovalRequest
# ---------------------------------------------------------------------------


def test_approval_request_creation():
    cid = new_correlation_id()
    req = ApprovalRequest(
        approval_id="01HAPPROVAL",
        correlation_id=cid,
        intent_id="01HINTENT",
        plugin="defender_xdr",
        action="isolate_device",
        inputs={"device_id": "d-42"},
        requested_by="orchestrator",
        required_approvers=["soc-lead"],
        policy_reason="Critical device",
    )

    assert req.approval_id == "01HAPPROVAL"
    assert req.correlation_id == cid
    assert req.intent_id == "01HINTENT"
    assert req.plugin == "defender_xdr"
    assert req.action == "isolate_device"
    assert req.status == ApprovalStatus.PENDING
    assert req.required_approvers == ["soc-lead"]
    assert req.policy_reason == "Critical device"
    assert req.decided_by is None
    assert req.decided_at is None
    assert req.decision_reason is None


def test_approval_request_status_transition():
    req = ApprovalRequest(
        approval_id="01HAPPROVAL2",
        correlation_id=new_correlation_id(),
        intent_id="01HINTENT2",
        plugin="sentinel",
        action="run_query",
        requested_by="user@contoso.com",
    )

    assert req.status == ApprovalStatus.PENDING

    req.status = ApprovalStatus.APPROVED
    assert req.status == ApprovalStatus.APPROVED


def test_approval_status_values():
    assert ApprovalStatus.PENDING == "pending"
    assert ApprovalStatus.APPROVED == "approved"
    assert ApprovalStatus.REJECTED == "rejected"
    assert ApprovalStatus.EXPIRED == "expired"


def test_approval_action_values():
    assert ApprovalAction.APPROVE == "approve"
    assert ApprovalAction.REJECT == "reject"


# ---------------------------------------------------------------------------
# new_correlation_id
# ---------------------------------------------------------------------------


def test_new_correlation_id_returns_unique_values():
    ids = {new_correlation_id() for _ in range(100)}
    assert len(ids) == 100, "Expected 100 unique correlation IDs"


def test_new_correlation_id_returns_string():
    cid = new_correlation_id()
    assert isinstance(cid, str)
    assert len(cid) > 0


# ---------------------------------------------------------------------------
# sha256_hex
# ---------------------------------------------------------------------------


def test_sha256_hex_produces_correct_output():
    data = b"hello world"
    expected = hashlib.sha256(data).hexdigest()
    assert sha256_hex(data) == expected


def test_sha256_hex_empty_input():
    data = b""
    expected = hashlib.sha256(data).hexdigest()
    assert sha256_hex(data) == expected


def test_sha256_hex_deterministic():
    data = b"msclaw test data"
    assert sha256_hex(data) == sha256_hex(data)


def test_sha256_hex_returns_hex_string():
    result = sha256_hex(b"test")
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)
