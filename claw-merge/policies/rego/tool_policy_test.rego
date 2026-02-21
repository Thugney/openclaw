# Tests for MSClaw tool policy

package msclaw.tool_policy_test

import rego.v1
import data.msclaw.tool_policy

# Test: security-lead can isolate a non-VIP device
test_lead_isolate_non_vip if {
    result := tool_policy with input as {
        "plugin": "defender_xdr",
        "action": "isolate_device",
        "inputs": {"deviceId": "device123"},
        "requested_by": "admin@contoso.com",
        "actor_roles": ["security-lead"],
        "device_tags": [],
        "risk_level": "high"
    }
    result.verdict == "allow"
}

# Test: security-analyst cannot isolate device
test_analyst_cannot_isolate if {
    result := tool_policy with input as {
        "plugin": "defender_xdr",
        "action": "isolate_device",
        "inputs": {"deviceId": "device123"},
        "requested_by": "analyst@contoso.com",
        "actor_roles": ["security-analyst"],
        "device_tags": [],
        "risk_level": "high"
    }
    result.verdict == "deny"
}

# Test: VIP device requires approval even for lead
test_vip_requires_approval if {
    result := tool_policy with input as {
        "plugin": "defender_xdr",
        "action": "isolate_device",
        "inputs": {"deviceId": "vip-device"},
        "requested_by": "admin@contoso.com",
        "actor_roles": ["security-lead"],
        "device_tags": ["VIP"],
        "risk_level": "high"
    }
    result.verdict == "require_approval"
}

# Test: Entra disable_user always requires approval
test_entra_disable_requires_approval if {
    result := tool_policy with input as {
        "plugin": "entra",
        "action": "disable_user",
        "inputs": {"userId": "user123"},
        "requested_by": "admin@contoso.com",
        "actor_roles": ["security-lead"],
        "device_tags": [],
        "risk_level": null
    }
    result.verdict == "require_approval"
}

# Test: unknown action is denied
test_unknown_action_denied if {
    result := tool_policy with input as {
        "plugin": "unknown",
        "action": "do_something",
        "inputs": {},
        "requested_by": "admin@contoso.com",
        "actor_roles": ["security-lead"],
        "device_tags": [],
        "risk_level": null
    }
    result.verdict == "deny"
}
