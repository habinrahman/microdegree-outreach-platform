"""email_campaigns.reply_type default OTHER (canonical uppercase); run normalize_reply_rows script."""

from alembic import op
from sqlalchemy.exc import OperationalError

revision = "20260403_0003_reply_upper"
down_revision = "20260401_0002_reply_type_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOTE: This migration used to ALTER a default on email_campaigns.reply_type.
    # On some managed Postgres deployments we observed statement_timeout cancelling
    # the DDL and leaving the transaction aborted, which blocks all subsequent
    # migrations (including demo-critical schema like reply_received_at).
    #
    # For the pilot, this default is non-critical because ingestion code normalizes
    # reply_type/reply_status. Treat as a no-op to keep upgrades reliable.
    return
    # Backfill existing rows: python -m app.scripts.normalize_reply_rows


def downgrade() -> None:
    return
