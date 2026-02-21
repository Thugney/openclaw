# MSClaw Model Policy – controls when cloud LLMs can be used
#
# Blocks cloud model usage when the prompt/payload contains
# device or user identifiers (PII) unless explicitly approved.

package msclaw.model_policy

import rego.v1

default allow_cloud := false
default rule := "default_deny_cloud"
default reason := "Cloud model usage denied by default"

# PII indicator fields that should not be sent to cloud models
pii_fields := {"deviceId", "userId", "userPrincipalName", "email", "ipAddress", "macAddress"}

# Check if payload contains PII
payload_has_pii if {
    some field in pii_fields
    input.payload[field]
}

# Allow cloud if no PII in payload
allow_cloud if {
    not payload_has_pii
}

rule := "cloud_no_pii" if {
    not payload_has_pii
}

reason := "Cloud model allowed: no PII detected in payload" if {
    not payload_has_pii
}

# Allow cloud if PII present but explicitly approved
allow_cloud if {
    payload_has_pii
    input.cloud_pii_approved == true
}

rule := "cloud_pii_approved" if {
    payload_has_pii
    input.cloud_pii_approved == true
}

reason := "Cloud model allowed: PII present but approved" if {
    payload_has_pii
    input.cloud_pii_approved == true
}

# Deny with reason if PII detected and not approved
reason := "Cloud model blocked: payload contains device/user identifiers" if {
    payload_has_pii
    not input.cloud_pii_approved
}

rule := "cloud_pii_blocked" if {
    payload_has_pii
    not input.cloud_pii_approved
}
