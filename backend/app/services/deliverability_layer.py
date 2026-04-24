"""
Email deliverability and sender reputation safety layer (above scheduler / SMTP).

Conservative defaults: disabled unless DELIVERABILITY_LAYER=1.
When enabled, blocks only on strong signals (bounce flood, extreme content heuristics, global failure storm).
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.email_campaign import EmailCampaign
from app.models.student import Student

logger = logging.getLogger(__name__)


def deliverability_layer_enabled() -> bool:
    return os.getenv("DELIVERABILITY_LAYER", "").strip().lower() in ("1", "true", "yes")


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


def _student_domain(email: str) -> str:
    e = (email or "").strip().lower()
    if "@" in e:
        return e.rsplit("@", 1)[-1]
    return ""


def count_recent_bounces(db: Session, student_id, *, hours: int = 72) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = (
        db.query(func.count(EmailCampaign.id))
        .filter(
            EmailCampaign.student_id == student_id,
            EmailCampaign.sent_at.isnot(None),
            EmailCampaign.sent_at >= since.replace(tzinfo=None),
            or_(
                EmailCampaign.reply_status.in_(("BOUNCED", "BOUNCE")),
                func.lower(EmailCampaign.delivery_status) == "failed",
            ),
        )
        .scalar()
    )
    return int(q or 0)


def count_sends_today_utc(db: Session, student_id) -> int:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    q = (
        db.query(func.count(EmailCampaign.id))
        .filter(
            EmailCampaign.student_id == student_id,
            EmailCampaign.status == "sent",
            EmailCampaign.sent_at.isnot(None),
            EmailCampaign.sent_at >= start.replace(tzinfo=None),
        )
        .scalar()
    )
    return int(q or 0)


def reply_positive_ratio(db: Session, student_id, *, days: int = 14) -> float:
    """Share of sent campaigns in window that got a positive reply signal."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    sent = (
        db.query(func.count(EmailCampaign.id))
        .filter(
            EmailCampaign.student_id == student_id,
            EmailCampaign.status == "sent",
            EmailCampaign.sent_at.isnot(None),
            EmailCampaign.sent_at >= since.replace(tzinfo=None),
        )
        .scalar()
        or 0
    )
    if sent == 0:
        return 0.0
    pos = (
        db.query(func.count(EmailCampaign.id))
        .filter(
            EmailCampaign.student_id == student_id,
            EmailCampaign.status == "sent",
            EmailCampaign.replied.is_(True),
            EmailCampaign.reply_type.in_(("INTERESTED", "INTERVIEW")),
            EmailCampaign.sent_at >= since.replace(tzinfo=None),
        )
        .scalar()
        or 0
    )
    return round(float(pos) / float(sent), 4)


def compute_spam_risk_score(subject: str, body: str) -> dict[str, Any]:
    """
    Lightweight pre-send heuristic (not ML). Score 0 = clean, 100 = very risky.
    """
    s = f"{subject or ''}\n{body or ''}"
    score = 0
    reasons: list[str] = []
    if len(s) > 12000:
        score += 15
        reasons.append("very_long_body")
    caps = sum(1 for c in s if c.isupper())
    letters = max(1, sum(1 for c in s if c.isalpha()))
    caps_ratio = caps / letters
    if caps_ratio > 0.35:
        score += 20
        reasons.append("high_caps_ratio")
    excl = s.count("!")
    if excl > 6:
        score += 10
        reasons.append("many_exclamations")
    links = len(re.findall(r"https?://", s, flags=re.I))
    if links > 4:
        score += 15
        reasons.append("many_links")
    triggers = ("100% free", "click here", "act now", "winner", "viagra", "crypto", "guaranteed")
    low = s.lower()
    for t in triggers:
        if t in low:
            score += 25
            reasons.append(f"trigger:{t}")
            break
    score = min(100, score)
    tier = "low" if score < 35 else "medium" if score < 70 else "high"
    return {"spam_risk_score": score, "spam_risk_tier": tier, "spam_reasons": reasons}


def compute_sending_reputation_score(db: Session, student: Student) -> dict[str, Any]:
    """
    0–100 composite: starts at 100, penalized by bounces / health, boosted by reply-positive ratio.
    """
    base = 100
    health = (getattr(student, "email_health_status", None) or "healthy").lower()
    if health == "warning":
        base -= 15
    elif health == "flagged":
        base -= 60
    bounces = count_recent_bounces(db, student.id, hours=_int_env("DELIVERABILITY_BOUNCE_WINDOW_HOURS", 72))
    bounce_pen = min(40, bounces * 12)
    base -= bounce_pen
    pos = reply_positive_ratio(db, student.id, days=_int_env("DELIVERABILITY_REPLY_SIGNAL_DAYS", 14))
    base += int(pos * 25)
    score = max(0, min(100, base))
    return {
        "reputation_score": score,
        "bounce_events_window": bounces,
        "reply_positive_ratio": pos,
        "email_health_status": health,
    }


def suggested_rotation_domain() -> str | None:
    """
    Optional multi-domain outbound strategy (documented for Gmail API / workspace routing).
    Returns one domain from DELIVERABILITY_SENDER_DOMAINS for operator visibility only.
    """
    raw = (os.getenv("DELIVERABILITY_SENDER_DOMAINS") or "").strip()
    if not raw:
        return None
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    if not parts:
        return None
    idx = datetime.now(timezone.utc).hour % len(parts)
    return parts[idx]


def scheduler_should_pause_sends(db: Session) -> dict[str, Any]:
    """
    Global circuit breaker: if recent aggregate failure rate is catastrophic, pause automated sends.
    """
    if not deliverability_layer_enabled():
        return {"pause": False, "reason": None}
    window_h = _int_env("DELIVERABILITY_GLOBAL_PAUSE_WINDOW_HOURS", 2)
    min_attempts = _int_env("DELIVERABILITY_GLOBAL_PAUSE_MIN_ATTEMPTS", 15)
    fail_pct = _float_env("DELIVERABILITY_GLOBAL_PAUSE_FAILURE_PCT", 40.0)
    since = datetime.now(timezone.utc) - timedelta(hours=window_h)
    sent = (
        db.query(func.count(EmailCampaign.id))
        .filter(
            EmailCampaign.status == "sent",
            EmailCampaign.sent_at.isnot(None),
            EmailCampaign.sent_at >= since.replace(tzinfo=None),
        )
        .scalar()
        or 0
    )
    failed = (
        db.query(func.count(EmailCampaign.id))
        .filter(
            EmailCampaign.status == "failed",
            EmailCampaign.sent_at.isnot(None),
            EmailCampaign.sent_at >= since.replace(tzinfo=None),
        )
        .scalar()
        or 0
    )
    attempts = int(sent) + int(failed)
    if attempts < min_attempts:
        return {"pause": False, "reason": None, "attempts": attempts}
    rate = (float(failed) / float(attempts)) * 100.0
    if rate >= fail_pct:
        return {
            "pause": True,
            "reason": "global_failure_rate",
            "failure_rate_pct": round(rate, 2),
            "attempts": attempts,
            "window_hours": window_h,
        }
    return {"pause": False, "reason": None, "failure_rate_pct": round(rate, 2), "attempts": attempts}


def evaluate_deliverability_for_send(
    db: Session,
    student: Student,
    subject: str,
    body: str,
) -> dict[str, Any]:
    """
    Pre-SMTP gate. If allow=False, caller should cancel/fail the campaign without sending.
    """
    if not deliverability_layer_enabled():
        return {"allow": True, "skipped": True}

    reasons: list[str] = []
    rep = compute_sending_reputation_score(db, student)
    spam = compute_spam_risk_score(subject, body)

    bounce_n = count_recent_bounces(db, student.id, hours=_int_env("DELIVERABILITY_BOUNCE_WINDOW_HOURS", 72))
    bounce_max = _int_env("DELIVERABILITY_BOUNCE_SUPPRESS_THRESHOLD", 3)
    if bounce_n >= bounce_max:
        reasons.append(f"bounce_suppression:{bounce_n}>={bounce_max}")

    spam_block = _int_env("DELIVERABILITY_SPAM_BLOCK_SCORE", 85)
    if int(spam["spam_risk_score"]) >= spam_block:
        reasons.append(f"spam_risk:{spam['spam_risk_score']}>={spam_block}")

    rep_min = _int_env("DELIVERABILITY_MIN_REPUTATION_SCORE", 25)
    if int(rep["reputation_score"]) < rep_min:
        reasons.append(f"low_reputation:{rep['reputation_score']}<{rep_min}")

    warmup_cap = _int_env("DELIVERABILITY_WARMUP_MAX_SENDS_PER_DAY", 40)
    if count_sends_today_utc(db, student.id) >= warmup_cap:
        reasons.append(f"warmup_daily_cap:{warmup_cap}")

    min_gap = _int_env("DELIVERABILITY_MIN_SECONDS_BETWEEN_SENDS", 0)
    if min_gap > 0 and student.last_sent_at:
        ls = student.last_sent_at
        if getattr(ls, "tzinfo", None) is None:
            ls = ls.replace(tzinfo=timezone.utc)
        delta = (datetime.now(timezone.utc) - ls).total_seconds()
        if delta < min_gap:
            reasons.append(f"send_throttle:{int(delta)}s<{min_gap}s")

    # Domain warmup phase: tighten cap for fresh addresses (student row age).
    if student.created_at:
        created = student.created_at
        if getattr(created, "tzinfo", None) is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - created).days
        warm_days = _int_env("DELIVERABILITY_WARMUP_STUDENT_DAYS", 14)
        if age_days < warm_days:
            tight_cap = _int_env("DELIVERABILITY_WARMUP_FRESH_STUDENT_DAY_CAP", 12)
            if count_sends_today_utc(db, student.id) >= tight_cap:
                reasons.append(f"fresh_student_warmup_cap:{tight_cap}d<{warm_days}")

    allow = len(reasons) == 0
    if not allow:
        logger.warning(
            "deliverability_block student_id=%s domain=%s reasons=%s",
            student.id,
            _student_domain(student.gmail_address or ""),
            reasons,
        )
    return {
        "allow": allow,
        "block_reasons": reasons,
        "reputation": rep,
        "spam": spam,
        "suggested_rotation_domain": suggested_rotation_domain(),
        "student_domain": _student_domain(student.gmail_address or ""),
    }


def build_deliverability_health_summary(db: Session) -> dict[str, Any]:
    """Aggregate metrics for admin dashboard (read-only)."""
    since24 = datetime.now(timezone.utc) - timedelta(hours=24)
    sent_24 = (
        db.query(func.count(EmailCampaign.id))
        .filter(
            EmailCampaign.status == "sent",
            EmailCampaign.sent_at.isnot(None),
            EmailCampaign.sent_at >= since24.replace(tzinfo=None),
        )
        .scalar()
        or 0
    )
    failed_24 = (
        db.query(func.count(EmailCampaign.id))
        .filter(
            EmailCampaign.status == "failed",
            EmailCampaign.sent_at.isnot(None),
            EmailCampaign.sent_at >= since24.replace(tzinfo=None),
        )
        .scalar()
        or 0
    )
    paused = scheduler_should_pause_sends(db)
    return {
        "layer_enabled": deliverability_layer_enabled(),
        "last_24h_sent": int(sent_24),
        "last_24h_failed": int(failed_24),
        "global_pause_recommendation": paused,
        "inbox_heuristics_note": "spam_risk_score is lexical/structural only; pair with provider postmaster + Gmail Postmaster Tools.",
    }
