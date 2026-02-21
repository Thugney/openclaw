"""SQLAlchemy async engine, session factory, and all durable models.

Every piece of runtime state lives here – workflows, runs, steps, approvals,
policy decisions, idempotency keys, audit entries, and tool execution records.
No in-memory stores.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, relationship

from .config import load_config

# ---------------------------------------------------------------------------
# Engine / session helpers
# ---------------------------------------------------------------------------

_engine = None
_session_factory = None


def _get_engine():
    global _engine
    if _engine is None:
        cfg = load_config().postgres
        _engine = create_async_engine(
            cfg.dsn,
            pool_size=cfg.pool_size,
            max_overflow=cfg.max_overflow,
            echo=cfg.echo,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            _get_engine(), expire_on_commit=False
        )
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RunStatus(str, enum.Enum):
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class StepStatus(str, enum.Enum):
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    REJECTED = "rejected"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class Workflow(Base):
    """A workflow definition (template)."""

    __tablename__ = "workflows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, default="")
    steps_definition = Column(JSONB, nullable=False)  # ordered list of step defs
    created_at = Column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=dt.datetime.now(dt.timezone.utc),
    )

    runs = relationship("Run", back_populates="workflow", lazy="selectin")


class Run(Base):
    """A single execution of a workflow."""

    __tablename__ = "runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(
        UUID(as_uuid=True), ForeignKey("workflows.id"), nullable=False
    )
    correlation_id = Column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4, index=True
    )
    status = Column(
        Enum(RunStatus, name="run_status"),
        nullable=False,
        default=RunStatus.PENDING,
    )
    input_params = Column(JSONB, default=dict)
    result = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    initiated_by = Column(String(255), nullable=False, default="system")
    idempotency_key = Column(String(255), nullable=True)
    policy_decision_id = Column(
        UUID(as_uuid=True), ForeignKey("policy_decisions.id"), nullable=True
    )
    created_at = Column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=dt.datetime.now(dt.timezone.utc),
    )

    workflow = relationship("Workflow", back_populates="runs")
    steps = relationship(
        "Step", back_populates="run", lazy="selectin", order_by="Step.seq"
    )
    approvals = relationship("Approval", back_populates="run", lazy="selectin")

    __table_args__ = (
        Index("ix_runs_idempotency_key", "idempotency_key", unique=True,
              postgresql_where=text("idempotency_key IS NOT NULL")),
    )


class Step(Base):
    """One step inside a run."""

    __tablename__ = "steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("runs.id"), nullable=False)
    seq = Column(Integer, nullable=False)
    name = Column(String(255), nullable=False)
    tool_name = Column(String(255), nullable=False)
    status = Column(
        Enum(StepStatus, name="step_status"),
        nullable=False,
        default=StepStatus.PENDING,
    )
    input_params = Column(JSONB, default=dict)
    output = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    policy_decision_id = Column(
        UUID(as_uuid=True), ForeignKey("policy_decisions.id"), nullable=True
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    run = relationship("Run", back_populates="steps")

    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_step_run_seq"),
    )


class Approval(Base):
    """Approval request for a run or step that requires human sign-off."""

    __tablename__ = "approvals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("runs.id"), nullable=False)
    step_id = Column(UUID(as_uuid=True), ForeignKey("steps.id"), nullable=True)
    reason = Column(Text, nullable=False)
    status = Column(
        Enum(ApprovalStatus, name="approval_status"),
        nullable=False,
        default=ApprovalStatus.PENDING,
    )
    requested_at = Column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decided_by = Column(String(255), nullable=True)
    correlation_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    run = relationship("Run", back_populates="approvals")


class PolicyDecision(Base):
    """Record of an OPA policy evaluation."""

    __tablename__ = "policy_decisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    correlation_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    run_id = Column(UUID(as_uuid=True), nullable=True)
    step_id = Column(UUID(as_uuid=True), nullable=True)
    actor = Column(String(255), nullable=False)
    action = Column(String(255), nullable=False)
    resource = Column(JSONB, default=dict)
    decision = Column(String(50), nullable=False)  # "allow", "deny", "require_approval"
    reasons = Column(JSONB, default=list)
    opa_response = Column(JSONB, default=dict)
    evaluated_at = Column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class IdempotencyKey(Base):
    """Global idempotency registry – unique constraint enforces exactly-once."""

    __tablename__ = "idempotency_keys"

    key = Column(String(255), primary_key=True)
    action_fingerprint = Column(String(512), nullable=False)
    result = Column(JSONB, nullable=True)
    status = Column(String(50), nullable=False, default="processing")
    created_at = Column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_idempotency_status",
        ),
    )


class ToolExecution(Base):
    """Durable record of every tool invocation with inputs/outputs."""

    __tablename__ = "tool_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    step_id = Column(UUID(as_uuid=True), ForeignKey("steps.id"), nullable=False)
    run_id = Column(UUID(as_uuid=True), ForeignKey("runs.id"), nullable=False)
    correlation_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    tool_name = Column(String(255), nullable=False)
    adapter_mode = Column(String(50), nullable=False)  # "real" or "mock"
    input_params = Column(JSONB, default=dict)
    output_metadata = Column(JSONB, nullable=True)
    status = Column(String(50), nullable=False, default="running")
    error = Column(Text, nullable=True)
    artifact_keys = Column(JSONB, default=list)  # MinIO object keys
    started_at = Column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)


class AuditEntry(Base):
    """Append-only, hash-chained audit ledger."""

    __tablename__ = "audit_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    correlation_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    run_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    step_id = Column(UUID(as_uuid=True), nullable=True)
    actor = Column(String(255), nullable=False)
    action = Column(String(255), nullable=False)
    detail = Column(JSONB, default=dict)
    policy_decision = Column(String(50), nullable=True)
    approval_chain = Column(JSONB, default=list)
    tool = Column(String(255), nullable=True)
    adapter_mode = Column(String(50), nullable=True)
    model = Column(String(255), nullable=True)
    prev_hash = Column(String(64), nullable=True)
    entry_hash = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        # Prevent updates/deletes at application level; DB-level rule recommended
        # via a Postgres trigger (see migrations).
        Index("ix_audit_entries_created_at", "created_at"),
    )
