"""Runtime operator settings + email_campaigns suppression_reason (autonomous sequencer).

Revision ID: 20260423_0010_autonomous_sequencer
Revises: 20260423_0009_students_hr_fixture_test_data_flags
"""

from alembic import op
import sqlalchemy as sa


revision = "20260423_0010_autonomous_sequencer"
down_revision = "20260423_0009_students_hr_fixture_test_data_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = getattr(bind.dialect, "name", "") if bind else ""

    op.create_table(
        "runtime_settings",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("key", name="uq_runtime_settings_key"),
    )

    if dialect == "postgresql":
        op.execute(
            """
            ALTER TABLE email_campaigns
              ADD COLUMN IF NOT EXISTS suppression_reason TEXT NULL;
            """
        )
    else:
        with op.batch_alter_table("email_campaigns") as batch:
            if not _has_column(bind, "email_campaigns", "suppression_reason"):
                batch.add_column(sa.Column("suppression_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    dialect = getattr(bind.dialect, "name", "") if bind else ""
    op.drop_table("runtime_settings")
    if dialect == "postgresql":
        op.execute("ALTER TABLE email_campaigns DROP COLUMN IF EXISTS suppression_reason;")
    else:
        with op.batch_alter_table("email_campaigns") as batch:
            if bind is not None and _has_column(bind, "email_campaigns", "suppression_reason"):
                batch.drop_column("suppression_reason")


def _has_column(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    cols = [c.get("name") for c in insp.get_columns(table)]
    return column in cols
