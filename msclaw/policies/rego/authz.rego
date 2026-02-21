# MSClaw Authorization Policy
#
# Evaluates every tool execution request against:
# 1. Role-based access control (RBAC)
# 2. VIP device/user approval gates
# 3. Cloud model PII restrictions
#
# Default: DENY everything. Explicit allow rules required.

package msclaw.authz

import rego.v1

# Default deny
default allow := false
default require_approval := false

# ---------------------------------------------------------------------------
# Role definitions
# ---------------------------------------------------------------------------

# Roles and their allowed actions
role_permissions := {
    "admin": {"*"},
    "operator": {
        "defender_xdr.isolate_device",
        "defender_xdr.unisolate_device",
        "defender_xdr.collect_investigation_package",
        "defender_xdr.run_antivirus_scan",
        "defender_xdr.resolve_device_from_incident",
        "intune.sync_device",
        "intune.assign_asr_policy",
        "entra.revoke_signin_sessions",
        "entra.disable_user",
        "entra.enable_user",
    },
    "viewer": {
        "defender_xdr.resolve_device_from_incident",
    },
    "intune_operator": {
        "intune.sync_device",
        "intune.assign_asr_policy",
    },
}

# ---------------------------------------------------------------------------
# RBAC: Allow based on role
# ---------------------------------------------------------------------------

# Allow if the operator has a role that includes the requested action
allow if {
    some role in input.operator.roles
    perms := role_permissions[role]
    action_allowed(perms, input.action)
}

action_allowed(perms, _) if {
    "*" in perms
}

action_allowed(perms, action) if {
    action in perms
}

# ---------------------------------------------------------------------------
# VIP approval gate
# ---------------------------------------------------------------------------

# Require approval when device is tagged VIP and action is destructive
require_approval if {
    some tag in input.device_tags
    tag == "VIP"
    input.action in vip_approval_actions
}

approval_reason := reason if {
    require_approval
    reason := sprintf("Device is tagged VIP - manual approval required for %s", [input.action])
}

vip_approval_actions := {
    "defender_xdr.isolate_device",
    "defender_xdr.unisolate_device",
    "entra.disable_user",
    "entra.enable_user",
}

# Require approval for all Entra identity actions (high-impact)
require_approval if {
    input.action in entra_approval_actions
}

entra_approval_actions := {
    "entra.revoke_signin_sessions",
    "entra.disable_user",
    "entra.enable_user",
}

# ---------------------------------------------------------------------------
# Cloud model PII restriction
# ---------------------------------------------------------------------------

# Deny sending PII to cloud models unless explicitly approved
deny_reason := reason if {
    input.contains_pii
    reason := "Payload contains device/user identifiers - cloud model usage blocked unless approved"
}

# Override allow to false when PII is present and no approval
allow := false if {
    input.contains_pii
    not input.pii_cloud_approved
}
