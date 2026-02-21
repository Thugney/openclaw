package msclaw_test

import rego.v1

import data.msclaw

# ---------------------------------------------------------------------------
# RBAC tests
# ---------------------------------------------------------------------------

test_soc_analyst_can_run_workflow if {
    msclaw.allow with input as {
        "actor": "analyst@contoso.com",
        "action": "run_workflow",
        "resource": {"actor_role": "soc_analyst", "workflow_name": "contain_device"}
    }
}

test_unknown_role_denied if {
    not msclaw.allow with input as {
        "actor": "guest@contoso.com",
        "action": "run_workflow",
        "resource": {"actor_role": "guest"}
    }
}

test_soc_analyst_cannot_isolate if {
    not msclaw.allow with input as {
        "actor": "analyst@contoso.com",
        "action": "isolate_device",
        "resource": {"actor_role": "soc_analyst", "device_id": "d1"}
    }
}

test_incident_responder_can_isolate_non_vip if {
    msclaw.allow with input as {
        "actor": "responder@contoso.com",
        "action": "isolate_device",
        "resource": {"actor_role": "incident_responder", "device_id": "d1", "tags": ["Standard"]}
    }
}

# ---------------------------------------------------------------------------
# VIP approval tests
# ---------------------------------------------------------------------------

test_vip_device_requires_approval if {
    msclaw.require_approval with input as {
        "actor": "responder@contoso.com",
        "action": "isolate_device",
        "resource": {"actor_role": "incident_responder", "device_id": "d1", "tags": ["VIP"]}
    }
}

test_non_vip_no_approval_needed if {
    not msclaw.require_approval with input as {
        "actor": "responder@contoso.com",
        "action": "isolate_device",
        "resource": {"actor_role": "incident_responder", "device_id": "d1", "tags": ["Standard"]}
    }
}

# ---------------------------------------------------------------------------
# PII routing block tests
# ---------------------------------------------------------------------------

test_pii_requires_approval_for_model_routing if {
    msclaw.require_approval with input as {
        "actor": "analyst@contoso.com",
        "action": "route_to_model",
        "resource": {
            "actor_role": "soc_analyst",
            "params": {"user_email": "victim@contoso.com", "query": "analyze this"}
        }
    }
}

test_no_pii_allows_model_routing if {
    not msclaw.require_approval with input as {
        "actor": "analyst@contoso.com",
        "action": "route_to_model",
        "resource": {
            "actor_role": "soc_analyst",
            "params": {"query": "what are common attack vectors"}
        }
    }
}

# ---------------------------------------------------------------------------
# Reason message tests
# ---------------------------------------------------------------------------

test_denied_has_reason if {
    count(msclaw.reasons) > 0 with input as {
        "actor": "guest@contoso.com",
        "action": "isolate_device",
        "resource": {"actor_role": "guest"}
    }
}

test_vip_has_approval_reason if {
    some reason in msclaw.reasons
    contains(reason, "VIP")
} with input as {
    "actor": "responder@contoso.com",
    "action": "isolate_device",
    "resource": {"actor_role": "incident_responder", "tags": ["VIP"]}
}
