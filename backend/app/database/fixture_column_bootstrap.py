"""
Bootstrap ``is_fixture_test_data`` on ``students`` and ``hr_contacts``.

Used when Alembic / Supabase SQL editor are unreliable: connect with ``DATABASE_URL``
and apply idempotent DDL + backfill. Postgres and SQLite supported.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def verify_fixture_columns(engine: Engine) -> dict[str, Any]:
    """Return presence + nullability hints for fixture columns (no DDL)."""
    dialect = engine.dialect.name
    out: dict[str, Any] = {"dialect": dialect, "students": False, "hr_contacts": False, "details": {}}
    if dialect == "postgresql":
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT table_name, column_name, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name IN ('students', 'hr_contacts')
                      AND column_name = 'is_fixture_test_data'
                    """
                )
            ).fetchall()
            for r in rows:
                tbl, col, nullable, default = str(r[0]), str(r[1]), str(r[2]), r[3]
                out["details"][tbl] = {"is_nullable": nullable, "column_default": str(default) if default is not None else None}
                if tbl == "students":
                    out["students"] = True
                if tbl == "hr_contacts":
                    out["hr_contacts"] = True
    elif dialect.startswith("sqlite"):
        with engine.connect() as conn:
            for tbl in ("students", "hr_contacts"):
                info = conn.execute(text(f'PRAGMA table_info("{tbl}")')).fetchall()
                # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
                names = {str(row[1]).lower() for row in info}
                present = "is_fixture_test_data" in names
                if tbl == "students":
                    out["students"] = present
                else:
                    out["hr_contacts"] = present
                out["details"][tbl] = {"pragma_columns": sorted(names)}
    else:
        out["details"]["note"] = f"verify_fixture_columns: dialect {dialect!r} not explicitly handled"
    out["fixture_columns_present"] = bool(out.get("students")) and bool(out.get("hr_contacts"))
    return out


def _apply_postgres(engine: Engine) -> None:
    stmts = [
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS is_fixture_test_data BOOLEAN DEFAULT FALSE",
        "ALTER TABLE hr_contacts ADD COLUMN IF NOT EXISTS is_fixture_test_data BOOLEAN DEFAULT FALSE",
        "UPDATE students SET is_fixture_test_data = FALSE WHERE is_fixture_test_data IS NULL",
        "UPDATE hr_contacts SET is_fixture_test_data = FALSE WHERE is_fixture_test_data IS NULL",
        "ALTER TABLE students ALTER COLUMN is_fixture_test_data SET DEFAULT FALSE",
        "ALTER TABLE students ALTER COLUMN is_fixture_test_data SET NOT NULL",
        "ALTER TABLE hr_contacts ALTER COLUMN is_fixture_test_data SET DEFAULT FALSE",
        "ALTER TABLE hr_contacts ALTER COLUMN is_fixture_test_data SET NOT NULL",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))


def _apply_sqlite(engine: Engine) -> None:
    """SQLite: add missing column only (create_all already defines it for new DBs)."""
    with engine.begin() as conn:
        for tbl in ("students", "hr_contacts"):
            info = conn.execute(text(f'PRAGMA table_info("{tbl}")')).fetchall()
            names = {str(row[1]).lower() for row in info}
            if "is_fixture_test_data" in names:
                continue
            # NOT NULL DEFAULT 0 is portable for SQLite booleans
            conn.execute(text(f'ALTER TABLE "{tbl}" ADD COLUMN is_fixture_test_data BOOLEAN NOT NULL DEFAULT 0'))


def ensure_fixture_columns_bootstrap(
    engine: Engine,
    *,
    verify_only: bool = False,
    strict: bool = True,
) -> dict[str, Any]:
    """
    Ensure columns exist and are NOT NULL with default FALSE.

    If ``strict`` is True, any DDL/verification failure raises (no swallowed errors).
    """
    before = verify_fixture_columns(engine)
    if verify_only:
        return {"before": before, "after": before, "changed": False, "verify_only": True}

    dialect = engine.dialect.name
    try:
        if dialect == "postgresql":
            _apply_postgres(engine)
        elif dialect.startswith("sqlite"):
            _apply_sqlite(engine)
        else:
            if strict:
                raise RuntimeError(f"ensure_fixture_columns_bootstrap: unsupported dialect {dialect!r}")
            logger.warning("Skipping fixture column bootstrap for dialect=%s", dialect)
            return {"before": before, "after": before, "changed": False, "skipped": True}

        after = verify_fixture_columns(engine)
        if strict and not after.get("fixture_columns_present"):
            raise RuntimeError(f"Fixture columns missing after bootstrap: {after!r}")
        # True only when columns were missing before this run (idempotent re-runs report False).
        changed = not bool(before.get("fixture_columns_present"))
        return {"before": before, "after": after, "changed": changed, "verify_only": False}
    except Exception:
        logger.exception("ensure_fixture_columns_bootstrap failed (strict mode)")
        raise
