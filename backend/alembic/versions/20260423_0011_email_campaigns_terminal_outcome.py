"""email_campaigns.terminal_outcome (campaign pair analytics).

Revision ID: 20260423_0011_email_campaigns_terminal_outcome
Revises: 20260423_0010_autonomous_sequencer
"""

from alembic import op
import sqlalchemy as sa


revision = "20260423_0011_email_campaigns_terminal_outcome"
down_revision = "20260423_0010_autonomous_sequencer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = getattr(bind.dialect, "name", "") if bind else ""

    if dialect == "postgresql":
        op.execute(
            """
            ALTER TABLE email_campaigns
              ADD COLUMN IF NOT EXISTS terminal_outcome VARCHAR(64) NULL;
            """
        )
    else:
        with op.batch_alter_table("email_campaigns") as batch:
            if not _has_column(bind, "email_campaigns", "terminal_outcome"):
                batch.add_column(sa.Column("terminal_outcome", sa.String(64), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    dialect = getattr(bind.dialect, "name", "") if bind else ""

    if dialect == "postgresql":
        op.execute("ALTER TABLE email_campaigns DROP COLUMN IF EXISTS terminal_outcome;")
    else:
        with op.batch_alter_table("email_campaigns") as batch:
            if bind is not None and _has_column(bind, "email_campaigns", "terminal_outcome"):
                batch.drop_column("terminal_outcome")


def _has_column(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    cols = [c.get("name") for c in insp.get_columns(table)]
    return column in cols
