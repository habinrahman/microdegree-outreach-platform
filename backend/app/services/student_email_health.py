"""Rolling 24h Gmail / send reputation signals per student (email_health_status)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.email_campaign import EmailCampaign
from app.models.student import Student

logger = logging.getLogger(__name__)

ROLLING_HOURS = 24


def _window_start_utc() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=ROLLING_HOURS)


def compute_student_send_health_metrics(db: Session, student_id) -> dict:
    """Counts email_campaign rows for this student in the last 24h (by sent_at)."""
    since = _window_start_utc()

    total_sent = (
        db.query(func.count(EmailCampaign.id))
        .filter(
            EmailCampaign.student_id == student_id,
            EmailCampaign.status == "sent",
            EmailCampaign.sent_at.isnot(None),
            EmailCampaign.sent_at >= since,
        )
        .scalar()
        or 0
    )
    failed = (
        db.query(func.count(EmailCampaign.id))
        .filter(
            EmailCampaign.student_id == student_id,
            EmailCampaign.status == "failed",
            EmailCampaign.sent_at.isnot(None),
            EmailCampaign.sent_at >= since,
        )
        .scalar()
        or 0
    )
    blocked = (
        db.query(func.count(EmailCampaign.id))
        .filter(
            EmailCampaign.student_id == student_id,
            EmailCampaign.reply_status == "BLOCKED",
            EmailCampaign.sent_at.isnot(None),
            EmailCampaign.sent_at >= since,
        )
        .scalar()
        or 0
    )

    attempts = int(total_sent) + int(failed)
    failure_rate = round((float(failed) / float(attempts)) * 100.0, 2) if attempts > 0 else 0.0

    return {
        "total_sent_last_24h": int(total_sent),
        "failed_last_24h": int(failed),
        "blocked_last_24h": int(blocked),
        "failure_rate": failure_rate,
    }


def classify_email_health_status(blocked_last_24h: int, failure_rate: float) -> str:
    if blocked_last_24h > 5 or failure_rate > 50:
        return "flagged"
    if blocked_last_24h > 2 or failure_rate > 30:
        return "warning"
    return "healthy"


def refresh_student_email_health(db: Session, student_id) -> dict:
    """Recompute metrics, persist Student.email_health_status, commit."""
    m = compute_student_send_health_metrics(db, student_id)
    status = classify_email_health_status(m["blocked_last_24h"], m["failure_rate"])
    st = db.query(Student).filter(Student.id == student_id).first()
    if not st:
        return {**m, "health_status": status}
    prev = getattr(st, "email_health_status", None) or "healthy"
    st.email_health_status = status
    db.add(st)
    db.commit()
    if status == "flagged" and prev != "flagged":
        logger.warning(
            "student_email_health_flagged student_id=%s failure_rate=%s blocked_24h=%s",
            student_id,
            m["failure_rate"],
            m["blocked_last_24h"],
        )
    return {**m, "health_status": status}


def refresh_all_students_email_health(db: Session) -> int:
    n = 0
    for (sid,) in db.query(Student.id).all():
        refresh_student_email_health(db, sid)
        n += 1
    return n


def is_student_email_sending_blocked(student: Student | None) -> bool:
    return student is not None and getattr(student, "email_health_status", None) == "flagged"
