# MSClaw Tool Policy – evaluated for every tool execution
#
# Default deny: no rule match = deny.
# Three example policies:
# 1. allow/deny based on role
# 2. require approval on VIP-tagged devices
# 3. block cloud model usage when payload contains device/user identifiers

package msclaw.tool_policy

import rego.v1

default verdict := "deny"
default rule := "default_deny"
default reason := "No policy rule matched – default deny"
default required_approvers := []

# ------------------------------------------------------------------
# 1. Role-based allow/deny
# ------------------------------------------------------------------

# Security analysts can run read-only and containment actions
analyst_allowed_actions := {
    "defender_xdr.collect_investigation_package",
    "defender_xdr.run_antivirus_scan",
    "intune.sync_device",
}

# Security leads can run all actions
lead_allowed_actions := analyst_allowed_actions | {
    "defender_xdr.isolate_device",
    "defender_xdr.unisolate_device",
    "intune.assign_asr_policy",
    "entra.revoke_signin_sessions",
    "entra.disable_user",
}

full_action := sprintf("%s.%s", [input.plugin, input.action])

# Allow if user is security-lead and action is in lead set
verdict := "allow" if {
    "security-lead" in input.actor_roles
    full_action in lead_allowed_actions
    not requires_vip_approval
}

rule := "role_lead_allow" if {
    "security-lead" in input.actor_roles
    full_action in lead_allowed_actions
    not requires_vip_approval
}

reason := "Allowed: security-lead role has permission" if {
    "security-lead" in input.actor_roles
    full_action in lead_allowed_actions
    not requires_vip_approval
}

# Allow if user is security-analyst and action is in analyst set
verdict := "allow" if {
    "security-analyst" in input.actor_roles
    full_action in analyst_allowed_actions
    not requires_vip_approval
}

rule := "role_analyst_allow" if {
    "security-analyst" in input.actor_roles
    full_action in analyst_allowed_actions
    not requires_vip_approval
}

reason := "Allowed: security-analyst role has permission" if {
    "security-analyst" in input.actor_roles
    full_action in analyst_allowed_actions
    not requires_vip_approval
}

# ------------------------------------------------------------------
# 2. VIP device approval gate
# ------------------------------------------------------------------

requires_vip_approval if {
    "VIP" in input.device_tags
}

verdict := "require_approval" if {
    requires_vip_approval
    full_action in lead_allowed_actions
}

rule := "vip_approval_required" if {
    requires_vip_approval
    full_action in lead_allowed_actions
}

reason := "Device is tagged VIP – approval required before execution" if {
    requires_vip_approval
    full_action in lead_allowed_actions
}

required_approvers := ["security-lead", "soc-manager"] if {
    requires_vip_approval
}

# ------------------------------------------------------------------
# 3. Always require approval for destructive Entra actions
# ------------------------------------------------------------------

entra_approval_actions := {
    "entra.revoke_signin_sessions",
    "entra.disable_user",
}

verdict := "require_approval" if {
    full_action in entra_approval_actions
    not requires_vip_approval
}

rule := "entra_approval_required" if {
    full_action in entra_approval_actions
    not requires_vip_approval
}

reason := "Entra identity actions always require approval" if {
    full_action in entra_approval_actions
    not requires_vip_approval
}

required_approvers := ["security-lead"] if {
    full_action in entra_approval_actions
    not requires_vip_approval
}

# ------------------------------------------------------------------
# Explicit deny for unknown actions
# ------------------------------------------------------------------

reason := sprintf("Action %s is not recognized or not allowed for roles %v", [full_action, input.actor_roles]) if {
    not full_action in lead_allowed_actions
}
