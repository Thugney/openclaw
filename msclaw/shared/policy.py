"""OPA policy gate – the SINGLE choke point for all tool execution.

No tool-runner action may proceed without a policy decision record from OPA.
The policy decision is stored durably and referenced by its ID.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from .audit import append_audit
from .config import OpaConfig, load_config
from .db import PolicyDecision, get_session

logger = logging.getLogger("msclaw.policy")


class PolicyDenied(Exception):
    """Raised when OPA denies an action."""

    def __init__(self, reasons: list[str], decision_id: uuid.UUID):
        self.reasons = reasons
        self.decision_id = decision_id
        super().__init__(f"Policy denied: {'; '.join(reasons)}")


class ApprovalRequired(Exception):
    """Raised when OPA requires human approval."""

    def __init__(self, reasons: list[str], decision_id: uuid.UUID):
        self.reasons = reasons
        self.decision_id = decision_id
        super().__init__(f"Approval required: {'; '.join(reasons)}")


async def evaluate_policy(
    *,
    actor: str,
    action: str,
    resource: dict[str, Any],
    correlation_id: str | uuid.UUID,
    run_id: str | uuid.UUID | None = None,
    step_id: str | uuid.UUID | None = None,
    session: AsyncSession | None = None,
    opa_cfg: OpaConfig | None = None,
) -> PolicyDecision:
    """Query OPA and persist the decision.

    OPA input schema:
      {
        "input": {
          "actor": "user@example.com",
          "action": "isolate_device",
          "resource": {
            "device_id": "...",
            "device_tags": ["VIP"],
            "incident_id": "..."
          }
        }
      }

    Expected OPA output:
      {
        "result": {
          "allow": true/false,
          "require_approval": true/false,
          "reasons": ["..."]
        }
      }
    """
    if opa_cfg is None:
        opa_cfg = load_config().opa

    opa_input = {
        "input": {
            "actor": actor,
            "action": action,
            "resource": resource,
        }
    }

    try:
        async with httpx.AsyncClient(timeout=opa_cfg.connect_timeout) as client:
            resp = await client.post(
                f"{opa_cfg.url}{opa_cfg.policy_path}",
                json=opa_input,
            )
            resp.raise_for_status()
            opa_result = resp.json().get("result", {})
    except Exception as exc:
        logger.error("OPA evaluation failed: %s", exc)
        # Fail-closed: deny if OPA is unreachable
        opa_result = {
            "allow": False,
            "require_approval": False,
            "reasons": [f"OPA unreachable: {exc}"],
        }

    allow = opa_result.get("allow", False)
    require_approval = opa_result.get("require_approval", False)
    reasons = opa_result.get("reasons", [])

    if require_approval:
        decision_str = "require_approval"
    elif allow:
        decision_str = "allow"
    else:
        decision_str = "deny"

    # Persist decision durably
    decision = PolicyDecision(
        id=uuid.uuid4(),
        correlation_id=correlation_id if isinstance(correlation_id, uuid.UUID) else uuid.UUID(str(correlation_id)),
        run_id=run_id if isinstance(run_id, uuid.UUID) or run_id is None else uuid.UUID(str(run_id)),
        step_id=step_id if isinstance(step_id, uuid.UUID) or step_id is None else uuid.UUID(str(step_id)),
        actor=actor,
        action=action,
        resource=resource,
        decision=decision_str,
        reasons=reasons,
        opa_response=opa_result,
    )

    async def _persist(sess: AsyncSession) -> PolicyDecision:
        sess.add(decision)
        await sess.flush()

        # Audit the policy evaluation
        await append_audit(
            correlation_id=correlation_id,
            run_id=run_id,
            step_id=step_id,
            actor=actor,
            action=f"policy.{decision_str}",
            detail={"opa_input": opa_input, "opa_result": opa_result},
            policy_decision=decision_str,
            session=sess,
        )

        return decision

    if session:
        await _persist(session)
    else:
        async with get_session() as sess:
            await _persist(sess)

    logger.info(
        "Policy decision: %s for %s/%s corr=%s  id=%s",
        decision_str,
        actor,
        action,
        correlation_id,
        decision.id,
    )

    if decision_str == "deny":
        raise PolicyDenied(reasons, decision.id)
    if decision_str == "require_approval":
        raise ApprovalRequired(reasons, decision.id)

    return decision
