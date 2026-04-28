"""Idempotent DDL bootstrap for outbound_suppressions (drift safety).

This mirrors the repo's existing bootstrap approach (runtime_settings, fixture columns).
It is intentionally conservative and additive only.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def ensure_outbound_suppression_schema_connection(connection) -> None:
    dialect = getattr(getattr(connection, "dialect", None), "name", "") or ""
    if dialect == "postgresql":
        connection.execute(
            text(
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
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_outbound_suppressions_email_lower "
                "ON outbound_suppressions (email_lower)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_outbound_suppressions_active "
                "ON outbound_suppressions (is_active)"
            )
        )
    elif dialect.startswith("sqlite"):
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS outbound_suppressions (
                  id VARCHAR(36) NOT NULL PRIMARY KEY,
                  email VARCHAR(320) NOT NULL,
                  email_lower VARCHAR(320) NOT NULL,
                  reason TEXT NULL,
                  source TEXT NULL,
                  is_active BOOLEAN NOT NULL DEFAULT 1,
                  suppressed_until DATETIME NULL,
                  created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                  updated_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP)
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_outbound_suppressions_email_lower "
                "ON outbound_suppressions (email_lower)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_outbound_suppressions_active "
                "ON outbound_suppressions (is_active)"
            )
        )
    else:
        logger.warning("outbound_suppressions bootstrap: unsupported dialect %r", dialect)

