"""Admin SRE / observability endpoints (read-only + Prometheus text)."""

import os

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.services.observability_metrics import prometheus_text
from app.services.sre_reliability import build_reliability_payload
from app.services.data_integrity_audit import build_data_integrity_snapshot
from app.services.google_sheets import validate_sheets_env
from app.services.runtime_settings_store import get_outbound_enabled

router = APIRouter(
    prefix="/admin",
    tags=["reliability_admin"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/reliability")
def admin_reliability(db: Session = Depends(get_db)):
    """Unified reliability, queues, SLO proxy, anomaly hints, and workflow trace docs."""
    return build_reliability_payload(db)


@router.get("/data-integrity")
def admin_data_integrity(include_demo: bool = False, db: Session = Depends(get_db)):
    """
    Cross-check a small set of aggregates operators compare across Dashboard, Campaigns, and Replies.

    Read-only; intended for pilot go-live verification (requires the same auth as other /admin routes).
    """
    return build_data_integrity_snapshot(db, include_demo=include_demo)


@router.get("/pilot-readiness")
def admin_pilot_readiness(include_demo: bool = False, sheets_check: bool = False, db: Session = Depends(get_db)):
    """
    Read-only checklist/diagnostics for pilot go-live.

    - sheets_check=false by default (avoids network calls on every use)
    """
    checks: list[dict] = []

    # 1) Outbound kill switch must be readable; recommend starting disabled.
    try:
        enabled = bool(get_outbound_enabled(db))
        checks.append({"name": "outbound_enabled_readable", "status": "green", "value": enabled})
        if enabled:
            checks.append({"name": "outbound_should_start_disabled", "status": "yellow", "note": "recommended false until validated"})
    except Exception as e:
        checks.append({"name": "outbound_enabled_readable", "status": "red", "error": str(e)[:200]})

    # 2) Sheets env validation (format-only; optional access check).
    try:
        snap = validate_sheets_env(require_access=bool(sheets_check))
        checks.append({"name": "google_sheets_env", "status": "green", "detail": snap})
    except Exception as e:
        checks.append({"name": "google_sheets_env", "status": "red", "error": str(e)[:240]})

    # 3) Data integrity snapshot (read-only)
    try:
        snap = build_data_integrity_snapshot(db, include_demo=include_demo)
        checks.append({"name": "data_integrity_snapshot", "status": "green" if snap.get("ok") else "yellow", "detail": snap})
    except Exception as e:
        checks.append({"name": "data_integrity_snapshot", "status": "yellow", "error": str(e)[:240]})

    # 4) Reliability snapshot (queue depth, stuck processing, scheduler metrics)
    try:
        checks.append({"name": "reliability", "status": "green", "detail": build_reliability_payload(db)})
    except Exception as e:
        checks.append({"name": "reliability", "status": "yellow", "error": str(e)[:240]})

    sev = {"green": 0, "yellow": 1, "red": 2}
    overall_n = max(sev.get(str(c.get("status")), 2) for c in checks) if checks else 2
    overall = "green" if overall_n == 0 else "yellow" if overall_n == 1 else "red"
    return {"ok": True, "overall": overall, "checks": checks}


@router.get("/metrics/prometheus")
def admin_metrics_prometheus():
    """
    Prometheus exposition format (in-process counters / latency gauges).

    Gated by METRICS_EXPORT_ENABLED=1 in addition to admin API key.
    """
    if os.getenv("METRICS_EXPORT_ENABLED", "").strip().lower() not in ("1", "true", "yes"):
        return Response(status_code=404, content="metrics export disabled (set METRICS_EXPORT_ENABLED=1)\n")
    body = prometheus_text()
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")
