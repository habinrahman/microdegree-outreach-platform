"""Add reply_received_at (inbound truth) on email_campaigns; backfill from replied_at / reply_detected_at.

Revision ID: 20260428_0014_reply_received_at
Revises: 20260423_0013_autonomous_sequencer_v1
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "20260428_0014_reply_received_at"
down_revision = "20260423_0013_autonomous_sequencer_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = getattr(bind.dialect, "name", "") if bind else ""

    if dialect == "postgresql":
        op.execute(
            """
            ALTER TABLE email_campaigns
              ADD COLUMN IF NOT EXISTS reply_received_at TIMESTAMP NULL;
            """
        )
        op.execute(
            text(
                """
                UPDATE email_campaigns
                SET reply_received_at = COALESCE(replied_at, reply_detected_at)
                WHERE reply_received_at IS NULL
                  AND replied IS TRUE
                  AND COALESCE(replied_at, reply_detected_at) IS NOT NULL
                """
            )
        )
    else:
        with op.batch_alter_table("email_campaigns") as batch:
            if bind is not None and not _has_column(bind, "email_campaigns", "reply_received_at"):
                batch.add_column(sa.Column("reply_received_at", sa.DateTime(), nullable=True))
        if bind is not None:
            bind.execute(
                text(
                    """
                    UPDATE email_campaigns
                    SET reply_received_at = COALESCE(replied_at, reply_detected_at)
                    WHERE reply_received_at IS NULL
                      AND replied = 1
                      AND COALESCE(replied_at, reply_detected_at) IS NOT NULL
                    """
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = getattr(bind.dialect, "name", "") if bind else ""

    if dialect == "postgresql":
        op.execute("ALTER TABLE email_campaigns DROP COLUMN IF EXISTS reply_received_at;")
    else:
        with op.batch_alter_table("email_campaigns") as batch:
            if bind is not None and _has_column(bind, "email_campaigns", "reply_received_at"):
                batch.drop_column("reply_received_at")


def _has_column(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    cols = [c.get("name") for c in insp.get_columns(table)]
    return column in cols
