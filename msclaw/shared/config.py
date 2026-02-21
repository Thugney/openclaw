"""Centralised configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class NatsConfig:
    url: str = "nats://localhost:4222"
    connect_timeout: int = 10  # seconds
    max_reconnect_attempts: int = 60
    reconnect_time_wait: float = 2.0  # seconds


@dataclass(frozen=True)
class PostgresConfig:
    dsn: str = "postgresql+asyncpg://msclaw:msclaw@localhost:5432/msclaw"
    pool_size: int = 10
    max_overflow: int = 20
    echo: bool = False


@dataclass(frozen=True)
class MinioConfig:
    endpoint: str = "localhost:9000"
    access_key: str = "msclaw"
    secret_key: str = "msclaw123"
    bucket: str = "msclaw-artifacts"
    secure: bool = False


@dataclass(frozen=True)
class OpaConfig:
    url: str = "http://localhost:8181"
    policy_path: str = "/v1/data/msclaw"
    connect_timeout: int = 5


@dataclass(frozen=True)
class MicrosoftConfig:
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    mode: str = "mock"  # "real" or "mock"


@dataclass(frozen=True)
class AppConfig:
    nats: NatsConfig = field(default_factory=NatsConfig)
    postgres: PostgresConfig = field(default_factory=PostgresConfig)
    minio: MinioConfig = field(default_factory=MinioConfig)
    opa: OpaConfig = field(default_factory=OpaConfig)
    microsoft: MicrosoftConfig = field(default_factory=MicrosoftConfig)
    log_level: str = "INFO"
    control_api_port: int = 8080
    ui_port: int = 3000


@lru_cache(maxsize=1)
def load_config() -> AppConfig:
    """Build AppConfig from environment variables with sane defaults."""
    return AppConfig(
        nats=NatsConfig(
            url=os.getenv("NATS_URL", "nats://localhost:4222"),
            connect_timeout=int(os.getenv("NATS_CONNECT_TIMEOUT", "10")),
            max_reconnect_attempts=int(os.getenv("NATS_MAX_RECONNECT", "60")),
            reconnect_time_wait=float(os.getenv("NATS_RECONNECT_WAIT", "2.0")),
        ),
        postgres=PostgresConfig(
            dsn=os.getenv(
                "DATABASE_URL",
                "postgresql+asyncpg://msclaw:msclaw@localhost:5432/msclaw",
            ),
            pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
            max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
            echo=os.getenv("DB_ECHO", "").lower() == "true",
        ),
        minio=MinioConfig(
            endpoint=os.getenv("MINIO_ENDPOINT", "localhost:9000"),
            access_key=os.getenv("MINIO_ACCESS_KEY", "msclaw"),
            secret_key=os.getenv("MINIO_SECRET_KEY", "msclaw123"),
            bucket=os.getenv("MINIO_BUCKET", "msclaw-artifacts"),
            secure=os.getenv("MINIO_SECURE", "").lower() == "true",
        ),
        opa=OpaConfig(
            url=os.getenv("OPA_URL", "http://localhost:8181"),
            policy_path=os.getenv("OPA_POLICY_PATH", "/v1/data/msclaw"),
            connect_timeout=int(os.getenv("OPA_CONNECT_TIMEOUT", "5")),
        ),
        microsoft=MicrosoftConfig(
            tenant_id=os.getenv("MS_TENANT_ID", ""),
            client_id=os.getenv("MS_CLIENT_ID", ""),
            client_secret=os.getenv("MS_CLIENT_SECRET", ""),
            mode=os.getenv("MS_MODE", "mock"),
        ),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        control_api_port=int(os.getenv("CONTROL_API_PORT", "8080")),
        ui_port=int(os.getenv("UI_PORT", "3000")),
    )
