"""Admin SRE / observability endpoints (read-only + Prometheus text)."""

import os

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.services.observability_metrics import prometheus_text
from app.services.sre_reliability import build_reliability_payload

router = APIRouter(
    prefix="/admin",
    tags=["reliability_admin"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/reliability")
def admin_reliability(db: Session = Depends(get_db)):
    """Unified reliability, queues, SLO proxy, anomaly hints, and workflow trace docs."""
    return build_reliability_payload(db)


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
