"""Outbound safety controls: suppression list table + outbound_enabled runtime key seed.

Revision ID: 20260428_0020_outbound_safety_controls
Revises: 20260428_0015_student_resume_lifecycle
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260428_0020_outbound_safety_controls"
down_revision = "20260428_0015_student_resume_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = getattr(bind.dialect, "name", "") if bind else ""

    if dialect == "postgresql":
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS outbound_suppressions (
              id VARCHAR(36) PRIMARY KEY NOT NULL,
              email VARCHAR(320) NOT NULL,
              email_lower VARCHAR(320) NOT NULL,
              reason TEXT NULL,
              source TEXT NULL,
              is_active BOOLEAN NOT NULL DEFAULT TRUE,
              suppressed_until TIMESTAMP NULL,
              created_at TIMESTAMP NOT NULL DEFAULT NOW(),
              updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
            """
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_outbound_suppressions_email_lower "
            "ON outbound_suppressions (email_lower)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbound_suppressions_active "
            "ON outbound_suppressions (is_active)"
        )
    else:
        # SQLite / other: use SQLAlchemy DDL
        op.create_table(
            "outbound_suppressions",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("email_lower", sa.String(length=320), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("source", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("suppressed_until", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("uq_outbound_suppressions_email_lower", "outbound_suppressions", ["email_lower"], unique=True)
        op.create_index("idx_outbound_suppressions_active", "outbound_suppressions", ["is_active"], unique=False)

    # Seed runtime setting key (best-effort; table may be missing in edge deploys).
    # We intentionally do NOT fail migration if runtime_settings is unavailable.
    try:
        from app.services.runtime_settings_bootstrap import ensure_runtime_settings_schema_connection, KEY_OUTBOUND_ENABLED
        import uuid
        from sqlalchemy import text

        conn = op.get_bind()
        if conn is not None:
            ensure_runtime_settings_schema_connection(conn)
            row = conn.execute(text("SELECT 1 FROM runtime_settings WHERE key = :k LIMIT 1"), {"k": KEY_OUTBOUND_ENABLED}).first()
            if row is None:
                conn.execute(
                    text(
                        "INSERT INTO runtime_settings (id, key, value, updated_at) "
                        "VALUES (:id, :k, :v, CURRENT_TIMESTAMP)"
                    ),
                    {"id": str(uuid.uuid4()), "k": KEY_OUTBOUND_ENABLED, "v": "true"},
                )
    except Exception:
        pass


def downgrade() -> None:
    bind = op.get_bind()
    dialect = getattr(bind.dialect, "name", "") if bind else ""

    if dialect == "postgresql":
        op.execute("DROP TABLE IF EXISTS outbound_suppressions;")
    else:
        op.drop_index("idx_outbound_suppressions_active", table_name="outbound_suppressions")
        op.drop_index("uq_outbound_suppressions_email_lower", table_name="outbound_suppressions")
        op.drop_table("outbound_suppressions")

