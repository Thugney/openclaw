"""Initial MSClaw durable schema.

Revision ID: 0001
Revises: None
Create Date: 2026-02-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- workflows --
    op.create_table(
        "workflows",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("steps_definition", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # -- policy_decisions (must come before runs which references it) --
    op.create_table(
        "policy_decisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("correlation_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("step_id", UUID(as_uuid=True), nullable=True),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("action", sa.String(255), nullable=False),
        sa.Column("resource", JSONB, server_default="{}"),
        sa.Column("decision", sa.String(50), nullable=False),
        sa.Column("reasons", JSONB, server_default="[]"),
        sa.Column("opa_response", JSONB, server_default="{}"),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # -- runs --
    op.create_table(
        "runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", UUID(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("correlation_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "awaiting_approval", "approved", "running",
                "completed", "failed", "rejected",
                name="run_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("input_params", JSONB, server_default="{}"),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("initiated_by", sa.String(255), nullable=False, server_default="system"),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("policy_decision_id", UUID(as_uuid=True), sa.ForeignKey("policy_decisions.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_runs_idempotency_key", "runs", ["idempotency_key"],
        unique=True, postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    # -- steps --
    op.create_table(
        "steps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "awaiting_approval", "approved", "running",
                "completed", "failed", "skipped", "rejected",
                name="step_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("input_params", JSONB, server_default="{}"),
        sa.Column("output", JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("policy_decision_id", UUID(as_uuid=True), sa.ForeignKey("policy_decisions.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "seq", name="uq_step_run_seq"),
    )

    # -- approvals --
    op.create_table(
        "approvals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("step_id", UUID(as_uuid=True), sa.ForeignKey("steps.id"), nullable=True),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "denied", "expired", name="approval_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(255), nullable=True),
        sa.Column("correlation_id", UUID(as_uuid=True), nullable=False, index=True),
    )

    # -- idempotency_keys --
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("action_fingerprint", sa.String(512), nullable=False),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="processing"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_idempotency_status",
        ),
    )

    # -- tool_executions --
    op.create_table(
        "tool_executions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("step_id", UUID(as_uuid=True), sa.ForeignKey("steps.id"), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("correlation_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column("adapter_mode", sa.String(50), nullable=False),
        sa.Column("input_params", JSONB, server_default="{}"),
        sa.Column("output_metadata", JSONB, nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="running"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("artifact_keys", JSONB, server_default="[]"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # -- audit_entries (append-only, hash-chained) --
    op.create_table(
        "audit_entries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("correlation_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("run_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("step_id", UUID(as_uuid=True), nullable=True),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("action", sa.String(255), nullable=False),
        sa.Column("detail", JSONB, server_default="{}"),
        sa.Column("policy_decision", sa.String(50), nullable=True),
        sa.Column("approval_chain", JSONB, server_default="[]"),
        sa.Column("tool", sa.String(255), nullable=True),
        sa.Column("adapter_mode", sa.String(50), nullable=True),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("prev_hash", sa.String(64), nullable=True),
        sa.Column("entry_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_entries_created_at", "audit_entries", ["created_at"])

    # -- Append-only trigger: prevent UPDATE/DELETE on audit_entries --
    op.execute("""
        CREATE OR REPLACE FUNCTION audit_entries_immutable()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_entries is append-only: UPDATE and DELETE are forbidden';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_audit_entries_immutable
        BEFORE UPDATE OR DELETE ON audit_entries
        FOR EACH ROW EXECUTE FUNCTION audit_entries_immutable();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_entries_immutable ON audit_entries")
    op.execute("DROP FUNCTION IF EXISTS audit_entries_immutable()")
    op.drop_table("audit_entries")
    op.drop_table("tool_executions")
    op.drop_table("idempotency_keys")
    op.drop_table("approvals")
    op.drop_table("steps")
    op.drop_table("runs")
    op.drop_table("policy_decisions")
    op.drop_table("workflows")
    op.execute("DROP TYPE IF EXISTS run_status")
    op.execute("DROP TYPE IF EXISTS step_status")
    op.execute("DROP TYPE IF EXISTS approval_status")
