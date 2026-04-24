"""Add updated_at to student_templates for optimistic concurrency.

Revision ID: 20260422_0008_student_templates_updated_at
Revises: 20260422_0007_followups_foundation
Create Date: 2026-04-22
"""

from alembic import op

revision = "20260422_0008_student_templates_updated_at"
down_revision = "20260422_0007_followups_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        ALTER TABLE student_templates
          ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;
        """
    )
    op.execute(
        """
        UPDATE student_templates
        SET updated_at = created_at
        WHERE updated_at IS NULL;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE student_templates DROP COLUMN IF EXISTS updated_at;")

