"""MSClaw configuration system.

Loads config.yaml for service endpoints and tenant.json for
Microsoft app registration details.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from ..auth import TenantConfig
from ..errors import ConfigurationError


@dataclass
class ServiceEndpoints:
    control_api: str = "http://localhost:8100"
    orchestrator: str = "http://localhost:8101"
    model_router: str = "http://localhost:8102"
    tool_runner: str = "http://localhost:8103"
    audit_service: str = "http://localhost:8104"
    nats_url: str = "nats://localhost:4222"
    postgres_url: str = "postgresql://msclaw:msclaw@localhost:5432/msclaw"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "msclaw"
    minio_secret_key: str = "msclaw-dev-secret"
    opa_url: str = "http://localhost:8181"


@dataclass
class ModelConfig:
    local_ollama_url: str = "http://localhost:11434"
    local_model: str = "llama3.2:3b"
    cloud_provider: str = "anthropic"
    cloud_model: str = "claude-sonnet-4-20250514"
    cloud_api_key: str = ""
    prefer_local: bool = True
    max_cloud_budget_usd: float = 10.0
    block_pii_to_cloud: bool = True


@dataclass
class PluginEnablement:
    defender_xdr: bool = True
    intune: bool = True
    entra: bool = True


@dataclass
class MSClawConfig:
    services: ServiceEndpoints = field(default_factory=ServiceEndpoints)
    tenant: TenantConfig | None = None
    models: ModelConfig = field(default_factory=ModelConfig)
    plugins: PluginEnablement = field(default_factory=PluginEnablement)
    dev_mode: bool = True
    log_level: str = "INFO"


def load_config(
    config_path: str | Path | None = None,
    tenant_path: str | Path | None = None,
) -> MSClawConfig:
    """Load MSClaw configuration from YAML + JSON files.

    Priority: env vars > files > defaults.
    """
    config_path = Path(config_path or os.getenv("MSCLAW_CONFIG", "config.yaml"))
    tenant_path = Path(tenant_path or os.getenv("MSCLAW_TENANT", "tenant.json"))

    config = MSClawConfig()

    # Load config.yaml
    if config_path.exists():
        with open(config_path) as f:
            raw: dict[str, Any] = yaml.safe_load(f) or {}

        svc = raw.get("services", {})
        config.services = ServiceEndpoints(
            control_api=svc.get("control_api", config.services.control_api),
            orchestrator=svc.get("orchestrator", config.services.orchestrator),
            model_router=svc.get("model_router", config.services.model_router),
            tool_runner=svc.get("tool_runner", config.services.tool_runner),
            audit_service=svc.get("audit_service", config.services.audit_service),
            nats_url=svc.get("nats_url", config.services.nats_url),
            postgres_url=svc.get("postgres_url", config.services.postgres_url),
            minio_endpoint=svc.get("minio_endpoint", config.services.minio_endpoint),
            minio_access_key=svc.get("minio_access_key", config.services.minio_access_key),
            minio_secret_key=svc.get("minio_secret_key", config.services.minio_secret_key),
            opa_url=svc.get("opa_url", config.services.opa_url),
        )

        mdl = raw.get("models", {})
        config.models = ModelConfig(
            local_ollama_url=mdl.get("local_ollama_url", config.models.local_ollama_url),
            local_model=mdl.get("local_model", config.models.local_model),
            cloud_provider=mdl.get("cloud_provider", config.models.cloud_provider),
            cloud_model=mdl.get("cloud_model", config.models.cloud_model),
            cloud_api_key=mdl.get("cloud_api_key", config.models.cloud_api_key),
            prefer_local=mdl.get("prefer_local", config.models.prefer_local),
            max_cloud_budget_usd=mdl.get("max_cloud_budget_usd", config.models.max_cloud_budget_usd),
            block_pii_to_cloud=mdl.get("block_pii_to_cloud", config.models.block_pii_to_cloud),
        )

        plugins = raw.get("plugins", {})
        config.plugins = PluginEnablement(
            defender_xdr=plugins.get("defender_xdr", True),
            intune=plugins.get("intune", True),
            entra=plugins.get("entra", True),
        )

        config.dev_mode = raw.get("dev_mode", True)
        config.log_level = raw.get("log_level", "INFO")

    # Load tenant.json
    if tenant_path.exists():
        with open(tenant_path) as f:
            tenant_raw = json.load(f)

        config.tenant = TenantConfig(
            tenant_id=tenant_raw["tenant_id"],
            client_id=tenant_raw["client_id"],
            client_secret=tenant_raw.get("client_secret"),
            certificate_path=tenant_raw.get("certificate_path"),
            certificate_password=tenant_raw.get("certificate_password"),
        )
    elif not config.dev_mode:
        raise ConfigurationError("tenant.json is required when dev_mode is false")

    # Env var overrides
    if env_tenant := os.getenv("MSCLAW_TENANT_ID"):
        if config.tenant is None:
            config.tenant = TenantConfig(
                tenant_id=env_tenant,
                client_id=os.getenv("MSCLAW_CLIENT_ID", ""),
                client_secret=os.getenv("MSCLAW_CLIENT_SECRET"),
            )
        else:
            config.tenant.tenant_id = env_tenant

    if env_key := os.getenv("MSCLAW_CLOUD_API_KEY"):
        config.models.cloud_api_key = env_key

    return config
