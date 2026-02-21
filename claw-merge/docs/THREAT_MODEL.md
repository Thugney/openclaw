# MSClaw Threat Model

**Document Version:** 1.0
**Date:** 2026-02-21
**Classification:** Internal — Security Sensitive
**Owner:** MSClaw Security Team

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Trust Boundaries](#2-trust-boundaries)
3. [Top Threats (STRIDE)](#3-top-threats-stride)
4. [Data Flow Analysis](#4-data-flow-analysis)
5. [Authentication & Authorization Risks](#5-authentication--authorization-risks)
6. [LLM-Specific Risks](#6-llm-specific-risks)
7. [Supply Chain Risks](#7-supply-chain-risks)
8. [Residual Risks and Accepted Trade-offs](#8-residual-risks-and-accepted-trade-offs)
9. [Recommendations for Production Hardening](#9-recommendations-for-production-hardening)

---

## 1. System Overview

MSClaw is a security-operations agent runtime that orchestrates LLM-driven workflows to automate defensive security tasks across Microsoft environments. Human operators submit workflows through a control API. An orchestrator decomposes those workflows into TOOL-INTENT messages, which are evaluated against OPA policies before execution in a sandboxed tool-runner. All actions are recorded in a tamper-evident audit ledger.

### Core Components

| Component | Role |
|---|---|
| **control-api** | FastAPI service handling authentication, RBAC, and workflow submission |
| **orchestrator** | Workflow engine that interprets operator goals and produces TOOL-INTENT messages |
| **model-router** | Routes inference requests to local Ollama instances with optional cloud LLM fallback |
| **tool-runner** | Executes approved tool calls inside a sandboxed environment |
| **audit-service** | Append-only, tamper-evident ledger of all actions and decisions |
| **OPA policy gate** | Evaluates every TOOL-INTENT against Rego policies before execution |
| **Microsoft plugins** | Integrations with Defender XDR, Intune, and Entra ID |
| **Infrastructure** | NATS (message bus), PostgreSQL (state), MinIO (artifact storage) |

### Key Security Invariants

- No tool executes without passing OPA policy evaluation.
- Every action is recorded in the audit ledger before execution.
- Human approval is required for destructive or high-impact operations.
- LLM inference defaults to local models; cloud fallback requires explicit opt-in and data scrubbing.

---

## 2. Trust Boundaries

```
                          TRUST BOUNDARY: External Network
 +==========================================================================+
 |                                                                          |
 |   [Operator Browser / CLI]                                               |
 |          |                                                               |
 +==========|===============================================================+
            | HTTPS/mTLS (TB-1)
 +==========|===============================================================+
 |  TRUST BOUNDARY: DMZ / API Gateway                                      |
 |          |                                                               |
 |   +------v--------+                                                      |
 |   | control-api   |--- JWT/OIDC auth, RBAC enforcement                  |
 |   | (FastAPI)     |                                                      |
 |   +------+--------+                                                      |
 |          |                                                               |
 +==========|===============================================================+
            | NATS (TB-2: Internal Service Mesh)
 +==========|===============================================================+
 |  TRUST BOUNDARY: Internal Services                                      |
 |          |                                                               |
 |   +------v--------+      +----------------+      +------------------+   |
 |   | orchestrator  |----->| OPA policy     |----->| tool-runner      |   |
 |   | (workflow     |      | gate           |      | (sandboxed exec) |   |
 |   |  engine)      |      +----------------+      +--------+---------+   |
 |   +------+--------+                                       |             |
 |          |                                                 |             |
 |   +------v--------+                               +-------v---------+  |
 |   | model-router  |                               | audit-service   |  |
 |   +---+-------+---+                               | (append-only    |  |
 |       |       |                                    |  ledger)        |  |
 |       |       |                                    +-----------------+  |
 +=======|=======|==========================================================+
         |       | (TB-3: Model Inference Boundary)
   +-----v--+ +-v-----------------+
   | Ollama | | Cloud LLM API    |
   | (local)| | (optional, TB-4) |
   +--------+ +------------------+

 +=========================================================================+
 |  TRUST BOUNDARY: Microsoft Tenant (TB-5)                                |
 |                                                                         |
 |   +-----------------+  +-----------+  +------------------+              |
 |   | Defender XDR    |  | Intune    |  | Entra ID         |              |
 |   +-----------------+  +-----------+  +------------------+              |
 +=========================================================================+

 +=========================================================================+
 |  TRUST BOUNDARY: Persistent Storage (TB-6)                              |
 |                                                                         |
 |   +-----------------+  +-----------------+                              |
 |   | PostgreSQL      |  | MinIO           |                              |
 |   +-----------------+  +-----------------+                              |
 +=========================================================================+
```

### Trust Boundary Descriptions

| ID | Boundary | What Crosses It |
|---|---|---|
| TB-1 | External to API Gateway | Operator requests, credentials |
| TB-2 | API Gateway to Internal Services | Authenticated workflow commands via NATS |
| TB-3 | Internal Services to Model Inference | Prompts containing security context, incident data |
| TB-4 | Local Inference to Cloud Fallback | Potentially sensitive prompts leaving infrastructure |
| TB-5 | Internal Services to Microsoft Tenant | API calls carrying privileged service-principal credentials |
| TB-6 | Services to Persistent Storage | Workflow state, audit records, artifacts |

---

## 3. Top Threats (STRIDE)

### Spoofing

#### T-01: Stolen or Forged JWT Allows Unauthorized Workflow Submission

| Attribute | Detail |
|---|---|
| **Description** | An attacker obtains or forges a valid JWT and submits malicious workflows through the control-api, impersonating a legitimate operator. |
| **Impact** | **Critical.** Attacker can trigger destructive security actions (isolate hosts, revoke access) across the Microsoft tenant. |
| **Likelihood** | Medium. Requires token theft (phishing, log exposure) or weak signing key. |
| **Mitigations** | Short-lived JWTs (15 min max). Rotate signing keys on schedule. Bind tokens to client IP or fingerprint. Require MFA at OIDC provider. Monitor for token reuse from anomalous locations. |

#### T-02: Service Impersonation on NATS Bus

| Attribute | Detail |
|---|---|
| **Description** | A rogue process connects to NATS and publishes crafted TOOL-INTENT messages, bypassing the orchestrator. |
| **Impact** | **Critical.** Direct tool execution with arbitrary parameters if OPA does not catch the spoofed origin. |
| **Likelihood** | Low-Medium. Requires network access to the NATS cluster. |
| **Mitigations** | NATS authentication with per-service NKeys or client certificates. Subject-level authorization so only the orchestrator can publish to tool-intent subjects. OPA policies must validate message origin claims. Network segmentation to restrict NATS access. |

---

### Tampering

#### T-03: Audit Log Manipulation

| Attribute | Detail |
|---|---|
| **Description** | An attacker with database access modifies or deletes audit records to cover tracks after a malicious action. |
| **Impact** | **High.** Loss of forensic trail. Compliance violations. Inability to detect and investigate incidents. |
| **Likelihood** | Low. Requires privileged database credentials. |
| **Mitigations** | Append-only table design with database-level constraints (no UPDATE/DELETE grants). Hash-chained log entries (each record includes a hash of the previous record). Replicate audit stream to an independent, immutable store (e.g., separate S3 bucket with Object Lock). Separate credentials for audit-service with minimal privileges. |

#### T-04: OPA Policy Tampering

| Attribute | Detail |
|---|---|
| **Description** | An attacker modifies Rego policy bundles to weaken or disable tool-call restrictions, allowing dangerous operations to pass unchecked. |
| **Impact** | **Critical.** Complete bypass of the authorization layer for tool execution. |
| **Likelihood** | Low. Requires access to policy storage or the bundle distribution mechanism. |
| **Mitigations** | Sign OPA policy bundles and verify signatures at load time. Store policies in version-controlled repository with mandatory code review. Restrict filesystem and API access to OPA's policy directory. Alert on any policy reload events. |

---

### Repudiation

#### T-05: Operator Denies Initiating a Destructive Action

| Attribute | Detail |
|---|---|
| **Description** | An operator triggers a high-impact action (e.g., mass device wipe via Intune) and later denies responsibility. Without strong non-repudiation, accountability cannot be established. |
| **Impact** | **Medium.** Organizational and legal risk. Undermines trust in the platform. |
| **Likelihood** | Medium. Especially relevant in multi-operator environments with shared accounts. |
| **Mitigations** | Bind every workflow submission to an authenticated identity with audit-service recording the full chain: operator identity, timestamp, workflow definition, every TOOL-INTENT, and execution result. Require human-in-the-loop confirmation for destructive actions with the confirmation itself logged. Prohibit shared accounts. |

---

### Information Disclosure

#### T-06: Sensitive Security Data Leaked to Cloud LLM Provider

| Attribute | Detail |
|---|---|
| **Description** | When the model-router falls back to a cloud LLM, prompts containing incident details, IOCs, internal hostnames, credentials, or PII are transmitted to a third-party API. |
| **Impact** | **High.** Exposure of confidential security data. Potential compliance violations (GDPR, internal policy). Data may be logged or used for training by the cloud provider. |
| **Likelihood** | Medium. Occurs whenever local inference is unavailable or insufficient and fallback is enabled. |
| **Mitigations** | Default to local Ollama inference. Require explicit per-workflow opt-in for cloud fallback. Implement a scrubbing layer in model-router that strips hostnames, IPs, credentials, and PII before sending to cloud. Negotiate a zero-data-retention agreement with the cloud LLM provider. Log every cloud fallback event for review. |

#### T-07: Credential Exposure in Logs or MinIO Artifacts

| Attribute | Detail |
|---|---|
| **Description** | Microsoft service-principal secrets, API keys, or user credentials end up in workflow logs, NATS messages, or MinIO-stored artifacts in cleartext. |
| **Impact** | **High.** Credential theft enables lateral movement into the Microsoft tenant. |
| **Likelihood** | Medium. Common in systems that log full request/response bodies. |
| **Mitigations** | Never include raw credentials in TOOL-INTENT payloads; use credential references resolved at execution time by the tool-runner. Implement log-scrubbing filters for known secret patterns. Encrypt MinIO artifacts at rest with managed keys. Regularly scan stored artifacts for credential patterns. |

---

### Denial of Service

#### T-08: Workflow Bomb Exhausts System Resources

| Attribute | Detail |
|---|---|
| **Description** | A compromised or malicious operator submits a workflow that spawns an excessive number of TOOL-INTENT messages, overwhelming the orchestrator, NATS, or tool-runner and starving legitimate operations. |
| **Impact** | **High.** Platform unavailability during an active security incident when it is most needed. |
| **Likelihood** | Medium. Any authenticated operator can submit workflows. |
| **Mitigations** | Per-operator rate limits on workflow submissions at the control-api. Maximum TOOL-INTENT count per workflow enforced by the orchestrator. NATS subject-level rate limiting. Tool-runner concurrency caps and per-execution timeouts. Circuit breakers on downstream Microsoft API calls to prevent cascading failures. |

---

### Elevation of Privilege

#### T-09: Prompt Injection Escalates Tool Permissions

| Attribute | Detail |
|---|---|
| **Description** | Attacker-controlled data ingested during a workflow (e.g., a malicious alert description from Defender XDR, a crafted device name in Intune) manipulates the LLM into generating TOOL-INTENT messages that exceed the operator's authorized scope. |
| **Impact** | **Critical.** Arbitrary tool execution with the platform's full service-principal permissions, not limited to the operator's RBAC role. |
| **Likelihood** | Medium-High. Prompt injection is a well-documented and difficult-to-fully-prevent attack vector in LLM-integrated systems. |
| **Mitigations** | OPA policy gate must enforce operator-scoped permissions on every TOOL-INTENT regardless of how it was generated. Never trust LLM output as pre-authorized. Treat all LLM-generated TOOL-INTENTs as untrusted input. Human approval gate for any action outside the operator's normal scope. Structured output parsing (do not execute free-text LLM output as commands). Input sanitization on all data ingested from Microsoft APIs before including in prompts. |

#### T-10: Tool-Runner Sandbox Escape

| Attribute | Detail |
|---|---|
| **Description** | A crafted tool payload exploits a vulnerability in the sandbox environment (container escape, mount traversal) to gain access to the host system or other containers. |
| **Impact** | **Critical.** Full host compromise. Access to NATS, Postgres, MinIO, and Microsoft credentials. |
| **Likelihood** | Low. Requires an exploitable sandbox vulnerability. |
| **Mitigations** | Run tool-runner in gVisor or Firecracker-based microVMs rather than standard containers. Apply seccomp and AppArmor profiles. Drop all capabilities except those explicitly required. Read-only root filesystem. No host network access. Separate tool-runner onto dedicated nodes with no co-located services. Regularly patch container runtime and kernel. |

#### T-11: RBAC Bypass via Direct Database Manipulation

| Attribute | Detail |
|---|---|
| **Description** | An attacker with PostgreSQL access modifies role assignments or permission tables directly, granting themselves elevated privileges that bypass the control-api's RBAC logic. |
| **Impact** | **High.** Unauthorized access to privileged workflows and tools. |
| **Likelihood** | Low. Requires database credentials. |
| **Mitigations** | Restrict database access to service accounts only (no human interactive access). Use separate database credentials per service with minimal grants. Implement row-level security in PostgreSQL. Alert on direct DDL/DML changes to RBAC tables outside the control-api. Keep database on a network segment inaccessible from operator workstations. |

#### T-12: Microsoft Service Principal Over-Permissioning

| Attribute | Detail |
|---|---|
| **Description** | The service principal used by MSClaw plugins has broader Microsoft Graph / Defender / Intune permissions than required. If any component is compromised, the blast radius includes the full permission set. |
| **Impact** | **Critical.** A compromised component can perform any action the over-permissioned service principal allows across the entire Microsoft tenant. |
| **Likelihood** | Medium. Over-permissioning is common during initial setup and often persists. |
| **Mitigations** | Apply least-privilege to the service principal. Use separate service principals per plugin (Defender, Intune, Entra) with only the permissions each requires. Use application-level permissions rather than delegated where possible. Conduct quarterly access reviews. Implement Conditional Access policies on service principal sign-ins. |

---

## 4. Data Flow Analysis

### 4.1 Workflow Submission Flow

```
Operator --> [HTTPS/mTLS] --> control-api --> [JWT validation, RBAC check]
    --> PostgreSQL (persist workflow definition)
    --> NATS (publish workflow-submitted event)
    --> orchestrator (consumes event)
```

**Sensitive data in transit:** Operator credentials (JWT), workflow definition (may reference targets by hostname/IP).

**Controls:** TLS everywhere. JWT validation at ingress. Workflow definition stored encrypted at rest in PostgreSQL.

### 4.2 Tool Execution Flow

```
orchestrator --> [TOOL-INTENT via NATS] --> OPA policy gate
    --> [ALLOW/DENY decision]
    --> IF ALLOW: tool-runner receives TOOL-INTENT
        --> tool-runner resolves credentials from vault
        --> tool-runner executes in sandbox
        --> tool-runner publishes TOOL-RESULT via NATS
        --> audit-service records INTENT + RESULT
    --> IF DENY: audit-service records INTENT + DENY reason
```

**Sensitive data in transit:** TOOL-INTENT parameters (target hosts, query filters), TOOL-RESULT payloads (alert data, device info, user records).

**Controls:** NATS TLS + authentication. OPA evaluation before execution. Credential resolution at execution time only. Audit of all decisions.

### 4.3 LLM Inference Flow

```
orchestrator --> model-router --> [Decision: local or cloud?]
    --> IF LOCAL: Ollama (prompt stays on-premises)
    --> IF CLOUD: scrubbing layer --> cloud LLM API (HTTPS)
                  <-- response
```

**Sensitive data in transit:** Prompts contain security context derived from Microsoft telemetry. Responses contain tool-call recommendations.

**Controls:** Local-first routing. Data scrubbing before cloud transmission. No credential material in prompts.

### 4.4 Data at Rest

| Store | Data | Sensitivity | Encryption |
|---|---|---|---|
| PostgreSQL | Workflow state, RBAC tables, operational metadata | High | AES-256 TDE, column-level encryption for secrets |
| MinIO | Workflow artifacts, tool output snapshots | High | SSE-S3 or SSE-KMS |
| Audit ledger (PostgreSQL) | Complete action history | Critical | AES-256 TDE, hash-chain integrity |
| NATS JetStream | In-flight and persisted messages | High | TLS in transit, encrypted volumes at rest |

---

## 5. Authentication & Authorization Risks

### 5.1 Authentication Architecture

- **Operator authentication:** OIDC (via Entra ID) with JWT bearer tokens at the control-api.
- **Service-to-service authentication:** NATS NKeys or mTLS client certificates.
- **Microsoft API authentication:** OAuth 2.0 client-credentials flow with service principals.
- **Database authentication:** Per-service credentials stored in a secrets manager.

### 5.2 Identified Risks

| Risk | Description | Severity |
|---|---|---|
| **Single OIDC provider dependency** | If the Entra ID tenant is compromised, all operator authentication is compromised. | High |
| **Long-lived service principal secrets** | Microsoft service principal client secrets have long validity periods by default (up to 2 years). | High |
| **JWT scope inflation** | JWTs may carry broad scopes that are not narrowed per-workflow. A single token authorizes all actions within the role. | Medium |
| **No step-up authentication** | Destructive operations use the same authentication level as read-only queries. No re-authentication or step-up MFA for high-impact actions. | Medium |
| **Credential sprawl** | Multiple credential types (JWTs, NKeys, client secrets, database passwords) across services increase the attack surface. | Medium |
| **RBAC role explosion** | Insufficient role granularity may lead to over-permissioned operators, or excessive roles that are difficult to audit. | Low-Medium |

### 5.3 Mitigations

- Implement step-up authentication (re-prompt MFA) for destructive workflow actions.
- Use managed identities or certificate-based credentials for Microsoft service principals instead of client secrets.
- Scope JWTs to specific workflow types or target sets where possible.
- Centralize credential management in a secrets vault (e.g., HashiCorp Vault) with automatic rotation.
- Conduct quarterly RBAC reviews with role-to-permission mapping audits.
- Implement break-glass procedures with separate, heavily monitored credentials for emergency access.

---

## 6. LLM-Specific Risks

### 6.1 Prompt Injection

| Variant | Description | Mitigation |
|---|---|---|
| **Direct injection** | Operator crafts a workflow description that manipulates the LLM into generating unauthorized TOOL-INTENTs. | OPA policy gate blocks out-of-scope tool calls regardless of LLM output. Structured output parsing rejects malformed intents. |
| **Indirect injection** | Attacker places malicious content in Microsoft telemetry (e.g., a crafted alert description or device name) that gets included in the LLM prompt and manipulates its behavior. | Sanitize all external data before prompt inclusion. Use delimiter tokens to separate system instructions from external data. Monitor for anomalous TOOL-INTENT patterns. |
| **Recursive injection** | A TOOL-RESULT returned from execution contains adversarial content that influences subsequent LLM reasoning in a multi-step workflow. | Sanitize TOOL-RESULT data before feeding back into LLM context. Limit multi-step workflow depth. Apply output validation at each step. |

### 6.2 Model Manipulation

| Risk | Description | Mitigation |
|---|---|---|
| **Model poisoning (Ollama)** | A compromised model file causes the LLM to systematically produce dangerous tool calls or exfiltrate data via tool parameters. | Verify model checksums against known-good hashes. Pull models only from trusted registries. Sign and verify model files. Monitor for statistical anomalies in model output patterns. |
| **Model confusion** | An ambiguous workflow causes the LLM to misinterpret intent and produce unintended but syntactically valid TOOL-INTENTs. | Always require structured output schemas. Implement semantic validation of TOOL-INTENTs against the workflow definition. Human review for high-impact actions. |

### 6.3 Data Leakage to Cloud

| Risk | Description | Mitigation |
|---|---|---|
| **Prompt leakage** | Security-sensitive data (IOCs, internal IPs, credentials, alert context) sent to cloud LLM providers. | Local-first inference. Mandatory data scrubbing layer. Classify prompt content and block cloud routing for prompts above a sensitivity threshold. |
| **Context window accumulation** | Over the course of a multi-step workflow, the LLM context accumulates a comprehensive picture of the security environment that, if leaked, constitutes a detailed reconnaissance report. | Limit context window growth. Summarize rather than carry forward raw data between steps. Clear context between unrelated workflows. |
| **Cloud provider logging** | Even with zero-retention agreements, prompts may be transiently logged by the cloud provider for operational purposes. | Prefer providers with verified zero-retention and no-training guarantees. Encrypt prompts client-side where provider supports it. Accept residual risk (see Section 8). |

---

## 7. Supply Chain Risks

### 7.1 Software Dependencies

| Risk | Description | Mitigation |
|---|---|---|
| **Compromised Python packages** | Malicious code in a PyPI dependency of the control-api, orchestrator, or other Python services. | Pin all dependencies with hashes in requirements files. Use private PyPI mirror with vulnerability scanning. Run `pip-audit` or equivalent in CI. Enable Dependabot/Renovate for automated CVE alerts. |
| **Compromised container base images** | A backdoored or vulnerable base image propagates to all services. | Use minimal, distroless base images. Pin image digests, not tags. Scan images with Trivy or Grype in CI pipeline. Rebuild images on a regular schedule to pick up base image patches. |
| **Ollama model supply chain** | Model files downloaded from public registries may be tampered with or backdoored. | Verify model checksums. Mirror models to a private registry. Audit model provenance. Test model outputs against known-good baselines before deployment. |
| **OPA/Rego policy dependencies** | If Rego policies import external data or bundles from untrusted sources. | Self-host all OPA bundles. Sign bundles. Review all policy changes through standard code review. |

### 7.2 Infrastructure Dependencies

| Risk | Description | Mitigation |
|---|---|---|
| **NATS vulnerability** | A vulnerability in the NATS server allows message interception or service disruption. | Pin NATS server version. Subscribe to NATS security advisories. Run NATS with minimal configuration. Network-segment NATS to internal services only. |
| **PostgreSQL vulnerability** | SQL injection or authentication bypass in the database engine. | Parameterized queries only (enforced by ORM). Patch PostgreSQL on a regular cadence. Restrict network access to database ports. |
| **MinIO vulnerability** | Object storage compromise exposes workflow artifacts. | Keep MinIO updated. Use IAM policies to restrict bucket access per service. Enable versioning and object lock on audit-related buckets. |

### 7.3 CI/CD Pipeline

| Risk | Description | Mitigation |
|---|---|---|
| **Build pipeline compromise** | An attacker injects malicious code during the build process. | Require signed commits. Enforce branch protection and mandatory reviews. Use isolated build environments. Sign container images and verify signatures at deployment. Generate and store SBOMs for each release. |

---

## 8. Residual Risks and Accepted Trade-offs

The following risks are acknowledged and accepted as residual after all practical mitigations are applied.

### 8.1 Accepted Residual Risks

| Risk | Rationale for Acceptance |
|---|---|
| **Prompt injection cannot be fully eliminated** | LLMs are inherently susceptible to prompt injection. OPA policy enforcement provides a hard backstop, but the LLM may still produce unexpected intermediate reasoning. Accepted because OPA + human-in-the-loop for destructive actions bounds the blast radius. |
| **Cloud LLM transient data exposure** | Even with zero-retention agreements, data may be transiently processed in the cloud provider's infrastructure. Accepted because cloud fallback is opt-in, scrubbing is applied, and the alternative (no fallback) degrades availability during local model failures. |
| **Insider threat from platform administrators** | A platform administrator with access to Kubernetes, databases, and secrets can bypass all application-level controls. Accepted because mitigating this fully requires hardware security modules and multi-party authorization that may be disproportionate to the operational environment. Compensating control: comprehensive audit logging. |
| **Zero-day in sandbox runtime** | A container or microVM escape via an unknown vulnerability. Accepted because the likelihood is low and mitigated by defense in depth (network segmentation, minimal permissions, separate nodes). |
| **Microsoft API behavioral changes** | Microsoft may change API behavior, rate limits, or permission models without notice, potentially causing unexpected tool-runner failures or permission errors. Accepted because this is outside MSClaw's control. Compensating control: integration tests and monitoring. |

### 8.2 Trade-offs

| Trade-off | Decision |
|---|---|
| **Security vs. Latency** | OPA evaluation on every TOOL-INTENT adds latency (~5-20ms). Accepted because the security benefit far outweighs the performance cost in a security-operations context where correctness matters more than speed. |
| **Local-only vs. Cloud fallback** | Pure local inference eliminates data leakage risk but reduces availability and model capability. The opt-in cloud fallback with scrubbing is a deliberate compromise. |
| **Append-only audit vs. Storage growth** | The audit ledger grows unboundedly. Accepted because audit integrity is paramount. Mitigated by tiered storage (hot/warm/cold) and retention policies for non-compliance-critical records. |
| **Granular RBAC vs. Operational agility** | Fine-grained RBAC increases friction for operators responding to active incidents. Mitigated by well-designed role hierarchies and break-glass procedures rather than loosening default permissions. |

---

## 9. Recommendations for Production Hardening

### 9.1 Critical (Implement Before Production)

1. **Enable mTLS everywhere.** All service-to-service communication (NATS, PostgreSQL, MinIO, OPA) must use mutual TLS with certificate rotation via a private CA.

2. **Deploy OPA policy bundle signing.** Sign all Rego bundles and configure OPA to reject unsigned or tampered bundles. A policy bypass is a complete security failure.

3. **Implement hash-chained audit log.** Each audit record must include a cryptographic hash of the previous record. Provide an independent verification tool that can validate chain integrity.

4. **Harden the tool-runner sandbox.** Deploy gVisor (runsc) or Firecracker as the sandbox runtime. Apply seccomp profiles, drop all Linux capabilities, enforce read-only root filesystems, and disable host networking.

5. **Enforce human-in-the-loop for destructive actions.** Any TOOL-INTENT classified as destructive (device isolation, account disable, policy push, data wipe) must require explicit operator confirmation through a separate authenticated channel.

6. **Rotate and vault all credentials.** Move all service principal secrets, database passwords, NATS credentials, and API keys into a secrets manager (e.g., HashiCorp Vault) with automatic rotation. No credentials in environment variables or config files.

### 9.2 High Priority (Implement Within First Sprint Post-Launch)

7. **Deploy network segmentation.** Place each component tier in a separate network segment. The tool-runner should be on an isolated network with egress restricted to only the Microsoft API endpoints and the NATS bus.

8. **Implement cloud fallback data scrubbing.** Build and test the scrubbing layer in model-router that removes hostnames, IP addresses, credential fragments, and PII before any prompt is sent to a cloud LLM. Maintain a deny-list of patterns that trigger automatic blocking.

9. **Enable rate limiting and circuit breakers.** Apply per-operator rate limits at the control-api. Implement circuit breakers on all Microsoft API calls with backoff. Set maximum TOOL-INTENT counts per workflow.

10. **Set up anomaly detection on TOOL-INTENT patterns.** Baseline normal TOOL-INTENT generation rates and types. Alert when a workflow generates an unusually high number of intents, targets unusual resources, or the LLM output diverges from expected patterns.

### 9.3 Standard Priority (Implement Within 90 Days)

11. **Implement SBOM generation and scanning.** Generate Software Bills of Materials for every release. Continuously scan SBOMs against vulnerability databases. Automate alerts for critical CVEs in dependencies.

12. **Conduct red team exercise.** Engage an internal or external red team to test prompt injection attacks, sandbox escape, NATS message spoofing, and credential theft scenarios against the deployed system.

13. **Deploy canary audit records.** Periodically insert known canary records into the audit ledger and verify their integrity. Alert immediately if a canary record is modified or missing.

14. **Implement break-glass monitoring.** Create a separate, heavily monitored authentication path for emergency access that bypasses normal RBAC. Log all break-glass usage and require post-incident review.

15. **Establish runbook for credential compromise.** Document and drill procedures for rotating all credentials (Microsoft service principals, NATS NKeys, database passwords, JWT signing keys) within a target window of 30 minutes.

---

## Appendix A: STRIDE Threat Summary Matrix

| ID | Category | Threat | Impact | Likelihood | Status |
|---|---|---|---|---|---|
| T-01 | Spoofing | Stolen/forged JWT | Critical | Medium | Mitigated |
| T-02 | Spoofing | NATS service impersonation | Critical | Low-Medium | Mitigated |
| T-03 | Tampering | Audit log manipulation | High | Low | Mitigated |
| T-04 | Tampering | OPA policy tampering | Critical | Low | Mitigated |
| T-05 | Repudiation | Operator denies destructive action | Medium | Medium | Mitigated |
| T-06 | Info Disclosure | Data leaked to cloud LLM | High | Medium | Partially mitigated |
| T-07 | Info Disclosure | Credentials in logs/artifacts | High | Medium | Mitigated |
| T-08 | Denial of Service | Workflow bomb | High | Medium | Mitigated |
| T-09 | Elevation of Privilege | Prompt injection escalation | Critical | Medium-High | Partially mitigated |
| T-10 | Elevation of Privilege | Sandbox escape | Critical | Low | Mitigated |
| T-11 | Elevation of Privilege | Direct RBAC DB manipulation | High | Low | Mitigated |
| T-12 | Elevation of Privilege | Service principal over-permissioning | Critical | Medium | Mitigated |

---

## Appendix B: Review Schedule

| Activity | Frequency | Owner |
|---|---|---|
| Threat model review and update | Quarterly | Security Team |
| RBAC and permissions audit | Quarterly | Security Team + Platform Team |
| Service principal permission review | Quarterly | Identity Team |
| Dependency vulnerability scan | Continuous (CI) | Platform Team |
| Audit log integrity verification | Daily (automated) | Audit Service |
| Red team exercise | Annually | Security Team |
| Incident response drill (credential compromise) | Semi-annually | Security Team + SRE |

---

*This document should be reviewed and updated whenever the system architecture changes, new integrations are added, or a security incident reveals gaps in the threat model.*
