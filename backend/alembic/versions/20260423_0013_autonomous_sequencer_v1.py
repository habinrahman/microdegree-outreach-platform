"""Autonomous Sequencer v1: sequence_state, overdue flags, sequencer export flag.

Revision ID: 20260423_0013_autonomous_sequencer_v1
Revises: 20260423_0012_runtime_settings_idempotent
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "20260423_0013_autonomous_sequencer_v1"
down_revision = "20260423_0012_runtime_settings_idempotent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = getattr(bind.dialect, "name", "") if bind else ""

    if dialect == "postgresql":
        op.execute(
            """
            ALTER TABLE email_campaigns
              ADD COLUMN IF NOT EXISTS sequence_state VARCHAR(48) NULL;
            """
        )
        op.execute(
            """
            ALTER TABLE email_campaigns
              ADD COLUMN IF NOT EXISTS overdue_late BOOLEAN NOT NULL DEFAULT FALSE;
            """
        )
        op.execute(
            """
            ALTER TABLE email_campaigns
              ADD COLUMN IF NOT EXISTS overdue_first_seen_at TIMESTAMP NULL;
            """
        )
        op.execute(
            """
            ALTER TABLE email_campaigns
              ADD COLUMN IF NOT EXISTS exported_sequencer_sheet BOOLEAN NOT NULL DEFAULT FALSE;
            """
        )
    else:
        with op.batch_alter_table("email_campaigns") as batch:
            if not _has_column(bind, "email_campaigns", "sequence_state"):
                batch.add_column(sa.Column("sequence_state", sa.String(48), nullable=True))
            if not _has_column(bind, "email_campaigns", "overdue_late"):
                batch.add_column(sa.Column("overdue_late", sa.Boolean(), nullable=False, server_default=sa.false()))
            if not _has_column(bind, "email_campaigns", "overdue_first_seen_at"):
                batch.add_column(sa.Column("overdue_first_seen_at", sa.DateTime(), nullable=True))
            if not _has_column(bind, "email_campaigns", "exported_sequencer_sheet"):
                batch.add_column(
                    sa.Column("exported_sequencer_sheet", sa.Boolean(), nullable=False, server_default=sa.false())
                )

    # Backfill lifecycle from existing terminal_outcome (seq 1 only).
    if dialect == "postgresql":
        op.execute(
            text(
                """
                UPDATE email_campaigns
                SET sequence_state = 'ACTIVE_SEQUENCE'
                WHERE sequence_number = 1 AND sequence_state IS NULL
                """
            )
        )
        op.execute(
            text(
                """
                UPDATE email_campaigns
                SET sequence_state = 'TERMINATED_REPLIED'
                WHERE sequence_number = 1
                  AND terminal_outcome LIKE 'REPLIED_AFTER_%'
                """
            )
        )
        op.execute(
            text(
                """
                UPDATE email_campaigns
                SET sequence_state = 'COMPLETED_NO_RESPONSE'
                WHERE sequence_number = 1 AND terminal_outcome = 'NO_RESPONSE_COMPLETED'
                """
            )
        )
        op.execute(
            text(
                """
                UPDATE email_campaigns
                SET sequence_state = 'BOUNCED_TERMINAL'
                WHERE sequence_number = 1 AND terminal_outcome = 'BOUNCED'
                """
            )
        )
        op.execute(
            text(
                """
                UPDATE email_campaigns
                SET sequence_state = 'PAUSED_UNKNOWN'
                WHERE sequence_number = 1 AND terminal_outcome = 'PAUSED_UNKNOWN_OUTCOME'
                """
            )
        )
    else:
        conn = bind
        conn.execute(
            text(
                """
                UPDATE email_campaigns
                SET sequence_state = 'ACTIVE_SEQUENCE'
                WHERE sequence_number = 1 AND sequence_state IS NULL
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE email_campaigns
                SET sequence_state = 'TERMINATED_REPLIED'
                WHERE sequence_number = 1
                  AND terminal_outcome LIKE 'REPLIED_AFTER_%'
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE email_campaigns
                SET sequence_state = 'COMPLETED_NO_RESPONSE'
                WHERE sequence_number = 1 AND terminal_outcome = 'NO_RESPONSE_COMPLETED'
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE email_campaigns
                SET sequence_state = 'BOUNCED_TERMINAL'
                WHERE sequence_number = 1 AND terminal_outcome = 'BOUNCED'
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE email_campaigns
                SET sequence_state = 'PAUSED_UNKNOWN'
                WHERE sequence_number = 1 AND terminal_outcome = 'PAUSED_UNKNOWN_OUTCOME'
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = getattr(bind.dialect, "name", "") if bind else ""

    if dialect == "postgresql":
        op.execute("ALTER TABLE email_campaigns DROP COLUMN IF EXISTS exported_sequencer_sheet;")
        op.execute("ALTER TABLE email_campaigns DROP COLUMN IF EXISTS overdue_first_seen_at;")
        op.execute("ALTER TABLE email_campaigns DROP COLUMN IF EXISTS overdue_late;")
        op.execute("ALTER TABLE email_campaigns DROP COLUMN IF EXISTS sequence_state;")
    else:
        with op.batch_alter_table("email_campaigns") as batch:
            for col in ("exported_sequencer_sheet", "overdue_first_seen_at", "overdue_late", "sequence_state"):
                if bind is not None and _has_column(bind, "email_campaigns", col):
                    batch.drop_column(col)


def _has_column(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    cols = [c.get("name") for c in insp.get_columns(table)]
    return column in cols
