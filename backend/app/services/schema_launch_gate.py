"""
Launch-gate: verify critical ORM tables exist (schema drift / missed migrations).

Used by SRE reliability payload, optional health route, and startup logging.
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from sqlalchemy import inspect
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class _TableSpec(TypedDict):
    name: str
    control_plane: bool


# Order: data plane first, then control-plane toggles operators rely on.
CRITICAL_TABLES: tuple[_TableSpec, ...] = (
    {"name": "students", "control_plane": False},
    {"name": "hr_contacts", "control_plane": False},
    {"name": "assignments", "control_plane": False},
    {"name": "email_campaigns", "control_plane": False},
    {"name": "runtime_settings", "control_plane": True},
)


def audit_critical_schema(db: Session) -> dict[str, Any]:
    """
    Return per-table presence + overall status.

    - ``critical``: any **control_plane** table (e.g. ``runtime_settings``) is missing.
    - ``degraded``: only non-control tables missing.
    - ``ok``: all listed tables exist.
    """
    try:
        bind = db.get_bind()
        insp = inspect(bind)
    except Exception as e:
        logger.warning("schema_launch_gate: introspection failed: %s", e)
        return {
            "status": "critical",
            "error": str(e)[:500],
            "tables": [],
            "missing_control_plane": [],
            "missing_any": [],
        }

    rows: list[dict[str, Any]] = []
    missing_control: list[str] = []
    missing_any: list[str] = []
    for spec in CRITICAL_TABLES:
        name = spec["name"]
        cp = bool(spec["control_plane"])
        try:
            present = bool(insp.has_table(name))
        except Exception:
            present = False
        rows.append({"name": name, "present": present, "control_plane": cp})
        if not present:
            missing_any.append(name)
            if cp:
                missing_control.append(name)

    if missing_control:
        status = "critical"
    elif missing_any:
        status = "degraded"
    else:
        status = "ok"

    return {
        "status": status,
        "tables": rows,
        "missing_control_plane": missing_control,
        "missing_any": missing_any,
    }


def log_schema_launch_gate_at_startup(db: Session) -> None:
    """Best-effort log line after DB init (no raise)."""
    try:
        snap = audit_critical_schema(db)
        logger.info(
            "schema_launch_gate status=%s missing_any=%s missing_control_plane=%s",
            snap.get("status"),
            snap.get("missing_any"),
            snap.get("missing_control_plane"),
        )
    except Exception as e:
        logger.warning("schema_launch_gate startup log skipped: %s", e)
