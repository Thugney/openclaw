"""MinIO artifact storage for investigation packages, reports, etc."""

from __future__ import annotations

import io
import logging
from typing import Any

from minio import Minio  # type: ignore[import-untyped]

from .config import MinioConfig, load_config

logger = logging.getLogger("msclaw.artifacts")

_client: Minio | None = None


def _get_client(cfg: MinioConfig | None = None) -> Minio:
    global _client
    if _client is None:
        if cfg is None:
            cfg = load_config().minio
        _client = Minio(
            cfg.endpoint,
            access_key=cfg.access_key,
            secret_key=cfg.secret_key,
            secure=cfg.secure,
        )
    return _client


def ensure_bucket(cfg: MinioConfig | None = None) -> None:
    """Create the artifacts bucket if it doesn't exist."""
    if cfg is None:
        cfg = load_config().minio
    client = _get_client(cfg)
    if not client.bucket_exists(cfg.bucket):
        client.make_bucket(cfg.bucket)
        logger.info("Created MinIO bucket: %s", cfg.bucket)


def upload_artifact(
    object_name: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    metadata: dict[str, str] | None = None,
    cfg: MinioConfig | None = None,
) -> str:
    """Upload bytes to MinIO. Returns the object key."""
    if cfg is None:
        cfg = load_config().minio
    client = _get_client(cfg)
    client.put_object(
        cfg.bucket,
        object_name,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
        metadata=metadata or {},
    )
    logger.info("Uploaded artifact: %s/%s (%d bytes)", cfg.bucket, object_name, len(data))
    return object_name


def download_artifact(
    object_name: str,
    cfg: MinioConfig | None = None,
) -> bytes:
    """Download an artifact from MinIO."""
    if cfg is None:
        cfg = load_config().minio
    client = _get_client(cfg)
    response = client.get_object(cfg.bucket, object_name)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def list_artifacts(
    prefix: str = "",
    cfg: MinioConfig | None = None,
) -> list[dict[str, Any]]:
    """List artifacts by prefix."""
    if cfg is None:
        cfg = load_config().minio
    client = _get_client(cfg)
    objects = client.list_objects(cfg.bucket, prefix=prefix, recursive=True)
    return [
        {
            "key": obj.object_name,
            "size": obj.size,
            "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
            "etag": obj.etag,
        }
        for obj in objects
    ]
