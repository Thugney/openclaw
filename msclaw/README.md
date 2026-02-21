# MSClaw – Durable, Policy-Gated Agent Runtime

MSClaw is a hardened runtime for executing security operations workflows against Microsoft 365 Defender / MDE / Intune APIs. Every action is policy-gated through OPA, durably recorded in Postgres, and communicated between services exclusively via NATS JetStream.

## Architecture

```
┌─────────────┐    HTTP     ┌──────────────┐   NATS    ┌──────────────┐
│   UI (3000) │───────────→ │ Control API  │─────────→ │ Orchestrator │
│  nginx/html │             │ (8080)       │           │              │
└─────────────┘             │  - OPA gate  │           │  - Step      │
                            │  - Idempotency│          │    sequencer │
                            │  - Approvals │           │  - OPA per-  │
                            └──────┬───────┘           │    step gate │
                                   │                   └──────┬───────┘
                                   │ NATS                     │ NATS
                                   ▼                          ▼
                            ┌──────────────┐           ┌──────────────┐
                            │ Audit Service│           │ Tool Runner  │
                            │  - Observer  │           │  - Policy    │
                            │  - Chain     │           │    verify    │
                            │    verify    │           │  - MS APIs   │
                            └──────────────┘           │  - MinIO     │
                                                       └──────────────┘
Infrastructure: [Postgres] [NATS JetStream] [MinIO] [OPA]
```

### Execution Flow (end-to-end)

1. **UI/CLI** submits a workflow run via `POST /api/v1/runs`
2. **Control API** checks idempotency key (Postgres unique constraint)
3. **Control API** evaluates OPA policy → `allow` / `deny` / `require_approval`
4. If denied → HTTP 403, audit entry, no NATS message
5. If approval required → creates `Approval` row, returns `awaiting_approval`
6. If allowed → creates `Run` + `Steps` in Postgres, publishes `workflow.run.requested.v1` to NATS
7. **Orchestrator** consumes from NATS, evaluates OPA per-step, publishes `workflow.step.intent.v1`
8. **Tool Runner** consumes intent, **verifies policy_decision_id exists in Postgres with decision=allow**, then executes
9. Tool Runner publishes `workflow.step.result.v1` to NATS
10. Orchestrator processes result, advances to next step (or marks run complete)
11. **Audit Service** independently observes ALL NATS messages and logs them

### Key Guarantees

| Property | Implementation |
|----------|---------------|
| **No in-memory state** | All workflows, runs, steps, approvals, audit, idempotency keys in Postgres |
| **NATS for cross-service** | No direct HTTP calls between services; all communication via JetStream |
| **Policy single choke point** | Tool Runner rejects any intent without a valid `policy_decision_id` |
| **Append-only audit** | Hash-chained entries, Postgres trigger prevents UPDATE/DELETE |
| **Idempotency** | Postgres unique constraint + fingerprint matching |
| **Durability** | Postgres + NATS file-based persistence + MinIO volumes |

## Quick Start

### Prerequisites

- Docker & Docker Compose v2
- curl, python3, jq (for smoke tests)

### Start the Stack

```bash
cd msclaw/
docker compose up -d
```

This starts: Postgres, NATS, MinIO, OPA, control-api, orchestrator, tool-runner, audit-service, UI.

### Run Smoke Test

```bash
./scripts/smoke_test.sh
```

The smoke test:
1. Runs DB migrations
2. Seeds the "contain device from incident" workflow
3. Submits a run (handles approval if triggered)
4. Polls until completion
5. Verifies audit chain integrity
6. Tests idempotency (duplicate + conflict detection)

### View the UI

Open http://localhost:3000

Features:
- Workflow list
- Submit new runs
- Approvals queue (approve/deny)
- Run timeline with step-by-step status
- Audit ledger with correlation ID linking
- Artifacts list (MinIO)
- Chain verification button

## Mock vs Real Mode

### Mock Mode (default)

```bash
MS_MODE=mock docker compose up -d
```

Returns realistic-looking responses from simulated Microsoft APIs. Every mock invocation is tagged with `adapter_mode=mock` in the audit trail.

### Real Mode

```bash
MS_MODE=real \
MS_TENANT_ID=your-tenant-id \
MS_CLIENT_ID=your-app-client-id \
MS_CLIENT_SECRET=your-client-secret \
docker compose up -d
```

Makes actual API calls to Microsoft 365 Defender / MDE.

## Microsoft Entra App Registration

### Step 1: Register the Application

1. Go to [Azure Portal → Entra ID → App registrations](https://portal.azure.com/#blade/Microsoft_AAD_IAM/ActiveDirectoryMenuBlade/RegisteredApps)
2. Click **New registration**
3. Name: `MSClaw Security Automation`
4. Supported account types: **Single tenant**
5. No redirect URI needed (daemon app)
6. Click **Register**

### Step 2: Create Client Secret

1. Go to **Certificates & secrets → New client secret**
2. Description: `MSClaw production`
3. Expiry: 24 months (rotate before expiry)
4. Copy the **Value** immediately (shown only once)

### Step 3: Grant API Permissions

Go to **API permissions → Add a permission → APIs my organization uses**.

Search for **WindowsDefenderATP** (Microsoft Defender for Endpoint):

| Permission | Type | Purpose |
|-----------|------|---------|
| `Machine.Read.All` | Application | Read device info from incidents |
| `Machine.Isolate` | Application | Isolate compromised devices |
| `Machine.CollectForensics` | Application | Collect investigation packages |
| `Alert.Read.All` | Application | Read alerts from incidents |
| `Incident.Read.All` | Application | Read incident details |

Click **Grant admin consent** for your tenant.

### Step 4: Verify Permissions

```bash
# Test token acquisition
curl -X POST "https://login.microsoftonline.com/$MS_TENANT_ID/oauth2/v2.0/token" \
  -d "client_id=$MS_CLIENT_ID" \
  -d "client_secret=$MS_CLIENT_SECRET" \
  -d "scope=https://api.securitycenter.microsoft.com/.default" \
  -d "grant_type=client_credentials"
```

A successful response returns an `access_token`. If you get an error, check permissions and admin consent.

### Permissions Matrix

| Workflow Step | API | Endpoint | Required Permission | Least Privilege |
|--------------|-----|----------|-------------------|-----------------|
| Resolve Device | MDE | `GET /api/incidents/{id}` | `Incident.Read.All` | App-only |
| Resolve Device | MDE | `GET /api/machines/{id}` | `Machine.Read.All` | App-only |
| Isolate Device | MDE | `POST /api/machines/{id}/isolate` | `Machine.Isolate` | App-only |
| Collect Package | MDE | `POST /api/machines/{id}/collectInvestigationPackage` | `Machine.CollectForensics` | App-only |

All permissions use **Application** (app-only) type with client_credentials grant. No delegated/user permissions needed.

## Verifying Durability

```bash
# 1. Run a workflow
./scripts/smoke_test.sh

# 2. Restart all services
docker compose restart control-api orchestrator tool-runner audit-service

# 3. Verify data survived
./scripts/test_durability.sh
```

## Verifying Policy Enforcement

```bash
./scripts/test_policy_enforcement.sh
```

Proves:
- Unauthorized roles get HTTP 403 (never reaches NATS/tool-runner)
- VIP device tag triggers approval requirement
- Denial is recorded in audit ledger

## Verifying Audit Chain

```bash
# Via API
curl -X POST http://localhost:8080/api/v1/audit/verify

# Via CLI
docker compose exec control-api python -c "
import asyncio
from msclaw.audit_service.service import cli_verify
result = asyncio.run(cli_verify())
"
```

## Verifying Idempotency

```bash
# Same key + same payload = returns prior result
curl -X POST http://localhost:8080/api/v1/runs \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-key-1" \
  -d '{"workflow_id": "...", "params": {"incident_id": "INC-001"}}'

# Same request again → returns {"status": "duplicate", "prior_result": {...}}
curl -X POST http://localhost:8080/api/v1/runs \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-key-1" \
  -d '{"workflow_id": "...", "params": {"incident_id": "INC-001"}}'

# Same key + different payload → HTTP 409
curl -X POST http://localhost:8080/api/v1/runs \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-key-1" \
  -d '{"workflow_id": "...", "params": {"incident_id": "INC-DIFFERENT"}}'
```

## OPA Policies

Policies are in `policies/msclaw.rego`:

1. **RBAC**: Only `admin`, `soc_analyst`, `incident_responder` roles can execute
2. **Destructive actions**: Only `admin` and `incident_responder` can isolate/restrict
3. **VIP device**: Any device tagged `VIP` requires human approval
4. **PII routing**: Blocks cloud model routing when payload contains PII fields

### Running Rego Tests

```bash
docker run --rm -v ./policies:/policies openpolicyagent/opa:latest-static \
  test /policies -v
```

## Service Ports

| Service | Port | Purpose |
|---------|------|---------|
| UI | 3000 | Web interface |
| Control API | 8080 | REST API |
| Postgres | 5432 | Durable state |
| NATS | 4222 | Message bus |
| NATS Monitor | 8222 | NATS dashboard |
| MinIO | 9000 | Artifact storage |
| MinIO Console | 9001 | MinIO dashboard |
| OPA | 8181 | Policy engine |

## NATS Subjects (v1)

| Subject | Publisher | Consumer | Purpose |
|---------|-----------|----------|---------|
| `workflow.run.requested.v1` | control-api | orchestrator | New run to execute |
| `workflow.run.approved.v1` | control-api | orchestrator | Approved run to resume |
| `workflow.step.intent.v1` | orchestrator | tool-runner | Step to execute |
| `workflow.step.result.v1` | tool-runner | orchestrator, control-api | Step completion |
| `workflow.run.status.v1` | orchestrator | control-api | Run status update |
| `workflow.approval.required.v1` | orchestrator | control-api | Approval needed |
| `workflow.dlq.v1` | any | audit-service | Failed message dead letter |
