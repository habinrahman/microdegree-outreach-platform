"""Backup artifact indexing + operator health payload (read-only)."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.database.config import DATABASE_URL
from app.services.backup_pg import is_postgres_database_url, redact_database_url, safe_db_url_host
from app.services.db_integrity_checks import run_corruption_integrity_checks

logger = logging.getLogger(__name__)


def default_backups_dir() -> Path:
    raw = (os.getenv("BACKUPS_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(os.getcwd()) / "backups"


def write_backup_manifest(
    *,
    backups_dir: Path | str,
    kind: str,
    relative_file: str,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write a small JSON manifest next to backup files for dashboard / automation."""
    backups_dir = Path(backups_dir)
    backups_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = backups_dir / f"backup_manifest_{ts}.json"
    body: dict[str, Any] = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "relative_file": relative_file,
        "database_dialect": "postgresql" if is_postgres_database_url(DATABASE_URL or "") else "sqlite",
        "database_url_redacted": redact_database_url(DATABASE_URL or ""),
        "database_host": safe_db_url_host(DATABASE_URL or ""),
    }
    if extra:
        body.update(extra)
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return path


def _load_manifest(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("bad manifest %s: %s", path, e)
        return None


def list_recent_manifests(backups_dir: Path, *, limit: int = 12) -> list[dict[str, Any]]:
    if not backups_dir.is_dir():
        return []
    files = sorted(backups_dir.glob("backup_manifest_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for p in files[:limit]:
        m = _load_manifest(p)
        if m:
            m["_manifest_path"] = str(p)
            out.append(m)
    return out


def _artifact_exists(backups_dir: Path, relative_file: str) -> bool:
    return (backups_dir / relative_file).is_file()


def build_backup_health_payload(db: Session) -> dict[str, Any]:
    """
    Operator snapshot: recent manifests, on-disk presence, DB integrity, suggested commands.
    """
    backups_dir = default_backups_dir()
    manifests = list_recent_manifests(backups_dir, limit=15)
    enriched: list[dict[str, Any]] = []
    for m in manifests:
        rel = m.get("relative_file")
        exists = bool(rel) and _artifact_exists(backups_dir, str(rel))
        enriched.append({**m, "artifact_exists": exists})
    integrity = run_corruption_integrity_checks(db)
    dialect = "postgresql" if is_postgres_database_url(DATABASE_URL or "") else "sqlite"
    last_ok = None
    for m in enriched:
        if not m.get("artifact_exists"):
            continue
        if m.get("kind") == "postgres_custom_verify" and m.get("pg_restore_list_ok"):
            last_ok = m.get("created_at_utc")
            break
        if m.get("kind") in ("postgres_custom", "sqlite_file") and m.get("pg_dump_ok") is not False:
            last_ok = m.get("created_at_utc")
            break
    return {
        "backups_dir": str(backups_dir),
        "database_dialect": dialect,
        "recent_manifests": enriched,
        "last_verified_backup_hint_utc": last_ok,
        "integrity": integrity,
        "suggested_commands": {
            "pg_dump": "python -m app.scripts.pg_dump_backup --verify",
            "restore_drill_verify": "python -m app.scripts.restore_drill_verify --dump ./backups/your.dump",
            "export_snapshot": "python -m app.scripts.export_operator_snapshot --out ./exports/snapshot",
            "nightly_integrity": "python -m app.scripts.nightly_integrity_verify",
            "restore_list": "pg_restore --list ./backups/your.dump",
        },
        "panic_rollback_notes": [
            "Stop app traffic (scale to 0 or maintenance page).",
            "Restore Postgres from provider snapshot / PITR to a NEW instance; validate with read-only queries.",
            "Point DATABASE_URL at restored DB; run Alembic if needed; smoke-test; cut over.",
            "For mistaken data deletes (not whole DB), use row-level exports + targeted restore scripts.",
        ],
    }
