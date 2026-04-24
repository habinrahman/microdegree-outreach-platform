"""Admin backup endpoints (SQLite snapshot)."""
import os
import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database.config import DATABASE_URL
from app.database import get_db
from app.models import AuditLog
from app.services.audit import log_event
from app.services.fixture_residual_purge import build_extended_audit, post_purge_integrity_audit
from app.services.backup_health import build_backup_health_payload, write_backup_manifest
from app.services.deliverability_layer import build_deliverability_health_summary

router = APIRouter(
    prefix="/admin",
    tags=["admin_backups"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/logs")
def admin_logs_list(db: Session = Depends(get_db), limit: int = 200):
    """Recent audit events (open in local dev; use /audit/ + admin key when locking down)."""
    rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 1000)).all()
    return [
        {
            "id": str(r.id),
            "actor": r.actor,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "meta": r.meta,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/backup-health")
def admin_backup_health(db: Session = Depends(get_db)):
    """Read-only: backup manifests, on-disk presence, structural integrity, DR hints."""
    return build_backup_health_payload(db)


@router.get("/deliverability-health")
def admin_deliverability_health(db: Session = Depends(get_db)):
    """Read-only: deliverability layer status + aggregate send health (no secrets)."""
    return build_deliverability_health_summary(db)


@router.get("/fixture-audit")
def admin_fixture_audit(db: Session = Depends(get_db)):
    """
    Read-only fixture pollution + integrity snapshot for operators.
    Does not mutate data. Use CLI scripts for schema bootstrap / purge.
    """
    ext = build_extended_audit(db)
    integrity = post_purge_integrity_audit(db)
    return {
        "extended_audit": ext,
        "integrity": integrity,
        "suggested_commands": {
            "verify_fixture_columns": "python -m app.scripts.ensure_fixture_columns --verify-only",
            "ensure_fixture_columns": "python -m app.scripts.ensure_fixture_columns",
            "purge_audit": "python -m app.scripts.purge_residual_fixture_families --audit",
            "purge_preview": "python -m app.scripts.purge_residual_fixture_families",
        },
    }


def _sqlite_db_path() -> str | None:
    if not DATABASE_URL.startswith("sqlite"):
        return None
    # sqlite:///./file.db OR sqlite:////abs/path.db
    u = DATABASE_URL.replace("sqlite:///", "", 1)
    if u.startswith("/"):
        return u
    # relative to backend/ cwd
    return os.path.abspath(os.path.join(os.getcwd(), u))


def _run_sqlite_backup(db):
    path = _sqlite_db_path()
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=400, detail="SQLite DB not found or not using SQLite")

    backups_dir = os.path.abspath(os.path.join(os.getcwd(), "backups"))
    os.makedirs(backups_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(backups_dir, f"microdegree_outreach_{ts}.db")
    shutil.copy2(path, dst)
    rel = os.path.basename(dst)
    try:
        write_backup_manifest(
            backups_dir=backups_dir,
            kind="sqlite_file",
            relative_file=rel,
            extra={"bytes": os.path.getsize(dst)},
        )
    except Exception:
        pass
    try:
        log_event(
            db,
            actor="admin",
            action="sqlite_backup_created",
            entity_type="Backup",
            entity_id=rel,
            meta={},
        )
    except Exception:
        pass
    return {"ok": True, "backup_file": rel}


@router.post("/backup")
def backup_sqlite_alias(db=Depends(get_db)):
    """Dashboard alias (open locally; prefer /admin/backup/sqlite + admin key when hardened)."""
    return _run_sqlite_backup(db)


@router.post("/backup/sqlite")
def backup_sqlite(db=Depends(get_db)):
    return _run_sqlite_backup(db)


@router.get("/backup/sqlite/download/{filename}")
def download_sqlite_backup(filename: str, _auth: bool = Depends(require_api_key)):
    backups_dir = os.path.abspath(os.path.join(os.getcwd(), "backups"))
    safe = os.path.basename(filename)
    full = os.path.join(backups_dir, safe)
    if not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(full, filename=safe, media_type="application/octet-stream")

