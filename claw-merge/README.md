# MSClaw – Microsoft Security Agent Runtime

Open-source, self-hosted agent runtime for Microsoft Security and Endpoint operations. MSClaw provides a policy-gated, auditable workflow engine for automating security response actions across Microsoft Defender for Endpoint, Intune, and Entra ID.

## Architecture

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│   UI (React) │    │  CLI (Python) │    │  External    │
│   :3000      │    │              │    │  Integrations│
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │
       └───────────┬───────┴───────────────────┘
                   │
          ┌────────▼────────┐
          │  Control API    │  FastAPI – auth, RBAC, workflow submission
          │  :8000          │
          └────────┬────────┘
                   │ NATS
          ┌────────▼────────┐
          │  Orchestrator   │  Workflow engine, agent loop
          │  :8001          │  Produces TOOL-INTENTS (LLM is untrusted)
          └──┬──────────┬───┘
             │          │
    ┌────────▼───┐  ┌───▼────────────┐
    │ OPA Policy │  │ Model Router   │  Local-first (Ollama)
    │ Gate :8181 │  │ :8002          │  Cloud fallback (policy-gated)
    └────────────┘  └────────────────┘
             │
    ┌────────▼────────┐
    │  Tool Runner    │  Sandboxed execution, idempotency
    │  :8003          │  Artifact storage (MinIO)
    └────────┬────────┘
             │
    ┌────────▼────────┐
    │  Audit Service  │  Append-only ledger, hash chain
    │  :8004          │  Tamper-evident
    └─────────────────┘

Infrastructure: PostgreSQL │ NATS JetStream │ MinIO │ OPA
```

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Git

### 1. Clone and start

```bash
git clone <repo-url> && cd Claw
docker-compose up -d
```

Services will start on:
- **UI**: http://localhost:3000
- **Control API**: http://localhost:8000
- **Tool Runner**: http://localhost:8003
- **Audit Service**: http://localhost:8004
- **OPA**: http://localhost:8181
- **MinIO Console**: http://localhost:9001 (msclaw/msclaw-dev-only)
- **NATS Monitoring**: http://localhost:8222

### 2. Run the MVP workflow (UI)

1. Open http://localhost:3000
2. On the "Run Workflow" page, enter a Device ID (e.g., `device-001`)
3. Optionally add "VIP" to device tags to trigger approval flow
4. Click "Submit Workflow"
5. View the workflow progress, audit trail, and artifacts

### 3. Run the MVP workflow (CLI)

```bash
# Install CLI
pip install -e cli/

# Submit workflow
msclaw run contain_device_from_incident --device-id device-001 --wait

# With VIP tag (triggers approval)
msclaw run contain_device_from_incident --device-id device-002 --tags VIP

# Check approvals
msclaw approvals

# Approve
msclaw approve <approval-id>

# View audit trail
msclaw audit --correlation <correlation-id>

# List registered tools
msclaw tools
```

### 4. Run the MVP workflow (curl)

```bash
# Submit workflow
curl -X POST http://localhost:8000/api/v1/workflows \
  -H "Content-Type: application/json" \
  -H "X-Actor: admin@contoso.com" \
  -H "X-Roles: security-lead" \
  -d '{
    "workflow_name": "contain_device_from_incident",
    "inputs": {"deviceId": "device-001", "actor_roles": ["security-lead"]},
    "idempotency_key": "contain-device-001-001"
  }'

# Check status
curl http://localhost:8000/api/v1/workflows/<run_id> \
  -H "X-Actor: admin@contoso.com"

# List pending approvals
curl http://localhost:8000/api/v1/approvals \
  -H "X-Actor: admin@contoso.com"

# View audit trail
curl http://localhost:8004/api/v1/audit/correlation/<correlation_id>

# Verify audit chain integrity
curl http://localhost:8004/api/v1/audit/verify
```

## Dev Mode vs Production

MSClaw ships with `DEV_MODE=true` by default. In dev mode:

- **Microsoft API calls are mocked** – no real Defender/Intune/Entra calls
- **Auth uses header-based identity** (`X-Actor`, `X-Roles`) – no JWT validation
- **Policy evaluation uses built-in dev logic** – VIP tags trigger approvals
- **All outputs are clearly marked** `_dev_mock: true`

For production, set `DEV_MODE=false` and configure real Microsoft credentials.

## Microsoft Entra App Registration

For production use, you need to register apps in Entra ID.

### Defender XDR App

1. Go to Azure Portal > Entra ID > App Registrations > New Registration
2. Name: `MSClaw-Defender`
3. Add API Permission > APIs my organization uses > "WindowsDefenderATP"
4. Add Application permissions:
   - `Machine.Isolate`
   - `Machine.CollectForensics`
   - `Machine.Scan`
   - `Incident.Read.All`
5. Grant admin consent
6. Create a client secret
7. Update `config/tenant.json` with the client ID
8. Set `MSCLAW_DEFENDER_CLIENT_SECRET` environment variable

### Intune App

1. Register app: `MSClaw-Intune`
2. Add Microsoft Graph Application permissions:
   - `DeviceManagementManagedDevices.ReadWrite.All`
   - `DeviceManagementConfiguration.ReadWrite.All`
3. Grant admin consent

### Entra ID App

1. Register app: `MSClaw-Entra`
2. Add Microsoft Graph Application permissions:
   - `User.ReadWrite.All`
3. Grant admin consent
4. Note: `revoke_signin_sessions` and `disable_user` are always approval-gated by policy

## Plugins

### Plugin SDK Contract

Every plugin action declares:

| Field | Description |
|-------|-------------|
| `input_schema` | JSONSchema for inputs |
| `required_permissions` | MS Graph permissions / app roles |
| `idempotency_strategy` | `check_and_skip`, `safe_to_retry`, or `require_lock` |
| `rollback_action` | Reverse action name (if feasible) |
| `requires_approval` | Whether action always requires approval |
| `audit_fields` | Fields to capture in audit log |

### Available Plugins

**defender_xdr**: `isolate_device`, `unisolate_device`, `collect_investigation_package`, `run_antivirus_scan`, `get_incident_devices`

**intune**: `sync_device`, `assign_asr_policy`

**entra**: `revoke_signin_sessions` (approval-gated), `disable_user` (approval-gated)

## Policy (OPA/Rego)

Policies are in `policies/rego/`. Every tool execution passes through OPA.

- **Default deny**: no matching rule = denied
- **Role-based**: security-analysts get read-only; security-leads get containment actions
- **VIP approval**: devices tagged "VIP" require approval from security-lead + soc-manager
- **Entra approval**: identity actions always require approval
- **Cloud model PII blocking**: payloads with device/user identifiers blocked from cloud LLMs

Test policies: `opa test policies/rego/ -v`

## Security Model

- **LLM is untrusted**: produces intents; policy decides; runner executes
- **Default deny** for tools and network egress
- **Tool allowlist**: only registered plugin actions can execute
- **Idempotency**: every action requires an Idempotency-Key; safe to retry
- **Audit**: append-only with SHA-256 hash chain for tamper evidence
- **Secrets**: injected per-job (never stored in config files)
- **Correlation IDs**: every operation is traceable end-to-end

See `docs/THREAT_MODEL.md` for the full threat model.

## Configuration

| File | Purpose |
|------|---------|
| `config/config.yaml` | Service endpoints, infrastructure, model router settings |
| `config/tenant.json` | MS tenant ID, app registrations, plugin enablement |
| `policies/rego/` | OPA/Rego policies |
| `docker-compose.yml` | Local dev deployment |

Environment variables override config. Pattern: `MSCLAW_<SECTION>_<KEY>`.

## Project Structure

```
├── shared/                    # Shared contracts, models, bus, auth, errors, policy
├── services/
│   ├── control-api/           # FastAPI – auth, RBAC, workflow submission
│   ├── orchestrator/          # Workflow engine, agent loop
│   ├── model-router/          # LLM routing (Ollama + cloud fallback)
│   ├── tool-runner/           # Sandboxed tool execution
│   ├── audit-service/         # Append-only audit ledger
│   └── ui-web/                # React operator console
├── plugins/
│   ├── sdk/                   # Plugin SDK base classes
│   ├── defender_xdr/          # Defender for Endpoint plugin
│   ├── intune/                # Intune plugin
│   └── entra/                 # Entra ID plugin
├── policies/rego/             # OPA/Rego policies
├── cli/                       # Python CLI client
├── config/                    # Configuration files
├── docs/                      # Documentation (OpenAPI, threat model)
└── docker-compose.yml         # Local dev deployment
```

## License

See LICENSE file.
