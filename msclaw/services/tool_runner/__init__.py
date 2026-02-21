"""MSClaw Tool Runner.

Executes tool intents in sandboxed environments after policy validation.
Handles idempotency, artifact collection, and audit emission.

Security model:
- Only allowlisted tools can be executed
- Each execution is isolated
- Secrets are injected per job (short-lived)
- Every execution requires an idempotency key
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from typing import Any

from ...shared.contracts import (
    AuditAction,
    AuditEntry,
    CorrelationContext,
    IdempotencyRecord,
    ToolExecutionStatus,
    ToolIntent,
    ToolResult,
)
from ...shared.errors import (
    IdempotencyConflictError,
    PolicyDeniedError,
    ToolExecutionError,
)
from ...shared.plugin_sdk import PluginBase

logger = logging.getLogger("msclaw.tool-runner")


class ToolRunner:
    """Executes tool intents from the orchestrator.

    Responsibilities:
    - Validate intent against plugin registry
    - Check idempotency
    - Execute in sandbox
    - Collect artifacts
    - Emit audit entries
    """

    def __init__(self, *, dev_mode: bool = True):
        self._plugins: dict[str, PluginBase] = {}
        self._idempotency_store: dict[str, IdempotencyRecord] = {}
        self._artifacts: dict[str, list[dict[str, Any]]] = {}
        self._audit_log: list[AuditEntry] = []
        self._dev_mode = dev_mode
        self._allowlisted_actions: set[str] = set()

    def register_plugin(self, plugin: PluginBase) -> None:
        """Register a plugin and allowlist its actions."""
        self._plugins[plugin.name] = plugin
        for action_name in plugin.actions():
            full_name = f"{plugin.name}.{action_name}"
            self._allowlisted_actions.add(full_name)
            logger.info("Allowlisted action: %s", full_name)
        logger.info("Registered plugin: %s v%s", plugin.name, plugin.version)

    async def execute(self, intent: ToolIntent) -> ToolResult:
        """Execute a tool intent.

        Flow:
        1. Validate action is allowlisted
        2. Check idempotency
        3. Validate parameters
        4. Execute via plugin
        5. Store result + artifacts
        6. Emit audit
        """
        full_action = f"{intent.plugin}.{intent.action}"
        start = time.monotonic()

        # 1. Allowlist check
        if full_action not in self._allowlisted_actions:
            self._emit_audit(
                AuditAction.TOOL_POLICY_DENIED,
                intent=intent,
                error=f"Action not allowlisted: {full_action}",
            )
            raise PolicyDeniedError(
                full_action,
                "Action not in allowlist - default deny",
                correlation_id=intent.correlation.correlation_id,
            )

        # 2. Idempotency check
        existing = self._idempotency_store.get(intent.idempotency_key)
        if existing:
            if existing.action == full_action and existing.status == ToolExecutionStatus.COMPLETED:
                logger.info("Idempotency hit for key %s - returning cached result", intent.idempotency_key)
                return ToolResult(
                    intent_id=intent.intent_id,
                    plugin=intent.plugin,
                    action=intent.action,
                    status=ToolExecutionStatus.COMPLETED,
                    result=existing.result,
                    correlation=intent.correlation,
                    executed_at=existing.completed_at or datetime.utcnow(),
                )
            elif existing.action != full_action:
                raise IdempotencyConflictError(
                    intent.idempotency_key,
                    correlation_id=intent.correlation.correlation_id,
                )

        # Record as in-progress
        self._idempotency_store[intent.idempotency_key] = IdempotencyRecord(
            idempotency_key=intent.idempotency_key,
            action=full_action,
            status=ToolExecutionStatus.EXECUTING,
        )

        # 3. Get plugin and validate
        plugin = self._plugins.get(intent.plugin)
        if not plugin:
            raise ToolExecutionError(
                intent.plugin, intent.action,
                f"Plugin not found: {intent.plugin}",
                correlation_id=intent.correlation.correlation_id,
            )

        validation_errors = plugin.validate_action(intent.action, intent.parameters)
        if validation_errors:
            raise ToolExecutionError(
                intent.plugin, intent.action,
                f"Parameter validation failed: {validation_errors}",
                correlation_id=intent.correlation.correlation_id,
            )

        # 4. Execute
        try:
            result = await plugin.execute(
                intent.action,
                intent.parameters,
                intent.correlation,
                dev_mode=self._dev_mode,
            )

            duration_ms = int((time.monotonic() - start) * 1000)
            result.duration_ms = duration_ms

            # 5. Update idempotency record
            self._idempotency_store[intent.idempotency_key] = IdempotencyRecord(
                idempotency_key=intent.idempotency_key,
                action=full_action,
                status=ToolExecutionStatus.COMPLETED,
                result=result.result,
                completed_at=datetime.utcnow(),
            )

            # 6. Audit
            self._emit_audit(
                AuditAction.TOOL_EXECUTED,
                intent=intent,
                outputs=result.result,
                duration_ms=duration_ms,
            )

            return result

        except Exception as e:
            self._idempotency_store[intent.idempotency_key] = IdempotencyRecord(
                idempotency_key=intent.idempotency_key,
                action=full_action,
                status=ToolExecutionStatus.FAILED,
            )
            self._emit_audit(
                AuditAction.TOOL_FAILED,
                intent=intent,
                error=str(e),
            )
            raise ToolExecutionError(
                intent.plugin, intent.action, str(e),
                correlation_id=intent.correlation.correlation_id,
            ) from e

    def store_artifact(
        self,
        correlation_id: str,
        artifact_type: str,
        data: bytes | str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store an artifact (investigation package, report, etc.)."""
        artifact_id = str(uuid.uuid4())
        if correlation_id not in self._artifacts:
            self._artifacts[correlation_id] = []

        self._artifacts[correlation_id].append({
            "artifact_id": artifact_id,
            "type": artifact_type,
            "size": len(data) if isinstance(data, bytes) else len(data.encode()),
            "metadata": metadata or {},
            "stored_at": datetime.utcnow().isoformat(),
        })

        # In production, upload to MinIO/S3
        logger.info("Stored artifact %s (type=%s) for %s", artifact_id, artifact_type, correlation_id)
        return artifact_id

    def _emit_audit(
        self,
        action: AuditAction,
        intent: ToolIntent,
        outputs: dict[str, Any] | None = None,
        error: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        entry = AuditEntry(
            correlation_id=intent.correlation.correlation_id,
            workflow_run_id=intent.correlation.workflow_run_id,
            action=action,
            actor="tool-runner",
            target=str(intent.parameters.get("device_id") or intent.parameters.get("user_id", "")),
            plugin=intent.plugin,
            tool_action=intent.action,
            inputs=intent.parameters,
            outputs=outputs,
            error=error,
        )
        self._audit_log.append(entry)
