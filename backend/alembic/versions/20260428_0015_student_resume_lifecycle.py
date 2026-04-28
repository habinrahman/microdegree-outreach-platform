"""Student resume lifecycle: updated_at + soft-archive path for Update Resume.

Revision ID: 20260428_0015_student_resume_lifecycle
Revises: 20260428_0014_reply_received_at
"""

from alembic import op
import sqlalchemy as sa


revision = "20260428_0015_student_resume_lifecycle"
down_revision = "20260428_0014_reply_received_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = getattr(bind.dialect, "name", "") if bind else ""

    if dialect == "postgresql":
        op.execute(
            """
            ALTER TABLE students
              ADD COLUMN IF NOT EXISTS resume_updated_at TIMESTAMP NULL;
            """
        )
        op.execute(
            """
            ALTER TABLE students
              ADD COLUMN IF NOT EXISTS resume_archive_path TEXT NULL;
            """
        )
    else:
        with op.batch_alter_table("students") as batch:
            if bind is not None and not _has_column(bind, "students", "resume_updated_at"):
                batch.add_column(sa.Column("resume_updated_at", sa.DateTime(), nullable=True))
            if bind is not None and not _has_column(bind, "students", "resume_archive_path"):
                batch.add_column(sa.Column("resume_archive_path", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    dialect = getattr(bind.dialect, "name", "") if bind else ""

    if dialect == "postgresql":
        op.execute("ALTER TABLE students DROP COLUMN IF EXISTS resume_archive_path;")
        op.execute("ALTER TABLE students DROP COLUMN IF EXISTS resume_updated_at;")
    else:
        with op.batch_alter_table("students") as batch:
            if bind is not None and _has_column(bind, "students", "resume_archive_path"):
                batch.drop_column("resume_archive_path")
            if bind is not None and _has_column(bind, "students", "resume_updated_at"):
                batch.drop_column("resume_updated_at")


def _has_column(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    cols = [c.get("name") for c in insp.get_columns(table)]
    return column in cols
