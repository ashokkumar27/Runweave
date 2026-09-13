"""Initial application state, replay events, effect ledger and outbox."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    op.create_table("workspace_gate", sa.Column("id", sa.Integer(), primary_key=True))
    op.execute("INSERT INTO workspace_gate (id) VALUES (1)")
    op.create_table(
        "agents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("config", sa.JSON(), nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("key", sa.String(128), unique=True, nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("output", sa.JSON()),
        sa.Column("error", sa.String(100)),
        sa.Column("approvals", sa.JSON(), nullable=False),
        sa.Column("decisions", sa.JSON(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("next_event", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_runs_session_id", "runs", ["session_id"])
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_table(
        "events",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), primary_key=True),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dedupe", sa.String(200), nullable=False),
        sa.Column("type", sa.String(80), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "dedupe"),
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("delivered", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_outbox_run_id", "outbox", ["run_id"])
    op.create_index("ix_outbox_delivered", "outbox", ["delivered"])
    op.create_table(
        "notes",
        sa.Column("operation_id", sa.String(160), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )


def downgrade():
    for table in ["notes", "outbox", "events", "runs", "sessions", "agents", "workspace_gate"]:
        op.drop_table(table)
