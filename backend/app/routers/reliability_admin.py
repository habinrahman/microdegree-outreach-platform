"""Admin SRE / observability endpoints (read-only + Prometheus text)."""

import os

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.services.observability_metrics import prometheus_text
from app.services.sre_reliability import build_reliability_payload
from app.services.data_integrity_audit import build_data_integrity_snapshot

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
