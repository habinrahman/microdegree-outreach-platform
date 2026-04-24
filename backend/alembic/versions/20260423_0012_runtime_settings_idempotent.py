"""runtime_settings: idempotent CREATE + seed (drift / missed migration safety).

Revision ID: 20260423_0012_runtime_settings_idempotent
Revises: 20260423_0011_email_campaigns_terminal_outcome
"""

from alembic import op

from app.services.runtime_settings_bootstrap import ensure_runtime_settings_schema_connection


revision = "20260423_0012_runtime_settings_idempotent"
down_revision = "20260423_0011_email_campaigns_terminal_outcome"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    ensure_runtime_settings_schema_connection(bind)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS runtime_settings")
