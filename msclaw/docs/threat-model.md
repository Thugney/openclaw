# MSClaw Threat Model

## Overview

MSClaw is a security operations agent runtime that orchestrates actions across Microsoft cloud services (Defender XDR, Intune, Entra ID). This document identifies the top risks and mitigations.

## Trust Boundaries

```
+---------------------------+
|  Operator (human)         | <- Trust boundary 1: Authentication + RBAC
+---------------------------+
           |
+---------------------------+
|  Control API              | <- Trust boundary 2: Input validation + policy
+---------------------------+
           |
+---------------------------+
|  Orchestrator + LLM       | <- Trust boundary 3: LLM is UNTRUSTED
+---------------------------+
           |
+---------------------------+
|  Policy Gate (OPA)        | <- Trust boundary 4: Policy enforcement
+---------------------------+
           |
+---------------------------+
|  Tool Runner (sandboxed)  | <- Trust boundary 5: Execution isolation
+---------------------------+
           |
+---------------------------+
|  Microsoft APIs           | <- Trust boundary 6: External API boundary
+---------------------------+
```

## Top Risks and Mitigations

### 1. LLM Prompt Injection / Intent Manipulation

**Risk**: An attacker crafts input that causes the LLM to produce malicious tool intents (e.g., isolate the wrong device, disable the wrong user).

**Impact**: HIGH - Unauthorized security actions on production systems.

**Mitigations**:
- LLM output is treated as UNTRUSTED - it produces intents, not commands
- Every intent passes through the OPA policy gate before execution
- High-impact actions require human approval regardless of LLM output
- Audit trail captures what the LLM proposed vs. what was executed
- Intent parameters are validated against strict JSON schemas

### 2. Privilege Escalation via Plugin Actions

**Risk**: An operator with limited permissions finds a way to execute actions outside their role.

**Impact**: HIGH - Unauthorized actions on Microsoft tenant.

**Mitigations**:
- OPA/Rego RBAC policies enforce least privilege per role
- Default deny: actions not explicitly allowed are blocked
- Tool runner only executes allowlisted plugin actions
- Plugin permissions are documented and minimized per action
- Audit trail captures the operator identity for every action

### 3. Token/Secret Exfiltration

**Risk**: Microsoft Graph tokens or client secrets are leaked through logs, LLM context, or artifact storage.

**Impact**: CRITICAL - Full access to Microsoft tenant APIs.

**Mitigations**:
- Tokens are short-lived and acquired per-job
- Secrets are never passed to the LLM or included in audit logs
- Client secrets stored in tenant.json (excluded from version control)
- Environment variable overrides for CI/CD (no file-based secrets)
- PII/secret detection blocks sensitive data from cloud model providers

### 4. Audit Log Tampering

**Risk**: An attacker modifies or deletes audit entries to cover their tracks.

**Impact**: HIGH - Loss of forensic evidence.

**Mitigations**:
- Append-only audit ledger (no UPDATE/DELETE operations)
- Hash chain links each entry to the previous one (tamper-evident)
- Chain verification can detect any modification
- Separate audit service with restricted access
- Database-level audit (Postgres triggers) as secondary control

### 5. Idempotency Bypass / Double Execution

**Risk**: A device is isolated twice, or a user is disabled when already disabled, causing operational disruption.

**Impact**: MEDIUM - Operational confusion, potential service disruption.

**Mitigations**:
- Every action requires a unique idempotency key
- Duplicate keys return cached results without re-execution
- Plugins implement CHECK_AND_APPLY strategy (check state before acting)
- Idempotency records are stored persistently (survive restarts)

### 6. Policy Gate Bypass

**Risk**: Tool execution occurs without policy evaluation (e.g., OPA is down or misconfigured).

**Impact**: HIGH - Unauthorized actions executed without policy check.

**Mitigations**:
- Default deny when OPA is unreachable
- Health checks verify OPA connectivity before accepting workflows
- Policy evaluation failure is logged and blocks execution
- Rego policy tests run in CI (prevent broken policy deploys)

### 7. Cross-Tenant Attack

**Risk**: MSClaw is misconfigured to target the wrong Azure tenant.

**Impact**: CRITICAL - Actions executed against unintended tenant.

**Mitigations**:
- Tenant ID is explicitly configured in tenant.json
- Token scopes are bound to the configured tenant
- Startup validation confirms tenant ID matches expected value
- All API calls include tenant-bound tokens (cannot cross tenants)

### 8. Network-Level Attacks (MITM, Replay)

**Risk**: API calls between MSClaw services or to Microsoft APIs are intercepted.

**Impact**: HIGH - Token theft, action replay.

**Mitigations**:
- HTTPS for all Microsoft API calls
- NATS supports TLS for inter-service communication
- Idempotency keys prevent replay attacks
- Correlation IDs enable detection of duplicate/replayed requests

### 9. Denial of Service via Workflow Flooding

**Risk**: Attacker submits thousands of workflows to overwhelm the system.

**Impact**: MEDIUM - Operational disruption.

**Mitigations**:
- Rate limiting at the Control API layer
- RBAC restricts workflow submission to authenticated operators
- Queue-based architecture provides natural backpressure
- Budget limits on cloud model usage prevent cost explosion

### 10. Insecure Dev Mode in Production

**Risk**: Dev mode (with mock responses) is accidentally deployed to production.

**Impact**: HIGH - Security actions appear to succeed but do nothing.

**Mitigations**:
- dev_mode flag must be explicitly set in config
- Startup logs clearly indicate when dev mode is active
- CI pipeline validates that production configs have dev_mode=false
- Audit entries include whether the action was mocked

## STRIDE Summary

| Threat | Category | Risk | Primary Mitigation |
|--------|----------|------|--------------------|
| LLM prompt injection | Spoofing/Tampering | HIGH | Policy gate + human approval |
| Privilege escalation | Elevation of Privilege | HIGH | OPA RBAC + default deny |
| Token exfiltration | Information Disclosure | CRITICAL | Short-lived tokens + PII blocking |
| Audit tampering | Tampering | HIGH | Hash chain + append-only |
| Idempotency bypass | Tampering | MEDIUM | Idempotency keys + state checks |
| Policy gate bypass | Elevation of Privilege | HIGH | Default deny + health checks |
| Cross-tenant attack | Spoofing | CRITICAL | Explicit tenant binding |
| Network MITM | Information Disclosure | HIGH | TLS + idempotency |
| Workflow flooding | Denial of Service | MEDIUM | Rate limiting + RBAC |
| Dev mode in prod | Information Disclosure | HIGH | Config validation + CI checks |
