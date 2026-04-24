"""email_campaigns: reply_workflow_status, reply_admin_notes (replies triage UI)."""

import sqlalchemy as sa
from alembic import op

revision = "20260404_0004_reply_triage"
down_revision = "20260403_0003_reply_upper"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("email_campaigns")]
    if "reply_workflow_status" not in cols:
        op.add_column(
            "email_campaigns",
            sa.Column(
                "reply_workflow_status",
                sa.String(50),
                nullable=True,
                server_default=sa.text("'OPEN'"),
            ),
        )
    if "reply_admin_notes" not in cols:
        op.add_column(
            "email_campaigns",
            sa.Column("reply_admin_notes", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("email_campaigns")]
    if "reply_admin_notes" in cols:
        op.drop_column("email_campaigns", "reply_admin_notes")
    if "reply_workflow_status" in cols:
        op.drop_column("email_campaigns", "reply_workflow_status")
