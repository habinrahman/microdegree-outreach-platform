"""add students.email_health_status (Gmail reputation)

Revision ID: 20260402_0001
Revises:
Create Date: 2026-04-02

Idempotent: skips if column already exists (e.g. applied via legacy DDL).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260402_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("students")]
    if "email_health_status" in cols:
        return
    op.add_column(
        "students",
        sa.Column(
            "email_health_status",
            sa.String(length=32),
            server_default=sa.text("'healthy'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("students")]
    if "email_health_status" not in cols:
        return
    op.drop_column("students", "email_health_status")
