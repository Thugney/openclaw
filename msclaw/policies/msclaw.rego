package msclaw

import rego.v1

# Default: deny everything (fail-closed)
default allow := false
default require_approval := false

# ---------------------------------------------------------------------------
# RBAC: role-based allow/deny
# ---------------------------------------------------------------------------

# Roles that can run workflows
allowed_roles := {"admin", "soc_analyst", "incident_responder"}

# Roles that can perform destructive actions
destructive_roles := {"admin", "incident_responder"}

# Actions classified as destructive
destructive_actions := {"isolate_device", "unisolate_device", "restrict_code_execution"}

# Check if actor has an allowed role
actor_role := role if {
    role := input.resource.actor_role
} else := "unknown"

# Allow non-destructive actions for any allowed role
allow if {
    actor_role in allowed_roles
    not input.action in destructive_actions
}

# Allow destructive actions only for destructive roles
allow if {
    actor_role in destructive_roles
    input.action in destructive_actions
    not _device_is_vip
}

# ---------------------------------------------------------------------------
# VIP device tag → requires approval
# ---------------------------------------------------------------------------

_device_tags := tags if {
    tags := input.resource.tags
} else := tags if {
    tags := input.resource.params.tags
} else := []

_device_is_vip if {
    some tag in _device_tags
    tag == "VIP"
}

# Destructive action on VIP device requires approval
require_approval if {
    input.action in destructive_actions
    _device_is_vip
}

# Also require approval for run_workflow when any param mentions VIP
require_approval if {
    input.action == "run_workflow"
    _device_is_vip
}

# ---------------------------------------------------------------------------
# PII / cloud model routing block
# ---------------------------------------------------------------------------

# Fields considered PII
_pii_fields := {"user_email", "user_upn", "device_name", "ip_address", "username"}

_has_pii if {
    some key, _ in input.resource.params
    key in _pii_fields
}

# Block cloud model routing when PII is present (unless approved)
require_approval if {
    input.action == "route_to_model"
    _has_pii
}

# ---------------------------------------------------------------------------
# Reasons (human-readable explanations)
# ---------------------------------------------------------------------------

reasons contains msg if {
    not allow
    not require_approval
    msg := sprintf("Actor role '%s' is not authorized for action '%s'", [actor_role, input.action])
}

reasons contains msg if {
    require_approval
    _device_is_vip
    msg := "VIP device tag detected – human approval required"
}

reasons contains msg if {
    require_approval
    _has_pii
    msg := "PII detected in payload – approval required before cloud model routing"
}

reasons contains msg if {
    allow
    msg := sprintf("Allowed: role '%s' action '%s'", [actor_role, input.action])
}
