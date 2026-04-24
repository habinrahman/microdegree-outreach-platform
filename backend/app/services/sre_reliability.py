"""
SRE snapshot: queue depth, scheduler lag, anomaly hints, SLO posture (rolling windows).

Read-only DB queries + in-process metrics. No external TSDB required.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.email_campaign import EmailCampaign
from app.models.student import Student
from app.services.observability_metrics import snapshot as metrics_snapshot
from app.services.sheet_sync import sheet_sync_status


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip() or default)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip() or default)
    except ValueError:
        return default


def queue_depth_metrics(db: Session) -> dict[str, int]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    scheduled_due = (
        db.query(func.count(EmailCampaign.id))
        .filter(
            EmailCampaign.status == "scheduled",
            EmailCampaign.scheduled_at <= now,
            EmailCampaign.replied.is_(False),
        )
        .scalar()
        or 0
    )
    pending = (
        db.query(func.count(EmailCampaign.id))
        .filter(EmailCampaign.status.in_(("pending", "scheduled")))
        .scalar()
        or 0
    )
    processing = (
        db.query(func.count(EmailCampaign.id)).filter(EmailCampaign.status == "processing").scalar() or 0
    )
    followup_backlog = (
        db.query(func.count(EmailCampaign.id))
        .filter(
            EmailCampaign.status.in_(("pending", "scheduled")),
            func.lower(EmailCampaign.email_type).like("followup%"),
        )
        .scalar()
        or 0
    )
    return {
        "scheduled_due_now": int(scheduled_due),
        "pending_plus_scheduled": int(pending),
        "processing": int(processing),
        "followup_pending_scheduled": int(followup_backlog),
    }


def smtp_rollups_24h(db: Session) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    since_naive = since.replace(tzinfo=None)
    sent = (
        db.query(func.count(EmailCampaign.id))
        .filter(EmailCampaign.status == "sent", EmailCampaign.sent_at.isnot(None), EmailCampaign.sent_at >= since_naive)
        .scalar()
        or 0
    )
    failed = (
        db.query(func.count(EmailCampaign.id))
        .filter(
            EmailCampaign.status == "failed", EmailCampaign.sent_at.isnot(None), EmailCampaign.sent_at >= since_naive
        )
        .scalar()
        or 0
    )
    attempts = int(sent) + int(failed)
    rate = round((float(sent) / float(attempts)) * 100.0, 2) if attempts else None
    return {"sent_24h": int(sent), "failed_24h": int(failed), "success_rate_pct_24h": rate}


def bounce_spike_metrics(db: Session) -> dict[str, Any]:
    h1 = datetime.now(timezone.utc) - timedelta(hours=1)
    h24 = datetime.now(timezone.utc) - timedelta(hours=24)
    def _bounced_since(since: datetime) -> int:
        sn = since.replace(tzinfo=None)
        return (
            db.query(func.count(EmailCampaign.id))
            .filter(
                EmailCampaign.sent_at.isnot(None),
                EmailCampaign.sent_at >= sn,
                EmailCampaign.reply_status.in_(("BOUNCED", "BOUNCE")),
            )
            .scalar()
            or 0
        )

    c1 = _bounced_since(h1)
    c24 = _bounced_since(h24)
    return {"bounced_last_1h": int(c1), "bounced_last_24h": int(c24)}


def reply_funnel_metrics(db: Session) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    sn = since.replace(tzinfo=None)
    sent = (
        db.query(func.count(EmailCampaign.id))
        .filter(EmailCampaign.status == "sent", EmailCampaign.sent_at.isnot(None), EmailCampaign.sent_at >= sn)
        .scalar()
        or 0
    )
    replied = (
        db.query(func.count(EmailCampaign.id))
        .filter(
            EmailCampaign.status == "sent",
            EmailCampaign.replied.is_(True),
            EmailCampaign.sent_at.isnot(None),
            EmailCampaign.sent_at >= sn,
        )
        .scalar()
        or 0
    )
    ratio = round(float(replied) / float(sent), 4) if sent else None
    return {"sent_24h": int(sent), "replied_24h": int(replied), "reply_rate_24h": ratio}


def per_student_send_health(db: Session) -> dict[str, int]:
    rows = (
        db.query(Student.email_health_status, func.count(Student.id))
        .group_by(Student.email_health_status)
        .all()
    )
    out: dict[str, int] = {}
    for status, n in rows:
        key = (status or "unknown").lower()
        out[key] = int(n)
    return out


def sequence_engine_metrics(db: Session) -> dict[str, Any]:
    """Autonomous Sequencer v1 — queue depth, overdue flags, lifecycle counts (initial rows)."""
    from app.services.sequence_state_service import ALL_SEQUENCE_STATES

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    due_now = (
        db.query(func.count(EmailCampaign.id))
        .filter(
            EmailCampaign.status == "scheduled",
            EmailCampaign.scheduled_at <= now_naive,
            EmailCampaign.replied.is_(False),
        )
        .scalar()
        or 0
    )
    overdue_late = (
        db.query(func.count(EmailCampaign.id))
        .filter(EmailCampaign.status == "scheduled", EmailCampaign.overdue_late.is_(True))
        .scalar()
        or 0
    )
    pairs = (
        db.query(EmailCampaign.sequence_state, func.count(EmailCampaign.id))
        .filter(EmailCampaign.sequence_number == 1)
        .group_by(EmailCampaign.sequence_state)
        .all()
    )
    state_counts: dict[str, int] = {k: 0 for k in sorted(ALL_SEQUENCE_STATES)}
    state_counts["UNSET_OR_ACTIVE"] = 0
    for st, n in pairs:
        c = int(n or 0)
        if st is None or not str(st).strip():
            state_counts["UNSET_OR_ACTIVE"] += c
        elif str(st) in ALL_SEQUENCE_STATES:
            state_counts[str(st)] = c
        else:
            state_counts["_other"] = state_counts.get("_other", 0) + c
    stuck_paused = (
        db.query(func.count(EmailCampaign.id))
        .filter(EmailCampaign.sequence_number == 1, EmailCampaign.sequence_state == "PAUSED_UNKNOWN")
        .scalar()
        or 0
    )
    return {
        "due_queue_depth_scheduled": int(due_now),
        "overdue_late_count": int(overdue_late),
        "sequence_state_on_initial": state_counts,
        "stuck_sequences_paused_unknown_initial": int(stuck_paused),
    }


def stuck_processing_metrics(db: Session, *, stale_minutes: int = 10) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
    cn = cutoff.replace(tzinfo=None)
    n = (
        db.query(func.count(EmailCampaign.id))
        .filter(
            EmailCampaign.status == "processing",
            EmailCampaign.processing_started_at.isnot(None),
            EmailCampaign.processing_started_at < cn,
        )
        .scalar()
        or 0
    )
    return {"stuck_processing_over_minutes": stale_minutes, "count": int(n)}


def build_anomaly_alerts(
    db: Session,
    sched: dict[str, Any],
    q: dict[str, Any],
    bounce: dict[str, Any],
    reply: dict[str, Any],
    smtp: dict[str, Any],
    *,
    seq_engine: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    bounce_1h = int(bounce.get("bounced_last_1h") or 0)
    if bounce_1h >= _int_env("SRE_ALERT_BOUNCE_1H_THRESHOLD", 8):
        alerts.append(
            {
                "severity": "warning",
                "code": "bounce_spike_1h",
                "message": f"Bounces in last hour ({bounce_1h}) >= threshold",
            }
        )

    rr = reply.get("reply_rate_24h")
    if rr is not None and rr < _float_env("SRE_ALERT_REPLY_RATE_MIN", 0.01) and int(reply.get("sent_24h") or 0) >= 20:
        alerts.append(
            {
                "severity": "warning",
                "code": "reply_rate_collapse",
                "message": f"Reply rate 24h very low ({rr}) with material volume",
            }
        )

    jobs = (sched.get("jobs") or {}) if isinstance(sched, dict) else {}
    campaign_job = jobs.get("campaign_send") or {}
    last_ok = campaign_job.get("last_ok")
    if last_ok is False:
        alerts.append({"severity": "warning", "code": "scheduler_last_job_failed", "message": "Last campaign_send job failed"})

    last_fin = campaign_job.get("last_finished_at_utc")
    if last_fin:
        try:
            t = datetime.fromisoformat(str(last_fin).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - t.astimezone(timezone.utc)).total_seconds()
            if age > _int_env("SRE_ALERT_SCHEDULER_STALL_SECONDS", 600):
                alerts.append(
                    {
                        "severity": "critical",
                        "code": "scheduler_stalled",
                        "message": f"No successful campaign_send finish for {int(age)}s",
                    }
                )
        except Exception:
            pass

    if int(q.get("followup_pending_scheduled") or 0) >= _int_env("SRE_ALERT_FOLLOWUP_BACKLOG", 500):
        alerts.append(
            {
                "severity": "warning",
                "code": "followup_backlog_growth",
                "message": "Large follow-up pending+scheduled backlog",
            }
        )

    due = int(q.get("scheduled_due_now") or 0)
    sent24 = int(smtp.get("sent_24h") or 0)
    if due > 100 and sent24 < 5:
        alerts.append(
            {
                "severity": "info",
                "code": "queue_starvation_suspected",
                "message": "Many due campaigns but very few sends in 24h (check window, pauses, credentials)",
            }
        )

    stuck = stuck_processing_metrics(db)
    if int(stuck.get("count") or 0) > 0:
        alerts.append(
            {
                "severity": "warning",
                "code": "stuck_processing_jobs",
                "message": f"{stuck['count']} campaigns stuck in processing beyond {stuck['stuck_processing_over_minutes']}m",
            }
        )

    if seq_engine and "error" not in seq_engine:
        ol = int(seq_engine.get("overdue_late_count") or 0)
        if ol >= _int_env("SRE_ALERT_SEQUENCER_OVERDUE_LATE", 50):
            alerts.append(
                {
                    "severity": "warning",
                    "code": "sequencer_overdue_late_backlog",
                    "message": f"{ol} scheduled rows flagged overdue_late (SEQUENCE_OVERDUE_LAG_MINUTES threshold)",
                }
            )
        sp = int(seq_engine.get("stuck_sequences_paused_unknown_initial") or 0)
        if sp > 0:
            alerts.append(
                {
                    "severity": "info",
                    "code": "sequencer_paused_unknown_pairs",
                    "message": f"{sp} initial rows in PAUSED_UNKNOWN (stale processing recovery)",
                }
            )

    return alerts


def slo_error_budget_panel(db: Session, smtp: dict[str, Any]) -> dict[str, Any]:
    """
    Minimal error-budget view using rolling 24h success as proxy (not calendar-month SLO).
    """
    target = _float_env("SLO_SEND_SUCCESS_TARGET", 0.995)
    rate_pct = smtp.get("success_rate_pct_24h")
    if rate_pct is None:
        consumed = None
        remaining = None
    else:
        actual = float(rate_pct) / 100.0
        remaining = max(0.0, round(target - (1.0 - actual), 6)) if actual < 1.0 else 0.0
        consumed = round(max(0.0, (1.0 - actual) - (1.0 - target)), 6) if actual < target else 0.0
    return {
        "target_monthly_send_success": target,
        "rolling_24h_success_rate_pct": rate_pct,
        "error_budget_consumed_proxy": consumed,
        "error_budget_remaining_proxy": remaining,
        "note": "Monthly SLO needs a persistent TSDB; this panel uses 24h rollup as operational proxy.",
    }


def workflow_trace_template() -> dict[str, Any]:
    """Operator documentation for correlating a single HR–student thread."""
    return {
        "stages": [
            "assignments: active student_id + hr_id",
            "email_campaigns: sequence_number, email_type, status transitions",
            "send: worker / SMTP → sent_at, message_id",
            "follow-up: followup eligibility + follow-up templates",
            "reply: reply_tracker / IMAP → replied, reply_type",
            "stop: replied, cancelled, expired, or HR paused",
        ],
        "correlation": "Propagate X-Correlation-ID on HTTP; include in logs [cid=…]. For batch jobs set context in worker entry if needed.",
    }


def dlq_and_retry_notes() -> dict[str, Any]:
    return {
        "dead_letter_queue": "Use EmailCampaign.status=failed + error/failure_type as DLQ; investigate before hard delete.",
        "retry_policy": "Scheduler does not auto-retry unknown-outcome processing rows (paused stale). Failed initial may be reset upstream.",
        "circuit_breakers": "deliverability_layer global pause; student email_health_status=flagged blocks sends.",
        "watchdog": "Use GET /admin/reliability + /health/scheduler/metrics; alert on scheduler_stalled and stuck_processing_jobs.",
        "self_heal": "Stale processing → paused (scheduler). Sheet sync stuck detector in GET /health/sheet-sync/status.",
    }


def build_reliability_payload(db: Session) -> dict[str, Any]:
    from app.services.campaign_scheduler import scheduler_metrics_snapshot
    from app.services.schema_launch_gate import audit_critical_schema

    sched = scheduler_metrics_snapshot()
    q = queue_depth_metrics(db)
    smtp = smtp_rollups_24h(db)
    bounce = bounce_spike_metrics(db)
    reply = reply_funnel_metrics(db)
    students_h = per_student_send_health(db)
    stuck = stuck_processing_metrics(db)
    try:
        seq_engine = sequence_engine_metrics(db)
    except Exception as e:
        seq_engine = {"error": str(e)[:240]}
    alerts = build_anomaly_alerts(db, sched, q, bounce, reply, smtp, seq_engine=seq_engine)
    try:
        sheet = sheet_sync_status(db)
    except Exception as e:
        sheet = {"error": str(e)[:200]}

    return {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "schema_launch_gate": audit_critical_schema(db),
        "sequence_engine": seq_engine,
        "metrics": metrics_snapshot(),
        "scheduler": sched,
        "queues": q,
        "smtp_rollups_24h": smtp,
        "bounce": bounce,
        "reply_funnel_24h": reply,
        "per_student_email_health_counts": students_h,
        "stuck_processing": stuck,
        "sheet_sync": sheet,
        "alerts": alerts,
        "slo_panel": slo_error_budget_panel(db, smtp),
        "workflow_trace": workflow_trace_template(),
        "reliability_notes": dlq_and_retry_notes(),
        "suggested_commands": {
            "prometheus": "GET /admin/metrics/prometheus (Authorization: X-API-Key)",
            "scheduler_metrics": "GET /health/scheduler/metrics",
            "sheet_health": "GET /health/sheet-sync/status",
            "schema_launch_gate": "GET /health/schema-launch-gate",
            "followups_dispatch_checksum": "GET /followups/settings/checksum",
        },
    }
