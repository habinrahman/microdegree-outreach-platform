"""Idempotent PG fix: reply_workflow_status VARCHAR(50) DEFAULT OPEN; widen legacy VARCHAR(32)."""

from alembic import op

revision = "20260406_0005_reply_workflow_fix"
down_revision = "20260404_0004_reply_triage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        ALTER TABLE email_campaigns
          ADD COLUMN IF NOT EXISTS reply_workflow_status VARCHAR(50) DEFAULT 'OPEN';
        """
    )
    op.execute(
        """
        ALTER TABLE email_campaigns
          ADD COLUMN IF NOT EXISTS reply_admin_notes TEXT;
        """
    )
    op.execute(
        """
        ALTER TABLE email_campaigns
          ALTER COLUMN reply_workflow_status TYPE VARCHAR(50);
        """
    )
    op.execute(
        """
        ALTER TABLE email_campaigns
          ALTER COLUMN reply_workflow_status SET DEFAULT 'OPEN';
        """
    )
    op.execute(
        """
        UPDATE email_campaigns
        SET reply_workflow_status = 'OPEN'
        WHERE reply_workflow_status IS NULL;
        """
    )


def downgrade() -> None:
    pass
