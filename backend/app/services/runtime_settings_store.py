"""DB-backed operator settings (single source for runtime toggles)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.models.runtime_setting import RuntimeSetting
from app.services.runtime_settings_bootstrap import (
    KEY_FOLLOWUPS_DISPATCH,
    KEY_OUTBOUND_ENABLED,
    ensure_runtime_settings_schema_for_engine,
)

logger = logging.getLogger(__name__)


def _missing_runtime_settings_table(exc: BaseException) -> bool:
    """Detect missing relation / table across Postgres + SQLite drivers."""
    if isinstance(exc, (ProgrammingError, OperationalError)):
        msg = str(exc).lower()
        if "runtime_settings" in msg and (
            "does not exist" in msg
            or "undefinedtable" in msg.replace(" ", "")
            or "no such table" in msg
        ):
            return True
    orig = getattr(exc, "orig", None)
    if orig is not None and orig is not exc:
        return _missing_runtime_settings_table(orig)
    return False


def _runtime_settings_table_exists(db: Session) -> bool:
    try:
        bind = db.get_bind()
        return bool(inspect(bind).has_table("runtime_settings"))
    except Exception:
        logger.warning("runtime_settings: could not introspect for runtime_settings table", exc_info=True)
        return False


def _get_raw(db: Session, key: str) -> str | None:
    row = db.query(RuntimeSetting).filter(RuntimeSetting.key == key).first()
    return (row.value or "").strip() if row else None


def get_followups_dispatch_enabled(db: Session) -> bool:
    """
    When False, scheduler must not send follow-up steps (rows remain; initial may still send).

    Missing **row** defaults to True (dispatch on if env FOLLOWUPS_ENABLED allows).
    Missing **table** fail-opens to True so deploys without migration do not 500 the app.
    """
    if not _runtime_settings_table_exists(db):
        logger.warning(
            "runtime_settings: table missing; fail-open followups_dispatch_enabled=True "
            "(apply Alembic or rely on startup bootstrap)"
        )
        return True
    try:
        raw = _get_raw(db, KEY_FOLLOWUPS_DISPATCH)
    except Exception as exc:
        if _missing_runtime_settings_table(exc):
            logger.warning(
                "runtime_settings: query failed with missing-table signature; fail-open=True: %s",
                exc,
            )
            return True
        raise
    if raw is None or raw == "":
        return True
    return raw.lower() in ("1", "true", "yes", "on")


def get_followups_dispatch_config_checksum(db: Session) -> dict[str, Any]:
    """
    Operator-facing "why is follow-up off?" summary.

    - ``dispatch_toggle``: stored DB preference when readable; ``null`` if table missing (fail-open).
    - ``effective_dispatch``: env kill-switch ∧ DB toggle (matches automated FU send gate intent).
    - ``source``: ``db`` | ``default_no_row`` | ``fail_open_missing_table``
    """
    from app.config import FOLLOWUPS_ENABLED

    env_on = bool(FOLLOWUPS_ENABLED)
    if not _runtime_settings_table_exists(db):
        return {
            "followups_env_enabled": env_on,
            "dispatch_toggle": None,
            "effective_dispatch": bool(env_on),
            "source": "fail_open_missing_table",
        }
    try:
        raw = _get_raw(db, KEY_FOLLOWUPS_DISPATCH)
    except Exception as exc:
        if _missing_runtime_settings_table(exc):
            return {
                "followups_env_enabled": env_on,
                "dispatch_toggle": None,
                "effective_dispatch": bool(env_on),
                "source": "fail_open_missing_table",
            }
        raise
    if raw is None or raw == "":
        toggle = True
        src = "default_no_row"
    else:
        toggle = raw.lower() in ("1", "true", "yes", "on")
        src = "db"
    return {
        "followups_env_enabled": env_on,
        "dispatch_toggle": toggle,
        "effective_dispatch": bool(env_on and toggle),
        "source": src,
    }


def set_followups_dispatch_enabled(db: Session, enabled: bool) -> None:
    val = "true" if enabled else "false"
    if not _runtime_settings_table_exists(db):
        from app.database.config import engine

        ensure_runtime_settings_schema_for_engine(engine)
        try:
            db.expire_all()
        except Exception:
            pass
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = db.query(RuntimeSetting).filter(RuntimeSetting.key == KEY_FOLLOWUPS_DISPATCH).first()
    if row is None:
        db.add(RuntimeSetting(key=KEY_FOLLOWUPS_DISPATCH, value=val, updated_at=now))
    else:
        row.value = val
        row.updated_at = now
        db.add(row)
    db.commit()
    logger.info("runtime_settings: followups_dispatch_enabled=%s", val)


def get_outbound_enabled(db: Session) -> bool:
    """
    Global kill switch for *any* outbound email dispatch (scheduler + manual sends).

    - Missing table: fail-open to True (maintains compatibility in partially migrated envs).
    - Missing row: defaults to True.
    - Read error (unexpected): fail-closed to False (safer than sending while blind).
    """
    if not _runtime_settings_table_exists(db):
        logger.warning("runtime_settings: table missing; fail-open outbound_enabled=True")
        return True
    try:
        raw = _get_raw(db, KEY_OUTBOUND_ENABLED)
    except Exception as exc:
        if _missing_runtime_settings_table(exc):
            logger.warning("runtime_settings: missing-table signature; fail-open outbound_enabled=True: %s", exc)
            return True
        logger.exception("runtime_settings: outbound_enabled read failed; fail-closed")
        return False
    if raw is None or raw == "":
        return True
    return raw.lower() in ("1", "true", "yes", "on")


def set_outbound_enabled(db: Session, enabled: bool) -> None:
    val = "true" if enabled else "false"
    if not _runtime_settings_table_exists(db):
        from app.database.config import engine

        ensure_runtime_settings_schema_for_engine(engine)
        try:
            db.expire_all()
        except Exception:
            pass
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = db.query(RuntimeSetting).filter(RuntimeSetting.key == KEY_OUTBOUND_ENABLED).first()
    if row is None:
        db.add(RuntimeSetting(key=KEY_OUTBOUND_ENABLED, value=val, updated_at=now))
    else:
        row.value = val
        row.updated_at = now
        db.add(row)
    db.commit()
    logger.info("runtime_settings: outbound_enabled=%s", val)
