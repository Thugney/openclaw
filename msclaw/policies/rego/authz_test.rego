# Tests for MSClaw authorization policy

package msclaw.authz_test

import rego.v1

import data.msclaw.authz

# Test: Admin can do anything
test_admin_allow if {
    authz.allow with input as {
        "operator": {"id": "admin@contoso.com", "roles": ["admin"]},
        "action": "defender_xdr.isolate_device",
        "plugin": "defender_xdr",
        "parameters": {"device_id": "dev-001"},
    }
}

# Test: Operator can isolate devices
test_operator_isolate_allow if {
    authz.allow with input as {
        "operator": {"id": "op@contoso.com", "roles": ["operator"]},
        "action": "defender_xdr.isolate_device",
        "plugin": "defender_xdr",
        "parameters": {"device_id": "dev-001"},
    }
}

# Test: Viewer cannot isolate devices
test_viewer_isolate_deny if {
    not authz.allow with input as {
        "operator": {"id": "viewer@contoso.com", "roles": ["viewer"]},
        "action": "defender_xdr.isolate_device",
        "plugin": "defender_xdr",
        "parameters": {"device_id": "dev-001"},
    }
}

# Test: VIP device requires approval
test_vip_device_approval if {
    authz.require_approval with input as {
        "operator": {"id": "op@contoso.com", "roles": ["operator"]},
        "action": "defender_xdr.isolate_device",
        "plugin": "defender_xdr",
        "parameters": {"device_id": "dev-001"},
        "device_tags": ["VIP", "executive"],
    }
}

# Test: Non-VIP device does not require approval for isolate
test_non_vip_no_approval if {
    not authz.require_approval with input as {
        "operator": {"id": "op@contoso.com", "roles": ["operator"]},
        "action": "defender_xdr.isolate_device",
        "plugin": "defender_xdr",
        "parameters": {"device_id": "dev-001"},
        "device_tags": ["standard"],
    }
}

# Test: Entra actions always require approval
test_entra_revoke_approval if {
    authz.require_approval with input as {
        "operator": {"id": "op@contoso.com", "roles": ["operator"]},
        "action": "entra.revoke_signin_sessions",
        "plugin": "entra",
        "parameters": {"user_id": "user-001"},
    }
}

# Test: PII to cloud model denied
test_pii_cloud_denied if {
    not authz.allow with input as {
        "operator": {"id": "op@contoso.com", "roles": ["operator"]},
        "action": "defender_xdr.isolate_device",
        "plugin": "defender_xdr",
        "parameters": {"device_id": "dev-001"},
        "contains_pii": true,
    }
}

# Test: Intune operator can sync but not isolate
test_intune_operator_sync if {
    authz.allow with input as {
        "operator": {"id": "intune-op@contoso.com", "roles": ["intune_operator"]},
        "action": "intune.sync_device",
        "plugin": "intune",
        "parameters": {"managed_device_id": "md-001"},
    }
}

test_intune_operator_cannot_isolate if {
    not authz.allow with input as {
        "operator": {"id": "intune-op@contoso.com", "roles": ["intune_operator"]},
        "action": "defender_xdr.isolate_device",
        "plugin": "defender_xdr",
        "parameters": {"device_id": "dev-001"},
    }
}
