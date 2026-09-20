"""Add toolkit state and bounded artifact storage without rewriting legacy rows."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "toolkit_runs",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), primary_key=True),
        sa.Column("root_id", sa.String(36), nullable=False),
        sa.Column("parent_id", sa.String(36), nullable=True),
        sa.Column("state", sa.JSON(), nullable=False),
    )
    op.create_index("ix_toolkit_runs_root_id", "toolkit_runs", ["root_id"])
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key", sa.String(160), nullable=False, unique=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(80), nullable=False),
        sa.Column("filename", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("producer_run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "toolkit_operations",
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
    )
    op.create_index("ix_toolkit_operations_run_id", "toolkit_operations", ["run_id"])


def downgrade():
    op.drop_table("toolkit_operations")
    op.drop_table("artifacts")
    op.drop_table("toolkit_runs")
