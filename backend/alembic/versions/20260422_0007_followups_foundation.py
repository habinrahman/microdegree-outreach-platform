"""Step 1 follow-ups foundation (schema only, no behavior changes).

Revision ID: 20260422_0007_followups_foundation
Revises: 20260418_0006_campaign_idx
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260422_0007_followups_foundation"
down_revision = "20260418_0006_campaign_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) student_templates table (safe storage of per-student templates)
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("student_templates"):
        op.create_table(
            "student_templates",
            sa.Column("id", sa.String(36), primary_key=True, nullable=False),
            sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id"), nullable=False),
            sa.Column("template_type", sa.String(20), nullable=False),  # INITIAL | FOLLOWUP_1..3
            sa.Column("subject", sa.Text(), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("student_id", "template_type", name="uq_student_templates_student_type"),
        )

    # 2) email_campaigns additions (do not change existing semantics)
    dialect = getattr(bind, "dialect", None)
    name = getattr(dialect, "name", "") if dialect else ""

    if name == "postgresql":
        # Only add columns if missing. Do NOT alter existing email_type column/type/default.
        op.execute(
            """
            ALTER TABLE email_campaigns
              ADD COLUMN IF NOT EXISTS follow_up_step INTEGER NOT NULL DEFAULT 0;
            """
        )
        # The repo already has an email_type column; this is a no-op if it exists.
        op.execute(
            """
            ALTER TABLE email_campaigns
              ADD COLUMN IF NOT EXISTS email_type VARCHAR(20) NOT NULL DEFAULT 'INITIAL';
            """
        )
        op.execute(
            """
            UPDATE email_campaigns
            SET follow_up_step = 0
            WHERE follow_up_step IS NULL;
            """
        )
    else:
        # SQLite / other dialects: use Alembic ops (no IF NOT EXISTS support for columns).
        # This is still safe for local dev; production should run Postgres migrations.
        with op.batch_alter_table("email_campaigns") as batch:
            if not _has_column("email_campaigns", "follow_up_step"):
                batch.add_column(sa.Column("follow_up_step", sa.Integer(), nullable=False, server_default="0"))
        op.execute("UPDATE email_campaigns SET follow_up_step = 0 WHERE follow_up_step IS NULL")


def downgrade() -> None:
    # Reverse is best-effort: we drop the new table and follow_up_step column.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("student_templates"):
        op.drop_table("student_templates")

    name = getattr(getattr(bind, "dialect", None), "name", "") if bind else ""
    if name == "postgresql":
        op.execute("ALTER TABLE email_campaigns DROP COLUMN IF EXISTS follow_up_step;")
        # Do not drop email_type: it existed before this revision in this repo.
    else:
        with op.batch_alter_table("email_campaigns") as batch:
            if _has_column("email_campaigns", "follow_up_step"):
                batch.drop_column("follow_up_step")


def _has_column(table: str, column: str) -> bool:
    # Lightweight cross-dialect check; avoids importing app metadata.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c.get("name") for c in insp.get_columns(table)]
    return column in cols

