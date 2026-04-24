import logging
import os

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.database.config import get_db

router = APIRouter(prefix="/health", tags=["Health"])
logger = logging.getLogger(__name__)


@router.get("/")
def health_check(db: Session = Depends(get_db)):
    """Liveness: verify DB connectivity only (no business queries)."""
    db.execute(text("SELECT 1"))
    logger.info("DB connected")
    return {"status": "ok", "db": "ok"}


@router.get("/schema-launch-gate")
def health_schema_launch_gate(db: Session = Depends(get_db)):
    """
    Critical table presence (schema drift). Same payload fragment as ``GET /admin/reliability`` → ``schema_launch_gate``.
    """
    from app.services.schema_launch_gate import audit_critical_schema

    return audit_critical_schema(db)


@router.get("/scheduler/status")
def scheduler_status():
    """Explicit scheduler heartbeat for dashboards (mirrors health payload)."""
    try:
        from app.services import campaign_scheduler as cs

        sch = getattr(cs, "_scheduler", None)
        running = sch is not None and getattr(sch, "running", False)
        return {"scheduler": "running" if running else "stopped"}
    except Exception:
        return {"scheduler": "unknown"}


@router.get("/scheduler/metrics")
def scheduler_metrics():
    """Lightweight in-process scheduler metrics (no secrets)."""
    try:
        from app.services.campaign_scheduler import scheduler_metrics_snapshot

        return scheduler_metrics_snapshot()
    except Exception:
        return {"running": False, "jobs": {}, "error": "metrics_unavailable"}


@router.get("/sheet-sync/trigger")
def sheet_sync_trigger_health():
    """Debug-only-ish: shows last async sheet sync trigger timestamp."""
    try:
        from app.services.sheet_sync_trigger import sheet_sync_trigger_status

        return sheet_sync_trigger_status()
    except Exception:
        return {"last_trigger_at_utc": None}


@router.get("/sheet-sync/status")
def sheet_sync_status(db: Session = Depends(get_db)):
    """
    Mirror drift protection: report pending count + oldest pending age and classify health.

    Thresholds:
    - SHEET_SYNC_WARN_MINUTES (default 10)
    - SHEET_SYNC_CRIT_MINUTES (default 30)
    """
    from app.services.sheet_sync import sheet_sync_status as _status

    warn_m = int((os.getenv("SHEET_SYNC_WARN_MINUTES") or "10").strip() or "10")
    crit_m = int((os.getenv("SHEET_SYNC_CRIT_MINUTES") or "30").strip() or "30")
    stuck_m = int((os.getenv("SHEET_SYNC_STUCK_MINUTES") or "20").strip() or "20")
    warn_m = max(1, warn_m)
    crit_m = max(warn_m + 1, crit_m)
    stuck_m = max(1, stuck_m)

    s = _status(db)
    age_sec = int(s.get("oldest_pending_age_sec") or 0)
    pending = int(s.get("pending_total") or 0)
    level = "ok"
    stuck = False
    if pending > 0:
        if age_sec >= crit_m * 60:
            level = "critical"
        elif age_sec >= warn_m * 60:
            level = "warning"

    # Stuck detector: pending is growing but we haven't observed a successful sync in a while.
    # This catches "scheduler running" but sync job hung/zombied or lock held forever.
    last_success = (s.get("last_success_at_utc") or "").strip() or None
    last_increase = (s.get("last_pending_increase_at_utc") or "").strip() or None
    now = datetime.now(timezone.utc)
    try:
        last_success_dt = datetime.fromisoformat(last_success) if last_success else None
    except Exception:
        last_success_dt = None
    try:
        last_increase_dt = datetime.fromisoformat(last_increase) if last_increase else None
    except Exception:
        last_increase_dt = None
    if pending > 0 and last_increase_dt is not None:
        success_age = (now - last_success_dt).total_seconds() if last_success_dt is not None else 10**9
        if success_age >= stuck_m * 60:
            stuck = True
            # Escalate: "stuck" is strictly worse than "warning" lag.
            level = "critical"

    return {
        **s,
        "thresholds": {"warn_minutes": warn_m, "critical_minutes": crit_m, "stuck_minutes": stuck_m},
        "health": level,
        "stuck_suspected": bool(stuck),
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/config")
def health_config():
    """
    Safe self-report for config drift debugging (no secrets).
    """
    env_name = (os.getenv("APP_ENV") or os.getenv("ENV") or os.getenv("ENVIRONMENT") or "dev").strip()
    scheduler_enabled = os.getenv("DISABLE_SCHEDULER", "").strip().lower() not in ("1", "true", "yes")
    cors_configured = bool((os.getenv("CORS_ALLOW_ORIGINS") or "").strip() or (os.getenv("CORS_ALLOW_ORIGIN_REGEX") or "").strip())
    port_raw = (os.getenv("PORT") or "").strip()
    try:
        api_port = int(port_raw) if port_raw else 8010
    except Exception:
        api_port = 8010

    return {
        "environment": env_name or "dev",
        "api_port": api_port,
        "scheduler_enabled": scheduler_enabled,
        "cors_configured": cors_configured,
    }
