# MSClaw - Microsoft Security Operations Agent Runtime

MSClaw is an open-source, self-hosted agent runtime for Microsoft Security and Endpoint operations. It provides a production-grade framework for automating security workflows across the Microsoft cloud ecosystem with full audit trails, policy gates, and approval workflows.

## Architecture

```
                    +-----------+
                    |   UI Web  |  (React - operator console)
                    +-----+-----+
                          |
                    +-----v-----+
                    | Control   |  (FastAPI - auth, RBAC, workflow submission)
                    | API       |
                    +-----+-----+
                          |
                    +-----v-----+
                    | NATS/     |  (Message bus)
                    | RabbitMQ  |
                    +-----+-----+
                          |
          +---------------+---------------+
          |               |               |
    +-----v-----+  +-----v-----+  +------v------+
    |Orchestrator|  |Model      |  |Audit        |
    |(workflow   |  |Router     |  |Service      |
    | engine)    |  |(local/    |  |(append-only  |
    |            |  | cloud)    |  | hash chain)  |
    +-----+------+  +-----------+  +-------------+
          |
    +-----v-----+
    |Tool Runner |  (sandboxed execution)
    |            |
    | +--------+ |
    | |OPA/Rego| |  (policy gate - every action)
    | +--------+ |
    +-----+------+
          |
    +-----v-----+
    | Plugins   |
    | - Defender XDR
    | - Intune
    | - Entra ID
    +-----------+
```

## Supported Microsoft Services

| Service | Plugin | Actions |
|---------|--------|---------|
| Defender for Endpoint / XDR | `defender_xdr` | isolate/unisolate device, collect investigation package, run AV scan, resolve device from incident |
| Intune | `intune` | sync device, assign ASR policy (idempotent) |
| Entra ID | `entra` | revoke sign-in sessions (approval-gated), disable/enable user (approval-gated) |

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.12+ (for development)
- Node.js 22+ (for UI development)

### 1. Start the development stack

```bash
cd msclaw/deploy/docker
docker-compose up -d
```

This starts: Postgres, NATS, MinIO, OPA, Control API, and the Web UI.

- **UI**: http://localhost:3000
- **API**: http://localhost:8100
- **OPA**: http://localhost:8181

### 2. Configure Microsoft integration

```bash
# Copy and edit tenant config
cp tenant.json.example tenant.json
# Edit tenant.json with your Entra app registration details
```

### 3. Submit a workflow via CLI

```bash
# Install CLI
pip install -e ".[dev]"

# Submit "Contain device from incident" workflow
msclaw workflow-submit contain-device-from-incident \
  --inputs '{"incidentId": "INC-42"}' \
  --operator operator@contoso.com

# Check status
msclaw workflow-status <run-id>

# List pending approvals
msclaw approval-list

# Approve an action
msclaw approval-decide <approval-id> approved --operator senior-op@contoso.com
```

### 4. Use the Web UI

Open http://localhost:3000 and:
1. Submit a "Contain device from incident" workflow
2. Approve pending actions in the Approvals tab
3. View the full audit trail with correlation IDs

## Registering Entra App for Microsoft Integration

### App Registration

1. Go to [Azure Portal > Entra ID > App registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
2. Click **New registration**
3. Name: `MSClaw Security Operations`
4. Supported account types: **Single tenant**
5. Click **Register**

### API Permissions (Application - app-only)

Add the following **Application** permissions (not Delegated):

| API | Permission | Purpose |
|-----|-----------|---------|
| Microsoft Graph | `User.ReadWrite.All` | Entra: disable/enable users, revoke sessions |
| Microsoft Graph | `DeviceManagementManagedDevices.ReadWrite.All` | Intune: sync devices |
| Microsoft Graph | `DeviceManagementConfiguration.ReadWrite.All` | Intune: manage ASR policies |
| WindowsDefenderATP | `Machine.Isolate` | Defender: isolate/unisolate devices |
| WindowsDefenderATP | `Machine.CollectForensics` | Defender: collect investigation packages |
| WindowsDefenderATP | `Machine.Scan` | Defender: run AV scans |
| WindowsDefenderATP | `Machine.Read.All` | Defender: read device info |
| WindowsDefenderATP | `Incident.Read.All` | Defender: read incidents |

Grant admin consent for all permissions.

### Client Secret

1. Go to **Certificates & secrets**
2. Create a new client secret
3. Copy the value to `tenant.json`

### tenant.json

```json
{
  "tenant_id": "YOUR-TENANT-ID",
  "client_id": "YOUR-APP-CLIENT-ID",
  "client_secret": "YOUR-CLIENT-SECRET"
}
```

## Security Model

- **Default deny**: Every tool execution must pass the OPA policy gate
- **Allowlisted tools only**: Tool runner only executes registered plugin actions
- **Approval gates**: High-impact actions (Entra identity ops, VIP device isolation) require operator approval
- **Full audit**: Every action produces an audit entry with correlation ID, inputs, outputs, policy decision, and hash chain
- **Idempotency**: Every action requires an idempotency key; safe to retry
- **Secrets per job**: Short-lived tokens injected at execution time
- **LLM as untrusted**: The model proposes intents; policy decides; the runner executes

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check .
ruff format --check .

# Type check
mypy shared/ plugins/ services/ cli/ --ignore-missing-imports

# Run OPA policy tests
cd policies && opa test rego/ -v
```

## Project Structure

```
msclaw/
  shared/              # Shared contracts, SDK, auth, config, errors
    contracts/         # Pydantic types for all service boundaries
    plugin-sdk/        # Plugin SDK with action definitions
    auth/              # MSAL authentication for Microsoft APIs
    config/            # Config loader (config.yaml + tenant.json)
    errors/            # Typed error hierarchy
  services/
    control-api/       # FastAPI control plane
    orchestrator/      # Workflow engine + contain-device workflow
    model-router/      # Local-first LLM routing with cloud fallback
    tool-runner/       # Sandboxed tool execution with idempotency
    audit-service/     # Append-only audit ledger with hash chain
    ui-web/            # React operator console
  plugins/
    defender_xdr/      # Defender for Endpoint / XDR actions
    intune/            # Intune device management actions
    entra/             # Entra ID identity actions
  policies/
    rego/              # OPA/Rego policies (RBAC, VIP gates, PII rules)
    data/              # Role definitions and policy data
  cli/                 # CLI thin client
  deploy/
    docker/            # Docker compose + Dockerfiles
    ci/                # GitHub Actions CI pipeline
  tests/               # Unit and integration tests
  docs/                # Threat model and additional docs
```

## License

MIT
