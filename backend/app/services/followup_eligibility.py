from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, tuple_
from sqlalchemy.orm import Session

from app.models import EmailCampaign, Student, HRContact, Assignment


# Cumulative cadence from **initial sent_at** (single anchor):
# - FU1 due day +7, FU2 day +14, FU3 day +21 (matches pre-created sequence_service rows).
_CUMULATIVE_DAYS_FROM_INITIAL_SENT = {1: 7, 2: 14, 3: 21}

_FOLLOWUP_STATUS = (
    "DUE_NOW",
    "WAITING",
    "REPLIED_STOPPED",
    "BOUNCED_STOPPED",
    "COMPLETED_STOPPED",
    "PAUSED",
    "SEND_IN_PROGRESS",
)


@dataclass(frozen=True)
class FollowupEligibility:
    student_id: str
    hr_id: str
    campaign_id: str | None
    eligible_for_followup: bool
    followup_status: str
    next_followup_step: int | None  # 1..3
    next_template_type: str | None  # FOLLOWUP_1..3
    due_date_utc: str | None
    days_until_due: int | None
    blocked_reason: str | None
    current_step: int  # 0..3
    paused: bool
    send_in_progress: bool


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_bounce_or_blocked(c: EmailCampaign) -> bool:
    rs = (getattr(c, "reply_status", None) or "").strip().upper()
    ft = (getattr(c, "failure_type", None) or "").strip().upper()
    ds = (getattr(c, "delivery_status", None) or "").strip().upper()
    if rs in ("BOUNCED", "BLOCKED"):
        return True
    if ft in ("BOUNCED", "BLOCKED"):
        return True
    # Delivery failed plus a bounce/block signal is treated as hard-stop.
    if ds == "FAILED" and rs in ("BOUNCED", "BLOCKED"):
        return True
    return False


def compute_followup_eligibility_for_pair(
    db: Session,
    *,
    student_id,
    hr_id,
    now_utc: datetime | None = None,
    student_row: Student | None = None,
    hr_row: HRContact | None = None,
    pair_campaigns: list[EmailCampaign] | None = None,
    trust_active_assignment: bool = False,
    prehas_active_assignment: bool | None = None,
) -> FollowupEligibility:
    """
    Pure eligibility engine (no side effects).
    Uses existing EmailCampaign rows as the source of truth.

    Optional fast path for batch consumers (e.g. priority queue): pass ``student_row``,
    ``hr_row``, and ``pair_campaigns`` to skip redundant lookups, and set
    ``trust_active_assignment=True`` when the caller already verified an active assignment.

    ``prehas_active_assignment`` avoids per-row ``Assignment`` queries when listing pairs:
    ``False`` => treat as no active assignment; ``True`` => skip lookup and proceed;
    ``None`` => use ``trust_active_assignment`` / DB lookup as before.
    """
    now = _ensure_utc(now_utc) or datetime.now(timezone.utc)

    if student_row is not None and student_row.id == student_id:
        st = student_row
    else:
        st = db.query(Student).filter(Student.id == student_id).first()
    if hr_row is not None and hr_row.id == hr_id:
        hr = hr_row
    else:
        hr = db.query(HRContact).filter(HRContact.id == hr_id).first()
    if st is None or hr is None:
        return FollowupEligibility(
            student_id=str(student_id),
            hr_id=str(hr_id),
            campaign_id=None,
            eligible_for_followup=False,
            followup_status="WAITING",
            next_followup_step=None,
            next_template_type=None,
            due_date_utc=None,
            days_until_due=None,
            blocked_reason="Missing student or HR",
            current_step=0,
            paused=False,
            send_in_progress=False,
        )

    if getattr(st, "status", None) != "active":
        return FollowupEligibility(
            student_id=str(student_id),
            hr_id=str(hr_id),
            campaign_id=None,
            eligible_for_followup=False,
            followup_status="WAITING",
            next_followup_step=None,
            next_template_type=None,
            due_date_utc=None,
            days_until_due=None,
            blocked_reason="Inactive student",
            current_step=0,
            paused=False,
            send_in_progress=False,
        )

    if getattr(hr, "is_valid", True) is not True:
        return FollowupEligibility(
            student_id=str(student_id),
            hr_id=str(hr_id),
            campaign_id=None,
            eligible_for_followup=False,
            followup_status="BOUNCED_STOPPED",
            next_followup_step=None,
            next_template_type=None,
            due_date_utc=None,
            days_until_due=None,
            blocked_reason="Invalid recipient (bounced/blocked)",
            current_step=0,
            paused=False,
            send_in_progress=False,
        )

    if prehas_active_assignment is False:
        return FollowupEligibility(
            student_id=str(student_id),
            hr_id=str(hr_id),
            campaign_id=None,
            eligible_for_followup=False,
            followup_status="WAITING",
            next_followup_step=None,
            next_template_type=None,
            due_date_utc=None,
            days_until_due=None,
            blocked_reason="No active assignment",
            current_step=0,
            paused=False,
            send_in_progress=False,
        )

    if not trust_active_assignment and prehas_active_assignment is not True:
        assignment = (
            db.query(Assignment)
            .filter(
                Assignment.student_id == student_id,
                Assignment.hr_id == hr_id,
                Assignment.status == "active",
            )
            .first()
        )
        if assignment is None:
            return FollowupEligibility(
                student_id=str(student_id),
                hr_id=str(hr_id),
                campaign_id=None,
                eligible_for_followup=False,
                followup_status="WAITING",
                next_followup_step=None,
                next_template_type=None,
                due_date_utc=None,
                days_until_due=None,
                blocked_reason="No active assignment",
                current_step=0,
                paused=False,
                send_in_progress=False,
            )

    if pair_campaigns is not None:
        campaigns = list(pair_campaigns)
    else:
        campaigns = (
            db.query(EmailCampaign)
            .filter(EmailCampaign.student_id == student_id, EmailCampaign.hr_id == hr_id)
            .all()
        )

    initial = next((c for c in campaigns if (c.email_type or "").lower() == "initial"), None)
    if initial is None:
        return FollowupEligibility(
            student_id=str(student_id),
            hr_id=str(hr_id),
            campaign_id=None,
            eligible_for_followup=False,
            followup_status="WAITING",
            next_followup_step=None,
            next_template_type=None,
            due_date_utc=None,
            days_until_due=None,
            blocked_reason="Initial not sent",
            current_step=0,
            paused=False,
            send_in_progress=False,
        )

    # Reply suppression before strict initial.status == "sent" (initial row may be status=replied).
    if any(bool(getattr(c, "replied", False)) or (getattr(c, "status", "") or "").lower() == "replied" for c in campaigns):
        return FollowupEligibility(
            student_id=str(student_id),
            hr_id=str(hr_id),
            campaign_id=str(initial.id),
            eligible_for_followup=False,
            followup_status="REPLIED_STOPPED",
            next_followup_step=None,
            next_template_type=None,
            due_date_utc=None,
            days_until_due=None,
            blocked_reason="Already replied",
            current_step=0,
            paused=False,
            send_in_progress=False,
        )

    # Operator collision guard: if any row for this pair is processing, treat as send-in-progress.
    send_in_progress = any((getattr(c, "status", "") or "").lower() == "processing" for c in campaigns)
    if send_in_progress:
        return FollowupEligibility(
            student_id=str(student_id),
            hr_id=str(hr_id),
            campaign_id=str(initial.id),
            eligible_for_followup=False,
            followup_status="SEND_IN_PROGRESS",
            next_followup_step=None,
            next_template_type=None,
            due_date_utc=None,
            days_until_due=None,
            blocked_reason="Send in progress",
            current_step=0,
            paused=False,
            send_in_progress=True,
        )

    if (getattr(initial, "status", None) or "").lower() != "sent":
        return FollowupEligibility(
            student_id=str(student_id),
            hr_id=str(hr_id),
            campaign_id=str(initial.id) if initial is not None else None,
            eligible_for_followup=False,
            followup_status="WAITING",
            next_followup_step=None,
            next_template_type=None,
            due_date_utc=None,
            days_until_due=None,
            blocked_reason="Initial not sent",
            current_step=0,
            paused=False,
            send_in_progress=False,
        )

    # Hard-stop bounces/blocked: any bounce signal blocks.
    if any(_is_bounce_or_blocked(c) for c in campaigns):
        return FollowupEligibility(
            student_id=str(student_id),
            hr_id=str(hr_id),
            campaign_id=str(initial.id),
            eligible_for_followup=False,
            followup_status="BOUNCED_STOPPED",
            next_followup_step=None,
            next_template_type=None,
            due_date_utc=None,
            days_until_due=None,
            blocked_reason="Bounced/blocked recipient",
            current_step=0,
            paused=False,
            send_in_progress=False,
        )

    paused = any((getattr(c, "status", "") or "").lower() == "paused" for c in campaigns)
    if paused:
        return FollowupEligibility(
            student_id=str(student_id),
            hr_id=str(hr_id),
            campaign_id=str(initial.id),
            eligible_for_followup=False,
            followup_status="PAUSED",
            next_followup_step=None,
            next_template_type=None,
            due_date_utc=None,
            days_until_due=None,
            blocked_reason="Manual pause enabled",
            current_step=0,
            paused=True,
            send_in_progress=False,
        )

    sent_fu = {1: False, 2: False, 3: False}
    for c in campaigns:
        et = (getattr(c, "email_type", None) or "").lower()
        if (getattr(c, "status", None) or "").lower() != "sent":
            continue
        if et == "followup_1":
            sent_fu[1] = True
        elif et == "followup_2":
            sent_fu[2] = True
        elif et == "followup_3":
            sent_fu[3] = True

    # Invalid progression guard.
    if sent_fu[2] and not sent_fu[1]:
        return FollowupEligibility(
            student_id=str(student_id),
            hr_id=str(hr_id),
            campaign_id=str(initial.id),
            eligible_for_followup=False,
            followup_status="WAITING",
            next_followup_step=None,
            next_template_type=None,
            due_date_utc=None,
            days_until_due=None,
            blocked_reason="Invalid step progression (followup_2 sent without followup_1)",
            current_step=0,
            paused=False,
            send_in_progress=False,
        )
    if sent_fu[3] and (not sent_fu[1] or not sent_fu[2]):
        return FollowupEligibility(
            student_id=str(student_id),
            hr_id=str(hr_id),
            campaign_id=str(initial.id),
            eligible_for_followup=False,
            followup_status="WAITING",
            next_followup_step=None,
            next_template_type=None,
            due_date_utc=None,
            days_until_due=None,
            blocked_reason="Invalid step progression (followup_3 sent without prior steps)",
            current_step=0,
            paused=False,
            send_in_progress=False,
        )

    current_step = 3 if sent_fu[3] else 2 if sent_fu[2] else 1 if sent_fu[1] else 0
    if current_step >= 3:
        return FollowupEligibility(
            student_id=str(student_id),
            hr_id=str(hr_id),
            campaign_id=str(initial.id),
            eligible_for_followup=False,
            followup_status="COMPLETED_STOPPED",
            next_followup_step=None,
            next_template_type=None,
            due_date_utc=None,
            days_until_due=None,
            blocked_reason="Follow-up 3 already sent",
            current_step=current_step,
            paused=False,
            send_in_progress=False,
        )

    next_step = current_step + 1
    initial_sent = _ensure_utc(getattr(initial, "sent_at", None))
    if initial_sent is None:
        return FollowupEligibility(
            student_id=str(student_id),
            hr_id=str(hr_id),
            campaign_id=str(initial.id),
            eligible_for_followup=False,
            followup_status="WAITING",
            next_followup_step=None,
            next_template_type=None,
            due_date_utc=None,
            days_until_due=None,
            blocked_reason="Initial missing sent_at",
            current_step=current_step,
            paused=False,
            send_in_progress=False,
        )

    delay_days = int(_CUMULATIVE_DAYS_FROM_INITIAL_SENT.get(next_step, 9999))
    due_dt = initial_sent + timedelta(days=delay_days)
    days_until_due = int((due_dt - now).total_seconds() // 86400)

    if now < due_dt:
        wait_days = max(0, int((due_dt - now).total_seconds() // 86400))
        return FollowupEligibility(
            student_id=str(student_id),
            hr_id=str(hr_id),
            campaign_id=str(initial.id),
            eligible_for_followup=False,
            followup_status="WAITING",
            next_followup_step=next_step,
            next_template_type=f"FOLLOWUP_{next_step}",
            due_date_utc=due_dt.isoformat(),
            days_until_due=max(0, days_until_due),
            blocked_reason=f"Waiting for {delay_days}-day interval ({max(0, wait_days)}d remaining)",
            current_step=current_step,
            paused=False,
            send_in_progress=False,
        )

    # Eligible
    return FollowupEligibility(
        student_id=str(student_id),
        hr_id=str(hr_id),
        campaign_id=str(initial.id),
        eligible_for_followup=True,
        followup_status="DUE_NOW",
        next_followup_step=next_step,
        next_template_type=f"FOLLOWUP_{next_step}",
        due_date_utc=due_dt.isoformat(),
        days_until_due=0,
        blocked_reason=None,
        current_step=current_step,
        paused=False,
        send_in_progress=False,
    )


def _pick_display_initial_for_pair(
    campaigns: list[EmailCampaign],
    max_sent_at: datetime | None,
) -> EmailCampaign | None:
    """Prefer the sent initial row matching ``max_sent_at`` (per-pair GROUP BY), else latest by time."""
    initials = [
        c
        for c in campaigns
        if (c.email_type or "").lower() == "initial" and (c.status or "").lower() == "sent"
    ]
    if not initials:
        return None

    def sort_key(c: EmailCampaign) -> tuple[Any, ...]:
        return (
            c.sent_at or datetime.min,
            c.created_at or c.scheduled_at or datetime.min,
            str(c.id),
        )

    if max_sent_at is not None:
        same_mx = [c for c in initials if c.sent_at == max_sent_at]
        if same_mx:
            return max(same_mx, key=sort_key)
    return max(initials, key=sort_key)


def list_followup_eligibility(
    db: Session,
    *,
    include_demo: bool = False,
    now_utc: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """
    Returns rows + summary counts for **this page** (due_now / blocked / … are not global).

    Pairs are distinct (student_id, hr_id) with at least one sent ``initial``; ordering matches
    the old behavior (latest ``sent_at`` on any sent initial for that pair, descending).
    """
    now = _ensure_utc(now_utc) or datetime.now(timezone.utc)
    lim = max(1, min(int(limit), 500))
    off = max(0, int(offset))

    # One row per pair: max(sent_at) over qualifying initials (same ordering intent as scan+dedupe).
    pair_groups = (
        db.query(
            EmailCampaign.student_id.label("sid"),
            EmailCampaign.hr_id.label("hid"),
            func.max(EmailCampaign.sent_at).label("mx"),
        )
        .join(Student, EmailCampaign.student_id == Student.id)
        .join(HRContact, EmailCampaign.hr_id == HRContact.id)
        .filter(func.lower(EmailCampaign.email_type) == "initial", EmailCampaign.status == "sent")
    )
    if not include_demo:
        pair_groups = pair_groups.filter(Student.is_demo.is_(False), HRContact.is_demo.is_(False))
    inner = pair_groups.group_by(EmailCampaign.student_id, EmailCampaign.hr_id).subquery()

    total_pairs = int(db.query(func.count()).select_from(inner).scalar() or 0)

    page_rows = (
        db.query(inner.c.sid, inner.c.hid, inner.c.mx)
        .select_from(inner)
        .order_by(inner.c.mx.desc().nullslast(), inner.c.sid, inner.c.hid)
        .offset(off)
        .limit(lim)
        .all()
    )

    if not page_rows:
        return {
            "now_utc": now.isoformat(),
            "summary": {
                "total": 0,
                "due_now": 0,
                "blocked": 0,
                "paused": 0,
                "completed": 0,
            },
            "status_breakdown": {},
            "rows": [],
            "pagination": {
                "limit": lim,
                "offset": off,
                "returned": 0,
                "total_pairs": total_pairs,
                "has_more": False,
                "next_offset": None,
            },
        }

    pair_tuples = [(r[0], r[1]) for r in page_rows]
    mx_by_pair = {(r[0], r[1]): r[2] for r in page_rows}

    all_campaigns = (
        db.query(EmailCampaign)
        .filter(tuple_(EmailCampaign.student_id, EmailCampaign.hr_id).in_(pair_tuples))
        .all()
    )
    by_pair: dict[tuple[Any, Any], list[EmailCampaign]] = defaultdict(list)
    for c in all_campaigns:
        by_pair[(c.student_id, c.hr_id)].append(c)

    active_pairs: set[tuple[Any, Any]] = set()
    if pair_tuples:
        for sid, hid in (
            db.query(Assignment.student_id, Assignment.hr_id)
            .filter(
                Assignment.status == "active",
                tuple_(Assignment.student_id, Assignment.hr_id).in_(pair_tuples),
            )
            .all()
        ):
            active_pairs.add((sid, hid))

    sid_set = {p[0] for p in pair_tuples}
    hid_set = {p[1] for p in pair_tuples}
    students = {s.id: s for s in db.query(Student).filter(Student.id.in_(sid_set)).all()}
    hrs = {h.id: h for h in db.query(HRContact).filter(HRContact.id.in_(hid_set)).all()}

    out_rows: list[dict[str, Any]] = []
    due_now = blocked = paused = completed = 0
    status_breakdown: Counter[str] = Counter()

    for sid, hid, _mx in page_rows:
        st = students.get(sid)
        hr = hrs.get(hid)
        if st is None or hr is None:
            continue
        campaigns = by_pair.get((sid, hid), [])
        display_initial = _pick_display_initial_for_pair(campaigns, mx_by_pair.get((sid, hid)))
        if display_initial is None:
            continue

        has_assign = (sid, hid) in active_pairs
        state = compute_followup_eligibility_for_pair(
            db,
            student_id=sid,
            hr_id=hid,
            now_utc=now,
            student_row=st,
            hr_row=hr,
            pair_campaigns=campaigns,
            prehas_active_assignment=has_assign,
        )
        r = {
            "student_id": str(st.id),
            "student_name": getattr(st, "name", None),
            "hr_id": str(hr.id),
            "company": getattr(hr, "company", None),
            "hr_email": getattr(hr, "email", None),
            "initial_campaign_id": str(display_initial.id),
            "current_step": int(state.current_step),
            "eligible_for_followup": bool(state.eligible_for_followup),
            "followup_status": state.followup_status,
            "send_in_progress": bool(state.send_in_progress),
            "next_followup_step": state.next_followup_step,
            "next_template_type": state.next_template_type,
            "due_date_utc": state.due_date_utc,
            "days_until_due": state.days_until_due,
            "blocked_reason": state.blocked_reason,
            "paused": bool(state.paused),
        }
        out_rows.append(r)
        status_breakdown[state.followup_status] += 1
        if state.eligible_for_followup:
            due_now += 1
        elif state.paused:
            paused += 1
        elif state.followup_status == "COMPLETED_STOPPED":
            completed += 1
        else:
            blocked += 1

    returned = len(out_rows)
    consumed_pairs = len(page_rows)
    has_more = off + consumed_pairs < total_pairs

    return {
        "now_utc": now.isoformat(),
        "summary": {
            "total": returned,
            "due_now": int(due_now),
            "blocked": int(blocked),
            "paused": int(paused),
            "completed": int(completed),
        },
        "status_breakdown": dict(sorted(status_breakdown.items(), key=lambda kv: (-kv[1], kv[0]))),
        "rows": out_rows,
        "pagination": {
            "limit": lim,
            "offset": off,
            "returned": returned,
            "total_pairs": total_pairs,
            "has_more": bool(has_more),
            "next_offset": (off + consumed_pairs) if has_more else None,
        },
    }

