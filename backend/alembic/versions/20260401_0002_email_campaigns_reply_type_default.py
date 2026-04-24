"""Set default for email_campaigns.reply_type (new rows classify to 'other' if unset)."""

from alembic import op

revision = "20260401_0002_reply_type_default"
down_revision = "20260402_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE email_campaigns ALTER COLUMN reply_type SET DEFAULT 'other'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE email_campaigns ALTER COLUMN reply_type DROP DEFAULT")
