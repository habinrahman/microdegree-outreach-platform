"""Add is_fixture_test_data to students and hr_contacts (CI-safe fixture tagging).

Revision ID: 20260423_0009_students_hr_fixture_test_data_flags
Revises: 20260422_0008_student_templates_updated_at
Create Date: 2026-04-23

Why this exists in addition to ``init_db`` → ``_ensure_postgres_columns()``:
- Production/staging often applies schema via Alembic only; API startup may not run
  ``init_db`` on every deploy, or may skip when ``ALEMBIC_UPGRADE_ON_START`` is off.
- Alembic remains the auditable, operator-run source of truth for Postgres DDL.
"""

from alembic import op


revision = "20260423_0009_students_hr_fixture_test_data_flags"
down_revision = "20260422_0008_student_templates_updated_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Idempotent add: IF NOT EXISTS keeps re-runs safe.
    op.execute(
        """
        ALTER TABLE students
          ADD COLUMN IF NOT EXISTS is_fixture_test_data BOOLEAN DEFAULT FALSE;
        """
    )
    op.execute(
        """
        ALTER TABLE hr_contacts
          ADD COLUMN IF NOT EXISTS is_fixture_test_data BOOLEAN DEFAULT FALSE;
        """
    )
    # Backfill any NULLs (e.g. partial manual DDL) before NOT NULL.
    op.execute("UPDATE students SET is_fixture_test_data = FALSE WHERE is_fixture_test_data IS NULL;")
    op.execute("UPDATE hr_contacts SET is_fixture_test_data = FALSE WHERE is_fixture_test_data IS NULL;")

    op.execute(
        """
        ALTER TABLE students
          ALTER COLUMN is_fixture_test_data SET DEFAULT FALSE;
        """
    )
    op.execute(
        """
        ALTER TABLE students
          ALTER COLUMN is_fixture_test_data SET NOT NULL;
        """
    )
    op.execute(
        """
        ALTER TABLE hr_contacts
          ALTER COLUMN is_fixture_test_data SET DEFAULT FALSE;
        """
    )
    op.execute(
        """
        ALTER TABLE hr_contacts
          ALTER COLUMN is_fixture_test_data SET NOT NULL;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE students DROP COLUMN IF EXISTS is_fixture_test_data;")
    op.execute("ALTER TABLE hr_contacts DROP COLUMN IF EXISTS is_fixture_test_data;")
