"""Indexes for scheduler / list queries on email_campaigns."""

from alembic import op

revision = "20260418_0006_campaign_idx"
down_revision = "20260406_0005_reply_workflow_fix"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_campaign_sent_at ON email_campaigns (sent_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_campaign_hr_status ON email_campaigns (hr_id, status)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_campaign_hr_status")
    op.execute("DROP INDEX IF EXISTS idx_campaign_sent_at")
