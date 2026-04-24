"""
Read-only priority outreach queue (Phase 1).

Ranks active student–HR assignment pairs for operator sequencing. Does not send mail
or replace the campaign scheduler. See docs/PRIORITY_QUEUE.md for model notes.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import and_, or_, tuple_
from sqlalchemy.orm import Session

from app.models import Assignment, BlockedHR, EmailCampaign, HRContact, Student
from app.services.followup_eligibility import compute_followup_eligibility_for_pair
from app.services.hr_health_scoring import compute_health_for_hr_ids, email_domain, tier_rank
from app.services.priority_queue_diversity import apply_diversity_layer

# --- Tunable weights (sum normalized to 1.0 at runtime) -----------------------
def _f(name: str, default: str) -> float:
    try:
        return float((os.getenv(name) or default).strip())
    except ValueError:
        return float(default)


W_FOLLOWUP = _f("PRIORITY_W_FOLLOWUP", "0.30")
W_HR_OPP = _f("PRIORITY_W_HR_OPP", "0.25")
W_HR_HEALTH = _f("PRIORITY_W_HR_HEALTH", "0.20")
W_STUDENT = _f("PRIORITY_W_STUDENT", "0.15")
W_WARM = _f("PRIORITY_W_WARM", "0.10")

# Over-contact: sends in rolling window (same pair)
OVER_CONTACT_WINDOW_DAYS = int((os.getenv("PRIORITY_OVER_CONTACT_DAYS") or "7").strip() or "7")
OVER_CONTACT_SOFT = int((os.getenv("PRIORITY_OVER_CONTACT_SOFT") or "2").strip() or "2")
OVER_CONTACT_HARD = int((os.getenv("PRIORITY_OVER_CONTACT_HARD") or "4").strip() or "4")

# Safety cap: max active assignments scanned per request (ordering within cap only).
_MAX_ASSIGN_SCAN = max(50, min(50_000, int((os.getenv("PRIORITY_QUEUE_MAX_ASSIGNMENTS_SCAN") or "4000").strip() or "4000")))


# Sort key: lower = earlier in queue. Follow-up due before due scheduled sends (warm thread
# continuity over cold scheduled outreach); see tests/test_priority_queue_followup_invariants.py.
BUCKET_ORDER = {
    "FOLLOW_UP_DUE": 0,
    "SEND_NOW": 1,
    "WARM_LEAD_PRIORITY": 2,
    "WAIT_FOR_COOLDOWN": 3,
    "LOW_PRIORITY": 4,
    "SUPPRESS": 5,
}


def _normalize_weights() -> tuple[float, float, float, float, float]:
    s = W_FOLLOWUP + W_HR_OPP + W_HR_HEALTH + W_STUDENT + W_WARM
    if s <= 0:
        return 0.30, 0.25, 0.20, 0.15, 0.10
    return (
        W_FOLLOWUP / s,
        W_HR_OPP / s,
        W_HR_HEALTH / s,
        W_STUDENT / s,
        W_WARM / s,
    )


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_hr_paused_send(hr: HRContact, now_utc: datetime) -> bool:
    """Align with scheduler: status paused blocks sends while paused_until is future or unset."""
    if (hr.status or "").lower() != "paused":
        return False
    pu = _utc(getattr(hr, "paused_until", None))
    if pu is None:
        return True
    return pu > now_utc


def _student_gmail_auth_cooldown_ids(db: Session, student_ids: Iterable, now_utc: datetime) -> set:
    cutoff = now_utc - timedelta(minutes=10)
    sid_tuples = (
        db.query(EmailCampaign.student_id)
        .filter(
            EmailCampaign.student_id.in_(list({i for i in student_ids if i is not None})),
            EmailCampaign.status == "paused",
            EmailCampaign.error == "gmail_auth_block",
            EmailCampaign.sent_at.isnot(None),
            EmailCampaign.sent_at >= cutoff,
        )
        .distinct()
        .all()
    )
    return {row[0] for row in sid_tuples}


def _blocked_email_set(db: Session) -> set[str]:
    return {(e or "").strip().lower() for (e,) in db.query(BlockedHR.email).all() if (e or "").strip()}


def _pair_sent_count_since(db: Session, student_id, hr_id, since_utc: datetime) -> int:
    return (
        int(
            db.query(EmailCampaign)
            .filter(
                EmailCampaign.student_id == student_id,
                EmailCampaign.hr_id == hr_id,
                EmailCampaign.status == "sent",
                EmailCampaign.sent_at.isnot(None),
                EmailCampaign.sent_at >= since_utc.replace(tzinfo=None),
            )
            .count()
        )
        if since_utc
        else 0
    )


def _pair_has_warm_signal(campaigns: list[EmailCampaign]) -> bool:
    for c in campaigns:
        rt = (getattr(c, "reply_type", None) or "").strip().upper()
        rs = (getattr(c, "reply_status", None) or "").strip().upper()
        if rt in ("INTERESTED", "INTERVIEW") or rs in ("INTERESTED", "INTERVIEW"):
            return True
    return False


def _next_future_scheduled(campaigns: list[EmailCampaign], now_utc: datetime) -> datetime | None:
    """Earliest scheduled_at in the future for pending/scheduled rows (if any)."""
    best: datetime | None = None
    for c in campaigns:
        st = (getattr(c, "status", None) or "").lower()
        if st not in ("pending", "scheduled"):
            continue
        if bool(getattr(c, "replied", False)):
            continue
        sa = _utc(getattr(c, "scheduled_at", None))
        if sa is None or sa <= now_utc:
            continue
        if best is None or sa < best:
            best = sa
    return best


def _next_due_campaign(campaigns: list[EmailCampaign], now_utc: datetime) -> EmailCampaign | None:
    due: list[EmailCampaign] = []
    for c in campaigns:
        st = (getattr(c, "status", None) or "").lower()
        if st not in ("pending", "scheduled"):
            continue
        if bool(getattr(c, "replied", False)):
            continue
        sa = _utc(getattr(c, "scheduled_at", None))
        if sa is None:
            continue
        if sa <= now_utc:
            due.append(c)
    if not due:
        return None
    due.sort(key=lambda x: (int(x.sequence_number or 99), _utc(x.scheduled_at) or now_utc, str(x.id)))
    return due[0]


def _student_priority_score(student: Student) -> tuple[float, list[str]]:
    """0–100 composite; reasons for transparency."""
    reasons: list[str] = []
    score = 42.0
    if (student.status or "").lower() == "active":
        score += 22.0
        reasons.append("+ Active student")
    else:
        reasons.append("- Student not active")
    if not bool(getattr(student, "is_demo", False)):
        score += 10.0
        reasons.append("+ Non-demo profile (production outreach)")
    eh = (getattr(student, "email_health_status", None) or "healthy").lower()
    if eh == "healthy":
        score += 16.0
        reasons.append("+ Student send reputation healthy")
    elif eh == "warning":
        score += 7.0
        reasons.append("~ Student send reputation warning")
    else:
        reasons.append("- Student send reputation flagged")
    if (getattr(student, "gmail_connected", False)) or (
        (getattr(student, "gmail_refresh_token", None) or "").strip()
    ):
        score += 5.0
        reasons.append("+ Gmail connected (OAuth)")
    elif (getattr(student, "app_password", None) or "").strip():
        score += 3.0
        reasons.append("+ SMTP app password configured")
    else:
        reasons.append("- No Gmail OAuth or app password — cannot send")
    return max(0.0, min(100.0, score)), reasons


def _followup_urgency_component(fu, now_utc: datetime, campaigns: list[EmailCampaign]) -> tuple[float, list[str]]:
    """0–100 follow-up / outreach-readiness urgency (single dimension — not double-counted in HR scores)."""
    reasons: list[str] = []
    if fu.eligible_for_followup and fu.followup_status == "DUE_NOW":
        urgency = 100.0
        reasons.append("+ Follow-up due now")
        if fu.due_date_utc:
            try:
                due = datetime.fromisoformat(fu.due_date_utc.replace("Z", "+00:00"))
                overdue_days = max(0, (now_utc - due).days)
                if overdue_days > 0:
                    bonus = min(8.0, overdue_days * 1.5)
                    urgency = min(100.0, urgency + bonus)
                    reasons.append(f"+ Follow-up overdue by {overdue_days}d")
            except ValueError:
                pass
        return urgency, reasons

    if fu.followup_status == "WAITING" and fu.days_until_due is not None:
        d = int(fu.days_until_due)
        if d <= 3:
            u = 72.0 - d * 6.0
            reasons.append(f"+ Follow-up window approaching ({d}d)")
            return u, reasons
        if d <= 7:
            return 48.0, [f"~ Follow-up in {d}d"]

    # Fresh outreach: assignment exists but nothing sent yet
    if (fu.blocked_reason or "") == "Initial not sent" or (
        fu.current_step == 0 and not fu.eligible_for_followup and fu.followup_status == "WAITING"
    ):
        nc = _next_due_campaign(campaigns, now_utc)
        if nc is not None:
            reasons.append("+ Initial / next touch scheduled and due")
            return 78.0, reasons
        reasons.append("+ Fresh assignment — initial not sent")
        return 62.0, reasons

    if fu.send_in_progress:
        return 15.0, ["- Send in progress for this pair"]

    if fu.followup_status == "PAUSED":
        return 8.0, ["- Thread paused"]

    if fu.followup_status in ("REPLIED_STOPPED", "BOUNCED_STOPPED", "COMPLETED_STOPPED"):
        return 0.0, [f"- Sequence stopped ({fu.followup_status})"]

    return 22.0, ["~ No urgent follow-up signal"]


def _warm_lead_component(
    hr_opp: float,
    tier: str,
    campaigns: list[EmailCampaign],
    fu,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 35.0
    if _pair_has_warm_signal(campaigns):
        score += 40.0
        reasons.append("+ Interested / interview-class signal on thread")
    if tier_rank(tier) <= 2 and hr_opp >= 58.0:
        score += 18.0
        reasons.append("+ Historically responsive HR (opportunity score)")
    if fu.followup_status == "WAITING" and fu.days_until_due is not None and fu.days_until_due <= 2:
        score += 12.0
        reasons.append("+ Warm timing — follow-up almost due")
    return max(0.0, min(100.0, score)), reasons


def _cooldown_penalty_component(
    hr: HRContact,
    student: Student,
    student_cooldown: bool,
    hr_paused: bool,
    over_contact_n: int,
    next_scheduled: datetime | None,
    now_utc: datetime,
) -> tuple[float, list[str]]:
    """
    Returns a *penalty* 0–100 where higher = worse cooldown / risk (subtracted from blended score).
    """
    reasons: list[str] = []
    pen = 0.0
    if student_cooldown:
        pen += 35.0
        reasons.append("- Student recent Gmail auth cooldown")
    if (getattr(student, "email_health_status", "") or "").lower() == "warning":
        pen += 12.0
        reasons.append("- Slight student reputation risk")
    if hr_paused:
        pen += 45.0
        reasons.append("- HR paused / not hiring window")
    pu = _utc(getattr(hr, "paused_until", None))
    if pu and pu > now_utc and (hr.status or "").lower() != "paused":
        pen += 20.0
        reasons.append("- HR cooldown (paused_until) active")
    if next_scheduled and next_scheduled > now_utc:
        pen += 18.0
        reasons.append("- Next send scheduled in the future")
    if over_contact_n >= OVER_CONTACT_HARD:
        pen += 40.0
        reasons.append(f"- Over-contact risk ({over_contact_n} sends in {OVER_CONTACT_WINDOW_DAYS}d)")
    elif over_contact_n >= OVER_CONTACT_SOFT:
        pen += 15.0
        reasons.append(f"- Elevated send frequency ({over_contact_n} in {OVER_CONTACT_WINDOW_DAYS}d)")
    lc = _utc(getattr(hr, "last_contacted_at", None))
    if lc and (now_utc - lc).total_seconds() < 2 * 86400:
        pen += 10.0
        reasons.append("- HR contacted very recently")
    return min(100.0, pen), reasons


def _pair_last_activity_iso(pair_cs: list[EmailCampaign]) -> str | None:
    best: datetime | None = None
    for c in pair_cs:
        for raw in (getattr(c, "sent_at", None), getattr(c, "scheduled_at", None), getattr(c, "created_at", None)):
            dt = _utc(raw)
            if dt is None:
                continue
            if best is None or dt > best:
                best = dt
    return best.isoformat() if best else None


def _bucket_rationale(
    *,
    queue_bucket: str,
    suppress: bool,
    fu: Any,
    student_cd_fu_deferred: bool,
    has_next_due_scheduled: bool,
) -> str:
    if suppress:
        return (
            "SUPPRESS: one or more hard gates fired (inactive student, flagged email health, invalid HR, "
            "blocked list, tier D, or follow-up engine reports thread ended / operator pause)."
        )
    if queue_bucket == "FOLLOW_UP_DUE":
        return "FOLLOW_UP_DUE: follow-up engine marks this pair eligible with status DUE_NOW; interval from last sent touch has elapsed."
    if queue_bucket == "SEND_NOW" and has_next_due_scheduled:
        return "SEND_NOW: a pending/scheduled campaign for this pair is due (scheduled_at in the past) and no higher-priority gate applies."
    if student_cd_fu_deferred:
        return (
            "WAIT_FOR_COOLDOWN: follow-up is due by eligibility, but the student is in a short Gmail auth "
            "cooldown window so sends are deferred to match scheduler behavior."
        )
    if queue_bucket == "WAIT_FOR_COOLDOWN":
        return (
            "WAIT_FOR_COOLDOWN: HR pause, student cooldown, future scheduled send, follow-up interval not met, "
            "send in progress, or missing send credentials for a due scheduled row."
        )
    if queue_bucket == "WARM_LEAD_PRIORITY":
        return "WARM_LEAD_PRIORITY: strong HR or timing — approaching follow-up window or high opportunity with an active sequence."
    if queue_bucket == "LOW_PRIORITY":
        if (getattr(fu, "blocked_reason", None) or "") == "Initial not sent":
            return "LOW_PRIORITY: active assignment with no logged initial send yet — prepare first outreach."
        return "LOW_PRIORITY: no immediate due follow-up or due scheduled send; assignment may still be worth future outreach."
    return f"{queue_bucket}: see recommended_action and signal lines for detail."


def _build_decision_diagnostics(
    *,
    computed_at_iso: str,
    queue_bucket: str,
    suppress: bool,
    recommended_action: str,
    fu: Any,
    deduped_reasons: list[str],
    cd_reasons: list[str],
    cooldown_status_line: str | None,
    wf: float,
    wopp: float,
    whealth: float,
    wstu: float,
    wwarm: float,
    fu_urg: float,
    st_score: float,
    warm_score: float,
    health: float,
    opportunity: float,
    blended: float,
    cd_pen: float,
    priority: float,
    pair_cs: list[EmailCampaign],
    student_cd_fu_deferred: bool,
    has_next_due_scheduled: bool,
) -> dict[str, Any]:
    why_ranked = [x for x in deduped_reasons if x.startswith(("+", "~"))]
    why_suppressed = [x for x in deduped_reasons if x.startswith("-")] if suppress else []

    components = [
        {"name": "followup_urgency", "value": round(fu_urg, 3), "weight": round(wf, 4), "weighted": round(wf * fu_urg, 3)},
        {"name": "hr_opportunity", "value": round(opportunity, 3), "weight": round(wopp, 4), "weighted": round(wopp * opportunity, 3)},
        {"name": "hr_health", "value": round(health, 3), "weight": round(whealth, 4), "weighted": round(whealth * health, 3)},
        {"name": "student_priority", "value": round(st_score, 3), "weight": round(wstu, 4), "weighted": round(wstu * st_score, 3)},
        {"name": "warm_lead", "value": round(warm_score, 3), "weight": round(wwarm, 4), "weighted": round(wwarm * warm_score, 3)},
    ]
    top_components = sorted(components, key=lambda x: -x["weighted"])[:5]

    follow_up_diag = {
        "status": fu.followup_status,
        "eligible_for_followup": bool(fu.eligible_for_followup),
        "blocked_reason": fu.blocked_reason,
        "next_followup_step": fu.next_followup_step,
        "next_template_type": fu.next_template_type,
        "due_date_utc": fu.due_date_utc,
        "days_until_due": fu.days_until_due,
        "paused": bool(fu.paused),
        "send_in_progress": bool(fu.send_in_progress),
        "initial_or_anchor_campaign_id": str(fu.campaign_id) if fu.campaign_id else None,
    }

    why_not_sent: dict[str, Any] | None = None
    if suppress:
        why_not_sent = {
            "is_suppressed": True,
            "summary": "This pair is not eligible for outbound sends under current policy and thread state.",
            "blockers": why_suppressed,
            "all_signal_lines": deduped_reasons,
            "follow_up_snapshot": follow_up_diag,
            "operator_note": "Resolve blockers (e.g. HR validity, tier, reply/stop state, student health) or archive the assignment before expecting sends.",
        }

    deferred: list[str] = []
    if not suppress and queue_bucket == "WAIT_FOR_COOLDOWN":
        deferred = [x for x in deduped_reasons if x.startswith("-")]

    return {
        "decision_computed_at_utc": computed_at_iso,
        "last_pair_activity_utc": _pair_last_activity_iso(pair_cs),
        "queue_bucket": queue_bucket,
        "bucket_rationale": _bucket_rationale(
            queue_bucket=queue_bucket,
            suppress=suppress,
            fu=fu,
            student_cd_fu_deferred=student_cd_fu_deferred,
            has_next_due_scheduled=has_next_due_scheduled,
        ),
        "recommended_action": recommended_action,
        "why_ranked": why_ranked,
        "why_suppressed": why_suppressed,
        "follow_up": follow_up_diag,
        "cooldown": {
            "summary_line": cooldown_status_line,
            "penalty_reasons": list(cd_reasons),
            "cooldown_penalty_score": round(cd_pen, 2),
        },
        "scoring": {
            "priority_score": round(priority, 2),
            "blended_before_cooldown_subtraction": round(blended, 3),
            "cooldown_subtracted": round(0.35 * cd_pen, 3),
            "formula": "priority = clamp(blended - 0.35 * cooldown_penalty, 0, 100); blended = Σ(weight_i * axis_i)",
            "axes": components,
            "top_components": top_components,
        },
        "why_not_sent": why_not_sent,
        "waiting_or_deferred": (
            {
                "bucket_is_wait": queue_bucket == "WAIT_FOR_COOLDOWN",
                "negative_signals": deferred,
                "summary": "Not suppressed, but send is deferred by cooldown, schedule, interval, in-flight send, or credentials.",
            }
            if not suppress and queue_bucket == "WAIT_FOR_COOLDOWN"
            else None
        ),
    }


def _fingerprint_parts(
    *,
    bucket: str,
    fu_status: str | None,
    tier: str,
    scheduled_at: str | None,
    score_bucket: int,
    campaign_id: str | None,
) -> str:
    payload = "|".join(
        [
            bucket,
            fu_status or "",
            tier,
            scheduled_at or "",
            str(score_bucket),
            campaign_id or "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


@dataclass
class _RawRow:
    student: Student
    hr: HRContact
    priority_score: float
    recommendation_reason: list[str]
    recommended_action: str
    urgency_level: str
    queue_bucket: str
    hr_tier: str
    health_score: float
    opportunity_score: float
    dimension_scores: dict[str, float]
    next_best_touch: str | None
    cooldown_status: str | None
    followup_status: str | None
    campaign_id: UUID | None
    signal_fingerprint: str
    sort_tuple: tuple[Any, ...]
    ranking_slot_type: str | None = None  # EXPLORATION when diversified layer marks row
    decision_diagnostics: dict[str, Any] = field(default_factory=dict)


def compute_priority_queue(
    db: Session,
    *,
    now_utc: datetime | None = None,
    bucket: str | None = None,
    student_id: UUID | None = None,
    tier: str | None = None,
    only_due: bool = False,
    limit: int = 200,
    include_rows: bool = True,
    include_demo: bool = False,
    diversified: bool = False,
) -> dict[str, Any]:
    """
    Build ranked priority queue for active assignments.

    Returns dict with summary, optional rows, computed_at_utc (ISO string).
    When ``diversified`` is True, applies Phase 2 re-ranking (caps, floor, exploration, optional MMR)
    on top of the standard ordering without changing underlying scores.
    """
    now = _utc(now_utc) or datetime.now(timezone.utc)
    wf, wopp, whealth, wstu, wwarm = _normalize_weights()

    q = (
        db.query(Assignment)
        .join(Student, Assignment.student_id == Student.id)
        .join(HRContact, Assignment.hr_id == HRContact.id)
        .filter(Assignment.status == "active")
    )
    if student_id is not None:
        q = q.filter(Assignment.student_id == student_id)
    if not include_demo:
        q = q.filter(Student.is_demo.is_(False), HRContact.is_demo.is_(False))

    assignments = q.order_by(Assignment.assigned_date.desc().nullslast()).limit(_MAX_ASSIGN_SCAN).all()
    if not assignments:
        empty_summary = {
            "send_now_count": 0,
            "followup_due_count": 0,
            "warm_lead_priority_count": 0,
            "wait_for_cooldown_count": 0,
            "suppressed_count": 0,
            "low_priority_count": 0,
            "avg_priority_score": None,
            "total_candidates": 0,
        }
        out: dict[str, Any] = {
            "computed_at_utc": now.isoformat(),
            "summary": empty_summary,
            "diversity_metrics": {
                "ranking_mode": "standard",
                "diversity_layer_applied": False,
                "top_k": 0,
                "requested_limit": 0,
                "returned_count": 0,
            },
        }
        if include_rows:
            out["rows"] = []
        return out

    pair_set = {(a.student_id, a.hr_id) for a in assignments}
    st_ids = {p[0] for p in pair_set}
    hr_ids_set = {p[1] for p in pair_set}

    students = {s.id: s for s in db.query(Student).filter(Student.id.in_(st_ids)).all()}
    hrs = {h.id: h for h in db.query(HRContact).filter(HRContact.id.in_(hr_ids_set)).all()}

    campaigns: list[EmailCampaign] = []
    pair_list = list(pair_set)
    dialect = getattr(getattr(db, "bind", None), "dialect", None)
    dialect_name = getattr(dialect, "name", "") or ""
    _chunk = 400 if dialect_name == "postgresql" else 80
    for i in range(0, len(pair_list), _chunk):
        chunk = pair_list[i : i + _chunk]
        if not chunk:
            continue
        if dialect_name == "postgresql":
            campaigns.extend(
                db.query(EmailCampaign)
                .filter(tuple_(EmailCampaign.student_id, EmailCampaign.hr_id).in_(chunk))
                .all()
            )
        else:
            cond = or_(
                *(
                    and_(EmailCampaign.student_id == sid, EmailCampaign.hr_id == hid)
                    for sid, hid in chunk
                )
            )
            campaigns.extend(db.query(EmailCampaign).filter(cond).all())
    by_pair: dict[tuple[Any, Any], list[EmailCampaign]] = {}
    for c in campaigns:
        key = (c.student_id, c.hr_id)
        by_pair.setdefault(key, []).append(c)

    health_bundles = compute_health_for_hr_ids(db, list(hr_ids_set), skip_domain_histogram=True)
    blocked_emails = _blocked_email_set(db)
    cooldown_students = _student_gmail_auth_cooldown_ids(db, st_ids, now)

    raw_rows: list[_RawRow] = []

    for a in assignments:
        st = students.get(a.student_id)
        hr = hrs.get(a.hr_id)
        if st is None or hr is None:
            continue

        pair_cs = by_pair.get((a.student_id, a.hr_id), [])
        fu = compute_followup_eligibility_for_pair(
            db,
            student_id=st.id,
            hr_id=hr.id,
            now_utc=now,
            student_row=st,
            hr_row=hr,
            # If batch fetch missed rows, fall back to per-pair DB load inside eligibility.
            pair_campaigns=pair_cs if pair_cs else None,
            trust_active_assignment=True,
        )
        bundle = health_bundles.get(hr.id) or {}
        hr_tier = str(bundle.get("tier") or "C")
        health = float(bundle.get("health_score") or 0.0)
        opportunity = float(bundle.get("opportunity_score") or 0.0)

        fu_urg, fu_reasons = _followup_urgency_component(fu, now, pair_cs)
        st_score, st_reasons = _student_priority_score(st)
        warm_score, warm_reasons = _warm_lead_component(opportunity, hr_tier, pair_cs, fu)

        next_c = _next_due_campaign(pair_cs, now)
        next_sched = _utc(getattr(next_c, "scheduled_at", None)) if next_c else None
        next_future = _next_future_scheduled(pair_cs, now)
        since = now - timedelta(days=OVER_CONTACT_WINDOW_DAYS)
        over_n = _pair_sent_count_since(db, st.id, hr.id, since)
        student_cd = st.id in cooldown_students
        hr_paused = _is_hr_paused_send(hr, now)
        cd_pen, cd_reasons = _cooldown_penalty_component(
            hr, st, student_cd, hr_paused, over_n, next_future or next_sched, now
        )
        pu_wait = _utc(getattr(hr, "paused_until", None))

        # Blend (cooldown is subtractive — not multiplied into HR dimensions to avoid double counting)
        blended = (
            wf * fu_urg
            + wopp * opportunity
            + whealth * health
            + wstu * st_score
            + wwarm * warm_score
        )
        priority = blended - 0.35 * cd_pen
        priority = max(0.0, min(100.0, priority))

        em_l = (hr.email or "").strip().lower()

        # --- Bucket + guardrails ------------------------------------------------
        reasons: list[str] = []
        reasons.extend(fu_reasons)
        reasons.extend(st_reasons)
        reasons.extend(warm_reasons)
        for r in cd_reasons:
            if r not in reasons:
                reasons.append(r)

        suppress = False
        if (st.status or "").lower() != "active":
            suppress = True
            reasons.append("- Student inactive — do not send")
        if (getattr(st, "email_health_status", "") or "").lower() == "flagged":
            suppress = True
            reasons.append("- Student email health flagged — do not send")
        if not hr.is_valid or (hr.status or "").lower() in ("invalid", "blacklisted"):
            suppress = True
            reasons.append("- Invalid or blacklisted HR")
        if em_l and em_l in blocked_emails:
            suppress = True
            reasons.append("- HR email on blocked list")
        if hr_tier == "D":
            suppress = True
            reasons.append("- HR tier D — suppress / avoid")
        if fu.followup_status in ("REPLIED_STOPPED", "BOUNCED_STOPPED", "COMPLETED_STOPPED"):
            suppress = True
            reasons.append(f"- Thread ended ({fu.followup_status})")
        if fu.followup_status == "PAUSED":
            suppress = True
            reasons.append("- Operator paused thread")

        queue_bucket = "LOW_PRIORITY"
        recommended = "Review timing — low priority queue"
        urgency = "LOW"

        if suppress:
            queue_bucket = "SUPPRESS"
            recommended = "Do not contact — suppressed"
            urgency = "NONE"
            priority = min(priority, 12.0)
        elif fu.send_in_progress:
            queue_bucket = "WAIT_FOR_COOLDOWN"
            recommended = "Wait — send already in progress"
            urgency = "MEDIUM"
            priority = min(priority, 55.0)
        elif fu.eligible_for_followup and fu.followup_status == "DUE_NOW":
            # Eligibility does not encode short Gmail auth cooldown; align bucket with scheduler safety.
            if student_cd:
                queue_bucket = "WAIT_FOR_COOLDOWN"
                recommended = "Wait — student Gmail auth cooldown (follow-up resumes after window)"
                urgency = "MEDIUM"
                priority = min(priority, 55.0)
                reasons.append("- Follow-up due but student in Gmail auth cooldown (~10m) — defer send")
            else:
                queue_bucket = "FOLLOW_UP_DUE"
                step = fu.next_followup_step or 1
                recommended = f"Send follow-up {step} now"
                urgency = "CRITICAL"
                reasons.append("+ Follow-up sequence due")
        elif next_c is not None:
            queue_bucket = "SEND_NOW"
            et = (getattr(next_c, "email_type", None) or "").lower()
            recommended = (
                "Send scheduled initial now"
                if et == "initial"
                else f"Send scheduled {et.replace('_', ' ')} now"
            )
            urgency = "HIGH"
            reasons.append("+ Scheduled send is due now")
        elif (
            fu.followup_status == "WAITING"
            and fu.days_until_due is not None
            and int(fu.days_until_due) <= 3
            and tier_rank(hr_tier) <= 2
            and not suppress
        ):
            queue_bucket = "WARM_LEAD_PRIORITY"
            recommended = "Prioritize — warm lead approaching follow-up window"
            urgency = "HIGH"
        elif (
            tier_rank(hr_tier) <= 2
            and opportunity >= 62.0
            and fu.followup_status == "WAITING"
            and not suppress
        ):
            queue_bucket = "WARM_LEAD_PRIORITY"
            recommended = "Prioritize — responsive HR with pending sequence"
            urgency = "MEDIUM"
        elif (
            hr_paused
            or student_cd
            or (next_sched is not None and next_sched > now)
            or (next_future is not None)
            or (
                fu.followup_status == "WAITING"
                and not fu.eligible_for_followup
                and (fu.blocked_reason or "") != "Initial not sent"
            )
            or (
                pu_wait is not None
                and pu_wait > now
                and (hr.status or "").lower() != "paused"
            )
        ):
            queue_bucket = "WAIT_FOR_COOLDOWN"
            recommended = "Wait — cooldown, schedule, or interval guard"
            urgency = "MEDIUM"
            priority = min(priority, max(0.0, priority - 5.0))
        elif (fu.blocked_reason or "") == "Initial not sent":
            queue_bucket = "LOW_PRIORITY"
            recommended = "Prepare initial outreach — assignment ready, no send logged yet"
            urgency = "MEDIUM"
        else:
            queue_bucket = "LOW_PRIORITY"
            recommended = "Queue later — no immediate due signal"
            urgency = "LOW"

        # HR tier boosts / labels (orchestration only — scores already include HR health/opp)
        if hr_tier == "A" and not suppress:
            reasons.append("+ A-tier HR")
            priority = min(100.0, priority + 4.0)
        elif hr_tier == "B" and not suppress:
            reasons.append("+ B-tier HR")
            priority = min(100.0, priority + 2.0)

        if not (getattr(st, "app_password", None) or "").strip() and not (
            getattr(st, "gmail_connected", False) or (getattr(st, "gmail_refresh_token", None) or "").strip()
        ):
            reasons.append("- Cannot auto-send: configure OAuth or app password")
            if queue_bucket == "SEND_NOW":
                queue_bucket = "WAIT_FOR_COOLDOWN"
                recommended = "Fix student configuration before sending"
                priority = min(priority, 40.0)

        # Dedupe reasons while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for r in reasons:
            if r not in seen:
                seen.add(r)
                deduped.append(r)

        cooldown_bits: list[str] = []
        if student_cd:
            cooldown_bits.append("Student Gmail auth cooldown (10m)")
        if hr_paused:
            cooldown_bits.append("HR paused / not hiring")
        pu2 = _utc(getattr(hr, "paused_until", None))
        if pu2 and pu2 > now:
            cooldown_bits.append(f"HR paused_until until {pu2.isoformat()}")
        if next_future:
            cooldown_bits.append(f"Next send scheduled at {next_future.isoformat()}")
        elif next_sched and next_sched > now:
            cooldown_bits.append(f"Next send scheduled at {next_sched.isoformat()}")

        next_touch = None
        if next_c and next_sched:
            next_touch = next_sched.isoformat()
        elif next_future:
            next_touch = next_future.isoformat()
        elif fu.due_date_utc:
            next_touch = fu.due_date_utc

        student_cd_fu_deferred = bool(
            fu.eligible_for_followup and fu.followup_status == "DUE_NOW" and student_cd and not suppress
        )
        diag = _build_decision_diagnostics(
            computed_at_iso=now.isoformat(),
            queue_bucket=queue_bucket,
            suppress=suppress,
            recommended_action=recommended,
            fu=fu,
            deduped_reasons=deduped,
            cd_reasons=cd_reasons,
            cooldown_status_line="; ".join(cooldown_bits) if cooldown_bits else None,
            wf=wf,
            wopp=wopp,
            whealth=whealth,
            wstu=wstu,
            wwarm=wwarm,
            fu_urg=fu_urg,
            st_score=st_score,
            warm_score=warm_score,
            health=health,
            opportunity=opportunity,
            blended=blended,
            cd_pen=cd_pen,
            priority=priority,
            pair_cs=pair_cs,
            student_cd_fu_deferred=student_cd_fu_deferred,
            has_next_due_scheduled=next_c is not None,
        )

        cid = next_c.id if next_c else None
        fp = _fingerprint_parts(
            bucket=queue_bucket,
            fu_status=fu.followup_status,
            tier=hr_tier,
            scheduled_at=next_touch,
            score_bucket=int(round(priority)),
            campaign_id=str(cid) if cid else None,
        )

        raw_rows.append(
            _RawRow(
                student=st,
                hr=hr,
                priority_score=round(priority, 2),
                recommendation_reason=deduped,
                recommended_action=recommended,
                urgency_level=urgency,
                queue_bucket=queue_bucket,
                hr_tier=hr_tier,
                health_score=health,
                opportunity_score=opportunity,
                dimension_scores={
                    "followup_urgency": round(fu_urg, 2),
                    "hr_opportunity": round(opportunity, 2),
                    "hr_health": round(health, 2),
                    "student_priority": round(st_score, 2),
                    "warm_lead": round(warm_score, 2),
                    "cooldown_penalty": round(cd_pen, 2),
                },
                next_best_touch=next_touch,
                cooldown_status="; ".join(cooldown_bits) if cooldown_bits else None,
                followup_status=fu.followup_status,
                campaign_id=cid,
                signal_fingerprint=fp,
                sort_tuple=(),
                decision_diagnostics=diag,
            )
        )

    # Filter
    bucket_u = bucket.strip().upper() if bucket else None
    tier_u = tier.strip().upper() if tier else None
    filtered: list[_RawRow] = []
    for r in raw_rows:
        if bucket_u and r.queue_bucket != bucket_u:
            continue
        if tier_u and r.hr_tier.upper() != tier_u:
            continue
        if only_due and r.queue_bucket not in ("SEND_NOW", "FOLLOW_UP_DUE"):
            continue
        filtered.append(r)

    # Stable sort: bucket priority, then score desc, follow-up urgency dim, student id, hr id
    def sort_key(row: _RawRow) -> tuple[Any, ...]:
        fu_u = row.dimension_scores.get("followup_urgency", 0.0)
        return (
            BUCKET_ORDER.get(row.queue_bucket, 99),
            -row.priority_score,
            -fu_u,
            str(row.student.id),
            str(row.hr.id),
        )

    filtered.sort(key=sort_key)
    lim = max(1, min(int(limit), 500))
    ranked, diversity_metrics = apply_diversity_layer(filtered, lim, diversified=diversified)

    # Assign ranks (dense among returned)
    for i, row in enumerate(ranked, start=1):
        row.sort_tuple = sort_key(row)  # type: ignore[misc]

    summary_counts = {
        "send_now": 0,
        "followup_due": 0,
        "warm_lead_priority": 0,
        "wait_for_cooldown": 0,
        "suppress": 0,
        "low_priority": 0,
    }
    for r in filtered:
        b = r.queue_bucket
        if b == "SEND_NOW":
            summary_counts["send_now"] += 1
        elif b == "FOLLOW_UP_DUE":
            summary_counts["followup_due"] += 1
        elif b == "WARM_LEAD_PRIORITY":
            summary_counts["warm_lead_priority"] += 1
        elif b == "WAIT_FOR_COOLDOWN":
            summary_counts["wait_for_cooldown"] += 1
        elif b == "SUPPRESS":
            summary_counts["suppress"] += 1
        else:
            summary_counts["low_priority"] += 1

    nonsup_scores = [r.priority_score for r in filtered if r.queue_bucket != "SUPPRESS"]
    avg = round(sum(nonsup_scores) / len(nonsup_scores), 2) if nonsup_scores else None

    summary = {
        "send_now_count": summary_counts["send_now"],
        "followup_due_count": summary_counts["followup_due"],
        "warm_lead_priority_count": summary_counts["warm_lead_priority"],
        "wait_for_cooldown_count": summary_counts["wait_for_cooldown"],
        "suppressed_count": summary_counts["suppress"],
        "low_priority_count": summary_counts["low_priority"],
        "avg_priority_score": avg,
        "total_candidates": len(filtered),
    }

    out: dict[str, Any] = {
        "computed_at_utc": now.isoformat(),
        "summary": summary,
        "diversity_metrics": diversity_metrics,
    }

    if include_rows:
        rows_out: list[dict[str, Any]] = []
        for rank, row in enumerate(ranked, start=1):
            rows_out.append(
                {
                    "student": {
                        "id": row.student.id,
                        "name": row.student.name,
                        "gmail_address": row.student.gmail_address,
                        "status": getattr(row.student, "status", "active") or "active",
                        "email_health_status": getattr(row.student, "email_health_status", "healthy")
                        or "healthy",
                        "is_demo": bool(getattr(row.student, "is_demo", False)),
                    },
                    "hr": {
                        "id": row.hr.id,
                        "name": row.hr.name,
                        "company": row.hr.company,
                        "email": row.hr.email,
                        "is_valid": bool(row.hr.is_valid),
                        "status": getattr(row.hr, "status", None),
                    },
                    "priority_score": row.priority_score,
                    "priority_rank": rank,
                    "recommendation_reason": row.recommendation_reason,
                    "recommended_action": row.recommended_action,
                    "urgency_level": row.urgency_level,
                    "queue_bucket": row.queue_bucket,
                    "hr_tier": row.hr_tier,
                    "health_score": row.health_score,
                    "opportunity_score": row.opportunity_score,
                    "dimension_scores": row.dimension_scores,
                    "next_best_touch": row.next_best_touch,
                    "cooldown_status": row.cooldown_status,
                    "followup_status": row.followup_status,
                    "campaign_id": row.campaign_id,
                    "signal_fingerprint": row.signal_fingerprint,
                    "ranking_mode": diversity_metrics.get("ranking_mode", "standard"),
                    "ranking_slot_type": getattr(row, "ranking_slot_type", None),
                    "diversity_note": (
                        "EXPLORATION — under-contacted / higher-uncertainty opportunity (not a safety downgrade)."
                        if getattr(row, "ranking_slot_type", None) == "EXPLORATION"
                        else None
                    ),
                    "decision_diagnostics": getattr(row, "decision_diagnostics", None) or {},
                }
            )
        out["rows"] = rows_out

    return out


def scheduler_priority_hook_enabled() -> bool:
    """Design hook: default false; no scheduler wiring in Phase 1."""
    return (os.getenv("SCHEDULER_USE_PRIORITY_QUEUE") or "").strip().lower() in ("1", "true", "yes")
