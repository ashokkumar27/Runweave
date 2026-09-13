"""Pin private model registrations and snapshot the total approval allowance.

Drain/version old workflows before upgrading; legacy terminal runs keep a null registration.
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    # A queued legacy run has no immutable selection. Refuse to silently redirect it.
    active = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM runs WHERE status NOT IN ('completed','failed','cancelled')"))
        .scalar()
    )
    if active:
        raise RuntimeError("Drain existing runs before applying registry/timer migration")
    op.create_table(
        "model_registrations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("config", sa.JSON(), nullable=False),
    )
    op.add_column(
        "runs",
        sa.Column("registration_id", sa.String(64), sa.ForeignKey("model_registrations.id"), nullable=True),
    )
    op.add_column(
        "runs", sa.Column("approval_wait_seconds", sa.Integer(), nullable=False, server_default="86400")
    )
    op.alter_column("runs", "approval_wait_seconds", server_default=None)


def downgrade():
    op.drop_column("runs", "approval_wait_seconds")
    op.drop_column("runs", "registration_id")
    op.drop_table("model_registrations")
