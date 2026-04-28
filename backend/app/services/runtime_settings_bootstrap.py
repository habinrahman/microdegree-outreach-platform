"""
Idempotent ``runtime_settings`` DDL + default seed (production schema drift safety).

Used by: Alembic migration, ``init_db`` Postgres bootstrap, and ``set_followups_dispatch_enabled``
when the table is missing (e.g. migration never applied).
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

KEY_FOLLOWUPS_DISPATCH = "followups_dispatch_enabled"
KEY_OUTBOUND_ENABLED = "outbound_enabled"


def ensure_runtime_settings_schema_connection(connection: Connection) -> None:
    """
    Create ``runtime_settings`` if missing and seed ``followups_dispatch_enabled`` when absent.

    Safe to run inside an Alembic migration transaction or ``engine.begin()`` block.
    """
    dialect = connection.dialect.name
    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS runtime_settings (
                    id VARCHAR(36) PRIMARY KEY NOT NULL,
                    key VARCHAR(128) NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_runtime_settings_key "
                "ON runtime_settings (key)"
            )
        )
    elif dialect.startswith("sqlite"):
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS runtime_settings (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    key VARCHAR(128) NOT NULL,
                    value TEXT NOT NULL,
                    updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP)
                )
                """
            )
        )
        connection.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS uq_runtime_settings_key ON runtime_settings (key)")
        )
    else:
        logger.warning("runtime_settings bootstrap: unsupported dialect %r", dialect)
        return

    def _seed_if_missing(key: str, value: str) -> None:
        row = connection.execute(
            text("SELECT 1 FROM runtime_settings WHERE key = :k LIMIT 1"),
            {"k": key},
        ).first()
        if row is None:
            connection.execute(
                text(
                    "INSERT INTO runtime_settings (id, key, value, updated_at) "
                    "VALUES (:id, :k, :v, CURRENT_TIMESTAMP)"
                ),
                {"id": str(uuid.uuid4()), "k": key, "v": value},
            )
            logger.info("runtime_settings bootstrap: seeded %s=%s", key, value)

    _seed_if_missing(KEY_FOLLOWUPS_DISPATCH, "true")
    # SAFETY: outbound must be explicitly enabled by an operator.
    _seed_if_missing(KEY_OUTBOUND_ENABLED, "false")


def ensure_runtime_settings_schema_for_engine(engine: Engine) -> None:
    """Committed DDL + seed (separate transaction from ORM session work)."""
    try:
        with engine.begin() as conn:
            ensure_runtime_settings_schema_connection(conn)
    except Exception:
        logger.exception("runtime_settings bootstrap failed")
        raise
