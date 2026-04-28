"""Admin endpoints for outbound safety controls (kill switch + suppression list)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.services.runtime_settings_store import get_outbound_enabled, set_outbound_enabled
from app.services.outbound_suppression_store import upsert_suppression
from app.models.outbound_suppression import OutboundSuppression
from app.services.deliverability_layer import scheduler_should_pause_sends
from app.services.campaign_scheduler import scheduler_metrics_snapshot
from app.services.sre_reliability import queue_depth_metrics, stuck_processing_metrics


router = APIRouter(
    prefix="/admin/outbound",
    tags=["outbound_admin"],
    dependencies=[Depends(require_api_key)],
)


class OutboundToggleUpdate(BaseModel):
    enabled: bool
    reason: str | None = Field(default=None, max_length=4000)


class SuppressionUpsert(BaseModel):
    email: str
    reason: str | None = Field(default=None, max_length=4000)
    source: str | None = Field(default="manual", max_length=256)
    active: bool = True
    suppressed_until: datetime | None = None


def _status_rollup(checks: list[dict]) -> str:
    sev = {"green": 0, "yellow": 1, "red": 2}
    mx = 0
    for c in checks:
        mx = max(mx, sev.get(str(c.get("status")), 2))
    return "green" if mx == 0 else "yellow" if mx == 1 else "red"


@router.get("/preflight")
def outbound_preflight(db: Session = Depends(get_db)):
    """
    Lightweight operational preflight for pilot go-live.

    Read-only, best-effort checks with a green/yellow/red rollup.
    """
    now = datetime.now(timezone.utc)
    checks: list[dict] = []

    # 1) outbound_enabled reachable/readable
    try:
        val = bool(get_outbound_enabled(db))
        checks.append({"name": "outbound_enabled_readable", "status": "green", "value": val})
        if not val:
            checks.append({"name": "outbound_enabled_is_false", "status": "yellow", "note": "sending is disabled"})
    except Exception as e:
        checks.append({"name": "outbound_enabled_readable", "status": "red", "error": str(e)[:200]})

    # 2) suppression table exists
    try:
        bind = db.get_bind()
        has = bool(inspect(bind).has_table("outbound_suppressions"))
        if has:
            checks.append({"name": "suppression_table_exists", "status": "green"})
        else:
            checks.append(
                {
                    "name": "suppression_table_exists",
                    "status": "yellow",
                    "note": "missing table; code can bootstrap on-demand but apply migration before pilot",
                }
            )
    except Exception as e:
        checks.append({"name": "suppression_table_exists", "status": "red", "error": str(e)[:200]})

    # 3) advisory lock support
    try:
        bind = db.get_bind()
        dialect = getattr(getattr(bind, "dialect", None), "name", "") if bind is not None else ""
        if dialect != "postgresql":
            checks.append({"name": "advisory_lock_supported", "status": "yellow", "note": f"dialect={dialect}"})
        else:
            ok = bool(db.execute(text("select pg_try_advisory_lock(123456, 654321)")).scalar())
            # Always try to unlock; ignore result.
            try:
                db.execute(text("select pg_advisory_unlock(123456, 654321)"))
            except Exception:
                pass
            checks.append({"name": "advisory_lock_supported", "status": "green" if ok else "red", "value": ok})
    except Exception as e:
        checks.append({"name": "advisory_lock_supported", "status": "red", "error": str(e)[:200]})

    # 4) scheduler preconditions healthy (read-only signals)
    try:
        paused = scheduler_should_pause_sends(db)
        if paused.get("pause"):
            checks.append({"name": "deliverability_global_pause", "status": "yellow", "detail": paused})
        else:
            checks.append({"name": "deliverability_global_pause", "status": "green", "detail": paused})
    except Exception as e:
        checks.append({"name": "deliverability_global_pause", "status": "yellow", "error": str(e)[:200]})

    try:
        q = queue_depth_metrics(db)
        stuck = stuck_processing_metrics(db)
        checks.append({"name": "queue_depth", "status": "green", "detail": q})
        if int(stuck.get("count") or 0) > 0:
            checks.append({"name": "stuck_processing", "status": "yellow", "detail": stuck})
        else:
            checks.append({"name": "stuck_processing", "status": "green", "detail": stuck})
    except Exception as e:
        checks.append({"name": "scheduler_db_rollups", "status": "yellow", "error": str(e)[:200]})

    # 5) key migrations present / revision visible
    try:
        rev = db.execute(text("select version_num from alembic_version")).scalar_one_or_none()
        expected_min = "20260428_0020_outbound_safety_controls"
        status = "green" if str(rev) == expected_min else "yellow"
        checks.append(
            {
                "name": "alembic_revision",
                "status": status,
                "db_revision": rev,
                "expected_min_for_outbound_safety": expected_min,
                "note": "yellow indicates DB revision behind repo head; apply migrations before pilot",
            }
        )
    except Exception as e:
        checks.append({"name": "alembic_revision", "status": "red", "error": str(e)[:200]})

    # 6) scheduler metrics visible (in-process)
    try:
        m = scheduler_metrics_snapshot()
        checks.append({"name": "scheduler_metrics_visible", "status": "green", "detail": m})
    except Exception as e:
        checks.append({"name": "scheduler_metrics_visible", "status": "yellow", "error": str(e)[:200]})

    overall = _status_rollup(checks)
    return {
        "ok": True,
        "checked_at_utc": now.isoformat(),
        "overall": overall,
        "checks": checks,
    }


@router.get("/status")
def get_outbound_status(db: Session = Depends(get_db)):
    return {"outbound_enabled": bool(get_outbound_enabled(db))}


@router.put("/status")
def put_outbound_status(request: Request, body: OutboundToggleUpdate, db: Session = Depends(get_db)):
    try:
        set_outbound_enabled(db, bool(body.enabled))
    except Exception:
        raise HTTPException(status_code=503, detail="runtime_settings_unavailable")
    return {"ok": True, "outbound_enabled": bool(body.enabled)}


@router.get("/suppressions")
def list_suppressions(
    active_only: bool = True,
    q: str | None = Query(default=None, description="Prefix filter on email_lower"),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    qry = db.query(OutboundSuppression)
    if active_only:
        qry = qry.filter(OutboundSuppression.is_active.is_(True))
    if q:
        qry = qry.filter(OutboundSuppression.email_lower.like(q.strip().lower() + "%"))
    rows = qry.order_by(OutboundSuppression.updated_at.desc(), OutboundSuppression.created_at.desc()).limit(limit).all()
    return [
        {
            "id": str(r.id),
            "email": r.email,
            "email_lower": r.email_lower,
            "reason": r.reason,
            "source": r.source,
            "is_active": bool(r.is_active),
            "suppressed_until": r.suppressed_until,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        for r in rows
    ]


@router.put("/suppressions")
def put_suppression(body: SuppressionUpsert, db: Session = Depends(get_db)):
    try:
        row = upsert_suppression(
            db,
            email=body.email,
            reason=body.reason,
            source=body.source,
            active=bool(body.active),
            suppressed_until=body.suppressed_until,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "id": str(row.id), "email_lower": row.email_lower}

