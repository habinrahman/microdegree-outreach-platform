"""email_campaigns.reply_type default OTHER (canonical uppercase); run normalize_reply_rows script."""

from alembic import op

revision = "20260403_0003_reply_upper"
down_revision = "20260401_0002_reply_type_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE email_campaigns ALTER COLUMN reply_type DROP DEFAULT")
    op.execute(
        "ALTER TABLE email_campaigns ALTER COLUMN reply_type SET DEFAULT 'OTHER'"
    )
    # Backfill existing rows: python -m app.scripts.normalize_reply_rows


def downgrade() -> None:
    op.execute("ALTER TABLE email_campaigns ALTER COLUMN reply_type DROP DEFAULT")
    op.execute(
        "ALTER TABLE email_campaigns ALTER COLUMN reply_type SET DEFAULT 'other'"
    )
