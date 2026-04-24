"""Analytics API – summary metrics + breakdowns for dashboard."""
import logging
from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, case, and_, or_, desc
from sqlalchemy.orm import Session, aliased

from app.auth import require_api_key
from app.database import get_db
from app.models import Student, HRContact, Assignment, Response
from app.models.email_campaign import EmailCampaign
from app.utils.campaign_query_filters import email_campaigns_scoped_to_hr
from app.utils.datetime_utils import ensure_utc, to_ist

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(require_api_key)])
logger = logging.getLogger(__name__)

_TEMPLATE_NONE = "(none)"

# Reply-rate denominator: campaign rows that left the outbound queue (not pending/scheduled/processing).
_CAMPAIGN_DENOM_STATUSES = (
    "sent",
    "failed",
    "replied",
    "cancelled",
    "expired",
    "paused",
)


def _debug_log_replied_by_student(db: Session) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return
    rows = (
        db.query(EmailCampaign.student_id, func.count(EmailCampaign.id))
        .filter(EmailCampaign.replied.is_(True))
        .group_by(EmailCampaign.student_id)
        .all()
    )
    logger.debug("email_campaigns replied=TRUE by student_id: %s", rows)


@router.get("/summary")
def get_analytics_summary(include_demo: bool = False, db: Session = Depends(get_db)):
    """Global metrics: students, HRs, emails sent, campaigns, replies, rates."""
    try:
        logger.info("Fetching analytics summary...")
        out = _analytics_summary_impl(include_demo, db)
        logger.info("Analytics summary OK")
        return out
    except Exception:
        logger.exception("Error in get_analytics_summary")
        raise HTTPException(status_code=500, detail="Internal server error")


def _analytics_summary_impl(include_demo: bool, db: Session) -> dict:
    students_q = db.query(func.count(Student.id))
    hrs_q = db.query(func.count(HRContact.id))
    if not include_demo:
        students_q = students_q.filter(Student.is_demo.is_(False))
        hrs_q = hrs_q.filter(HRContact.is_demo.is_(False))
    students_count = students_q.scalar() or 0
    hrs_count = hrs_q.scalar() or 0
    assignments_count = db.query(func.count(Assignment.id)).scalar() or 0

    base_query = email_campaigns_scoped_to_hr(db, include_demo=include_demo)

    # Strict DB-aligned counts (reply_status / is_valid only; matches raw SQL expectations).
    bounced = base_query.filter(EmailCampaign.reply_status == "BOUNCED").count()
    # Campaign rows with inbound BLOCKED signal (same scope as base_query: non-demo HR join).
    blocked_hr_count = base_query.filter(
        EmailCampaign.reply_status == "BLOCKED",
    ).count()
    hr_invalid_base = db.query(HRContact)
    if not include_demo:
        hr_invalid_base = hr_invalid_base.filter(HRContact.is_demo.is_(False))
    invalid_hr_contacts = hr_invalid_base.filter(HRContact.is_valid.is_(False)).count()

    total_bounced = bounced
    # Alias: total_blocked === blocked_hr_count (campaign-level BLOCKED rows).
    total_blocked = int(blocked_hr_count)

    # Delivery buckets (mutually exclusive) for dashboard stacked delivery chart:
    # - delivery_sent: delivery_status != FAILED (or NULL)
    # - delivery_failed_other: delivery_status == FAILED but not a known bounced/blocked classification
    # - delivery_bounced: reply_status == BOUNCED
    # - delivery_blocked: reply_status == BLOCKED
    delivery_failed_total = (
        base_query.filter(EmailCampaign.delivery_status == "FAILED")
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )
    delivery_sent_total = (
        base_query.filter(or_(EmailCampaign.delivery_status.is_(None), EmailCampaign.delivery_status != "FAILED"))
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )
    delivery_bounced = int(total_bounced)
    delivery_blocked = int(total_blocked)
    delivery_failed_other = max(0, int(delivery_failed_total) - delivery_bounced - delivery_blocked)

    # Row counts (one row per campaign send), same HR filter as logs / email-status.
    emails_sent = (
        base_query.filter(EmailCampaign.status == "sent")
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )
    emails_failed = (
        base_query.filter(EmailCampaign.status == "failed")
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )
    # Replies = campaigns marked replied (bounce is NOT a reply).
    total_replies = (
        base_query.filter(EmailCampaign.replied.is_(True))
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )

    # Distinct HRs with at least one captured reply (KPI for rate; keeps reply_rate ≤ 100%).
    unique_replies = (
        base_query.filter(EmailCampaign.replied.is_(True))
        .with_entities(func.count(func.distinct(EmailCampaign.hr_id)))
        .scalar()
        or 0
    )

    interested_replies = (
        base_query.filter(
            EmailCampaign.replied.is_(True),
            or_(
                EmailCampaign.reply_status.in_(("INTERESTED", "INTERVIEW")),
                EmailCampaign.reply_text.ilike("%interested%"),
                EmailCampaign.reply_text.ilike("%let's%"),
                EmailCampaign.reply_text.ilike("%schedule%"),
                EmailCampaign.reply_text.ilike("%call%"),
                EmailCampaign.reply_text.ilike("%interview%"),
            ),
        )
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )

    invalid_email_sends = (
        base_query.filter(EmailCampaign.failure_type == "INVALID_EMAIL")
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )

    bounce_rate = (
        round(min(100.0, (100.0 * total_bounced / emails_sent) if emails_sent > 0 else 0.0), 2)
    )
    
    total_attempted = emails_sent + emails_failed 

    success_rate = (
        (emails_sent / total_attempted * 100)
        if total_attempted > 0 else 0
    )
    success_rate = round(max(success_rate, 0), 2)

    campaigns_sent = (
        base_query.with_entities(
            func.count(func.distinct(case((EmailCampaign.status == "sent", EmailCampaign.hr_id))))
        ).scalar()
        or 0
    )
    campaigns_scheduled = (
        base_query.with_entities(
            func.count(
                func.distinct(case((EmailCampaign.status == "scheduled", EmailCampaign.hr_id)))
            )
        ).scalar()
        or 0
    )
    campaigns_total = (
        base_query.with_entities(func.count(func.distinct(EmailCampaign.hr_id))).scalar() or 0
    )

    responses_count = db.query(func.count(Response.id)).scalar() or 0
    reply_rate = round(
        min(100.0, (100 * unique_replies / emails_sent) if emails_sent > 0 else 0.0),
        2,
    )

    replies_initial = (
        base_query.filter(
            func.lower(EmailCampaign.email_type) == "initial",
            EmailCampaign.reply_text.isnot(None),
        )
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )
    replies_fu1 = db.query(func.count(Response.id)).filter(Response.source_email_type == "followup_1").scalar() or 0
    replies_fu2 = db.query(func.count(Response.id)).filter(Response.source_email_type == "followup_2").scalar() or 0
    replies_fu3 = db.query(func.count(Response.id)).filter(Response.source_email_type == "followup_3").scalar() or 0

    # Lifetime campaign-row counts: same HR/demo scope as base_query (DB source of truth for dashboard).
    _lt = (
        base_query.with_entities(
            func.count(EmailCampaign.id),
            func.coalesce(
                func.sum(case((EmailCampaign.status == "sent", 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((EmailCampaign.status == "failed", 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((EmailCampaign.status == "cancelled", 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((EmailCampaign.status == "replied", 1), else_=0)), 0
            ),
        ).one()
    )
    total_emails_all_time = int(_lt[0] or 0)
    total_sent = int(_lt[1] or 0)
    total_failed = int(_lt[2] or 0)
    total_cancelled = int(_lt[3] or 0)
    total_replied = int(_lt[4] or 0)

    return {
        "students": students_count,
        "hrs": hrs_count,
        "hr_contacts": hrs_count,
        "assignments": assignments_count,
        "emails_sent": emails_sent,
        "emails_failed": emails_failed,
        "total": int(total_attempted),
        "sent": emails_sent,
        "failed": emails_failed,
        "replied": int(total_replies),
        "total_replies": int(total_replies),
        "unique_replies": int(unique_replies),
        "success_rate": success_rate,
        "campaigns_sent": campaigns_sent,
        "campaigns_scheduled": campaigns_scheduled,
        "campaigns_total": campaigns_total,
        "responses": responses_count,
        "bounced": int(total_bounced),
        "total_bounced": int(total_bounced),
        "total_blocked": int(total_blocked),
        "total_emails_all_time": total_emails_all_time,
        "total_sent": total_sent,
        "total_failed": total_failed,
        "total_cancelled": total_cancelled,
        "total_replied": total_replied,
        "invalid_hr": int(invalid_hr_contacts),
        "invalid_hr_contacts": int(invalid_hr_contacts),
        "invalid_email_sends": int(invalid_email_sends),
        "blocked_hr_count": int(blocked_hr_count),
        "blocked_hr": int(blocked_hr_count),
        "bounce_rate": bounce_rate,
        "reply_rate": reply_rate,
        "interested_replies": int(interested_replies),
        # Mutually exclusive delivery buckets (prefer these over total_* to avoid double counting).
        "delivery_sent": int(delivery_sent_total),
        "delivery_failed": int(delivery_failed_total),
        "delivery_failed_other": int(delivery_failed_other),
        "delivery_bounced": int(delivery_bounced),
        "delivery_blocked": int(delivery_blocked),
        "replies_initial": int(replies_initial),
        "replies_followup1": int(replies_fu1),
        "replies_followup2": int(replies_fu2),
        "replies_followup3": int(replies_fu3),
        # Backward-compatible aliases
        "replies_followup_1": int(replies_fu1),
        "replies_followup_2": int(replies_fu2),
        "replies_followup_3": int(replies_fu3),
    }


@router.get("/templates")
def get_analytics_templates(include_demo: bool = False, db: Session = Depends(get_db)):
    """
    A/B style metrics: initial sends (seq 1) grouped by template_label,
    replies attributed via Response.source_campaign_id → initial row for same student+HR.
    """
    lbl_sent = func.coalesce(EmailCampaign.template_label, _TEMPLATE_NONE).label("template_label")

    sent_rows_q = (
        db.query(
            lbl_sent,
            func.count(EmailCampaign.id).label("sent"),
        )
        .join(HRContact, EmailCampaign.hr_id == HRContact.id)
        .filter(
            EmailCampaign.sequence_number == 1,
            EmailCampaign.status == "sent",
        )
    )
    if not include_demo:
        sent_rows_q = sent_rows_q.filter(HRContact.is_demo.is_(False))
    sent_rows = sent_rows_q.group_by(lbl_sent).all()

    src_ec = aliased(EmailCampaign)
    init_ec = aliased(EmailCampaign)
    lbl_rep = func.coalesce(init_ec.template_label, _TEMPLATE_NONE).label("template_label")

    reply_rows_q = (
        db.query(
            lbl_rep,
            func.count(Response.id).label("replies"),
        )
        .select_from(Response)
        .join(src_ec, Response.source_campaign_id == src_ec.id)
        .join(
            init_ec,
            and_(
                init_ec.student_id == src_ec.student_id,
                init_ec.hr_id == src_ec.hr_id,
                init_ec.sequence_number == 1,
            ),
        )
        .join(HRContact, src_ec.hr_id == HRContact.id)
    )
    if not include_demo:
        reply_rows_q = reply_rows_q.filter(HRContact.is_demo.is_(False))
    reply_rows = reply_rows_q.group_by(lbl_rep).all()

    by_label: dict[str, dict] = {}
    for lbl, sent in sent_rows:
        key = lbl or _TEMPLATE_NONE
        by_label[key] = {
            "template_label": key,
            "sent": int(sent or 0),
            "replies": 0,
            "reply_rate": 0.0,
        }
    for lbl, rep in reply_rows:
        key = lbl or _TEMPLATE_NONE
        if key not in by_label:
            by_label[key] = {
                "template_label": key,
                "sent": 0,
                "replies": 0,
                "reply_rate": 0.0,
            }
        by_label[key]["replies"] = int(rep or 0)

    out = list(by_label.values())
    for row in out:
        s, r = row["sent"], row["replies"]
        row["reply_rate"] = round(100 * r / s, 1) if s > 0 else (0.0 if r == 0 else 100.0)

    out.sort(key=lambda x: (-x["sent"], x["template_label"]))
    return out


@router.get("/students")
def analytics_by_student(db: Session = Depends(get_db), limit: int = 200, include_demo: bool = False):
    """Per-student breakdown."""
    limit = min(max(int(limit), 1), 1000)

    _debug_log_replied_by_student(db)

    resp_sub = (
        db.query(
            EmailCampaign.student_id.label("sid"),
            func.count(EmailCampaign.id).label("responses"),
        )
        .filter(EmailCampaign.replied.is_(True))
        .group_by(EmailCampaign.student_id)
        .subquery()
    )
    sent_sub = (
        db.query(
            EmailCampaign.student_id.label("sid"),
            func.count(EmailCampaign.id).label("campaigns_sent"),
        )
        .filter(EmailCampaign.status.in_(_CAMPAIGN_DENOM_STATUSES))
        .group_by(EmailCampaign.student_id)
        .subquery()
    )
    tot_sub = (
        db.query(
            EmailCampaign.student_id.label("sid"),
            func.count(EmailCampaign.id).label("campaigns_total"),
        )
        .group_by(EmailCampaign.student_id)
        .subquery()
    )
    ass_sub = (
        db.query(
            Assignment.student_id.label("sid"),
            func.count(func.distinct(Assignment.hr_id)).label("assigned_hrs"),
        )
        .group_by(Assignment.student_id)
        .subquery()
    )

    q = (
        db.query(
            Student.id.label("student_id"),
            Student.name.label("student_name"),
            func.coalesce(ass_sub.c.assigned_hrs, 0).label("assigned_hrs"),
            func.coalesce(tot_sub.c.campaigns_total, 0).label("campaigns_total"),
            func.coalesce(sent_sub.c.campaigns_sent, 0).label("campaigns_sent"),
            func.coalesce(resp_sub.c.responses, 0).label("responses"),
        )
        .select_from(Student)
        .outerjoin(ass_sub, ass_sub.c.sid == Student.id)
        .outerjoin(tot_sub, tot_sub.c.sid == Student.id)
        .outerjoin(sent_sub, sent_sub.c.sid == Student.id)
        .outerjoin(resp_sub, resp_sub.c.sid == Student.id)
    )
    if not include_demo:
        q = q.filter(Student.is_demo.is_(False))
    rows = q.order_by(desc(func.coalesce(resp_sub.c.responses, 0))).limit(limit).all()

    out = []
    for r in rows:
        sent = int(r.campaigns_sent or 0)
        resp = int(r.responses or 0)
        reply_rate = round(100 * resp / sent, 1) if sent > 0 else 0
        out.append(
            {
                "student_id": str(r.student_id),
                "student_name": r.student_name,
                "assigned_hrs": int(r.assigned_hrs or 0),
                "campaigns_total": int(r.campaigns_total or 0),
                "campaigns_sent": sent,
                "responses": resp,
                "reply_rate": reply_rate,
            }
        )
    return out


@router.get("/companies")
def analytics_by_company(db: Session = Depends(get_db), limit: int = 200, include_demo: bool = False):
    """Per-company breakdown (based on HR company)."""
    limit = min(max(int(limit), 1), 1000)

    resp_sub = (
        db.query(
            EmailCampaign.hr_id.label("hid"),
            func.count(EmailCampaign.id).label("responses"),
        )
        .filter(EmailCampaign.replied.is_(True))
        .group_by(EmailCampaign.hr_id)
        .subquery()
    )
    sent_sub = (
        db.query(
            EmailCampaign.hr_id.label("hid"),
            func.count(EmailCampaign.id).label("campaigns_sent"),
        )
        .filter(EmailCampaign.status.in_(_CAMPAIGN_DENOM_STATUSES))
        .group_by(EmailCampaign.hr_id)
        .subquery()
    )
    tot_sub = (
        db.query(
            EmailCampaign.hr_id.label("hid"),
            func.count(EmailCampaign.id).label("campaigns_total"),
        )
        .group_by(EmailCampaign.hr_id)
        .subquery()
    )

    q = (
        db.query(
            HRContact.company.label("company"),
            func.count(func.distinct(HRContact.id)).label("hrs"),
            func.coalesce(func.sum(tot_sub.c.campaigns_total), 0).label("campaigns_total"),
            func.coalesce(func.sum(sent_sub.c.campaigns_sent), 0).label("campaigns_sent"),
            func.coalesce(func.sum(resp_sub.c.responses), 0).label("responses"),
        )
        .select_from(HRContact)
        .outerjoin(tot_sub, tot_sub.c.hid == HRContact.id)
        .outerjoin(sent_sub, sent_sub.c.hid == HRContact.id)
        .outerjoin(resp_sub, resp_sub.c.hid == HRContact.id)
    )
    if not include_demo:
        q = q.filter(HRContact.is_demo.is_(False))
    rows = (
        q.group_by(HRContact.company)
        .order_by(desc(func.coalesce(func.sum(resp_sub.c.responses), 0)))
        .limit(limit)
        .all()
    )
    out = []
    for r in rows:
        sent = int(r.campaigns_sent or 0)
        resp = int(r.responses or 0)
        reply_rate = round(100 * resp / sent, 1) if sent > 0 else 0
        out.append(
            {
                "company": r.company,
                "hrs": int(r.hrs or 0),
                "campaigns_total": int(r.campaigns_total or 0),
                "campaigns_sent": sent,
                "responses": resp,
                "reply_rate": reply_rate,
            }
        )
    return out


@router.get("/hrs")
def analytics_by_hr(db: Session = Depends(get_db), limit: int = 200, include_demo: bool = False):
    """Per-HR breakdown."""
    limit = min(max(int(limit), 1), 1000)

    resp_sub = (
        db.query(
            EmailCampaign.hr_id.label("hid"),
            func.count(EmailCampaign.id).label("responses"),
        )
        .filter(EmailCampaign.replied.is_(True))
        .group_by(EmailCampaign.hr_id)
        .subquery()
    )
    sent_sub = (
        db.query(
            EmailCampaign.hr_id.label("hid"),
            func.count(EmailCampaign.id).label("campaigns_sent"),
        )
        .filter(EmailCampaign.status.in_(_CAMPAIGN_DENOM_STATUSES))
        .group_by(EmailCampaign.hr_id)
        .subquery()
    )
    tot_sub = (
        db.query(
            EmailCampaign.hr_id.label("hid"),
            func.count(EmailCampaign.id).label("campaigns_total"),
        )
        .group_by(EmailCampaign.hr_id)
        .subquery()
    )

    q = (
        db.query(
            HRContact.id.label("hr_id"),
            HRContact.name.label("hr_name"),
            HRContact.email.label("email"),
            HRContact.company.label("company"),
            HRContact.status.label("status"),
            HRContact.is_valid.label("is_valid"),
            func.coalesce(tot_sub.c.campaigns_total, 0).label("campaigns_total"),
            func.coalesce(sent_sub.c.campaigns_sent, 0).label("campaigns_sent"),
            func.coalesce(resp_sub.c.responses, 0).label("responses"),
        )
        .select_from(HRContact)
        .outerjoin(tot_sub, tot_sub.c.hid == HRContact.id)
        .outerjoin(sent_sub, sent_sub.c.hid == HRContact.id)
        .outerjoin(resp_sub, resp_sub.c.hid == HRContact.id)
    )
    if not include_demo:
        q = q.filter(HRContact.is_demo.is_(False))
    rows = q.order_by(desc(func.coalesce(resp_sub.c.responses, 0))).limit(limit).all()
    out = []
    for r in rows:
        sent = int(r.campaigns_sent or 0)
        resp = int(r.responses or 0)
        reply_rate = round(100 * resp / sent, 1) if sent > 0 else 0
        out.append(
            {
                "hr_id": str(r.hr_id),
                "hr_name": r.hr_name,
                "email": r.email,
                "company": r.company,
                "status": r.status,
                "is_valid": bool(r.is_valid) if r.is_valid is not None else True,
                "campaigns_total": int(r.campaigns_total or 0),
                "campaigns_sent": sent,
                "responses": resp,
                "reply_rate": reply_rate,
            }
        )
    return out


@router.get("/email-status")
def get_email_status(include_demo: bool = False, db: Session = Depends(get_db)):
    """
    Email delivery status based on EmailCampaign send outcomes.

    Smart filter: exclude invalid HRs so the success rate isn't distorted by bad contacts.
    """
    base_query = email_campaigns_scoped_to_hr(db, include_demo=include_demo)

    sent = (
        base_query.filter(EmailCampaign.status == "sent")
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )
    failed = (
        base_query.filter(EmailCampaign.status == "failed")
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )

    today_start = ensure_utc(
        datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    )
    today_sent = base_query.filter(
        EmailCampaign.status == "sent",
        EmailCampaign.sent_at >= today_start,
    ).with_entities(func.count(func.distinct(EmailCampaign.hr_id))).scalar() or 0

    # Match /analytics/summary: replied flag is the reply KPI (not merely non-null reply_text).
    total_replies = (
        base_query.filter(EmailCampaign.replied.is_(True))
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )

    sent_distinct_hr = (
        base_query.with_entities(
            func.count(func.distinct(case((EmailCampaign.status == "sent", EmailCampaign.hr_id))))
        ).scalar()
        or 0
    )

    unique_replies = (
        base_query.filter(EmailCampaign.replied.is_(True))
        .with_entities(func.count(func.distinct(EmailCampaign.hr_id)))
        .scalar()
        or 0
    )

    reply_rate = round(
        min(100.0, (100 * unique_replies / sent_distinct_hr) if sent_distinct_hr > 0 else 0.0),
        2,
    )
    
    total_attempted = sent + failed
    success_rate = (
        (sent / total_attempted * 100)
        if total_attempted > 0 else 0
    )
    success_rate = round(max(success_rate, 0), 2)

    bounced = base_query.filter(EmailCampaign.reply_status == "BOUNCED").count()
    blocked = base_query.filter(EmailCampaign.reply_status == "BLOCKED").count()
    hr_invalid_base = db.query(HRContact)
    if not include_demo:
        hr_invalid_base = hr_invalid_base.filter(HRContact.is_demo.is_(False))
    invalid_hr_contacts = hr_invalid_base.filter(HRContact.is_valid.is_(False)).count()

    total_bounced = bounced
    total_blocked = blocked
    blocked_hr_count = blocked
    bounce_rate = round(
        min(100.0, (100.0 * total_bounced / sent) if sent > 0 else 0.0),
        2,
    )

    return {
        "total": int(total_attempted),
        "sent": int(sent),
        "failed": int(failed),
        "today_sent": int(today_sent),
        "replied": int(total_replies),
        "total_replies": int(total_replies),
        "unique_replies": int(unique_replies),
        "success_rate": success_rate,
        "reply_rate": reply_rate,
        "total_bounced": int(total_bounced),
        "total_blocked": int(total_blocked),
        "bounce_rate": bounce_rate,
        "invalid_hr_contacts": int(invalid_hr_contacts),
        "blocked_hr_count": int(blocked_hr_count),
    }


def _norm_campaign_error(raw: str | None) -> str:
    t = (raw or "").strip()
    return t if t else "(no error text stored)"


@router.get("/failure-breakdown")
def get_failure_breakdown(
    include_demo: bool = False,
    limit_groups: int = Query(20, ge=1, le=50),
    recent_limit: int = Query(10, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """
    Debug failed sends: counts grouped by `email_campaigns.error` and recent failed rows.
    Same HR filters as /analytics/email-status.
    """
    base = (
        db.query(EmailCampaign)
        .join(HRContact, EmailCampaign.hr_id == HRContact.id)
    )
    if not include_demo:
        base = base.filter(HRContact.is_demo.is_(False))

    error_rows = (
        base.filter(EmailCampaign.status == "failed").with_entities(EmailCampaign.error).all()
    )
    total_failed = len(error_rows)
    counts = Counter(_norm_campaign_error(e[0]) for e in error_rows)
    top_errors = [{"error": msg, "count": c} for msg, c in counts.most_common(limit_groups)]

    event_ts = func.coalesce(EmailCampaign.sent_at, EmailCampaign.created_at)
    recent_q = (
        db.query(
            EmailCampaign.id,
            EmailCampaign.error,
            EmailCampaign.email_type,
            event_ts.label("event_ts"),
            Student.name.label("student_name"),
            HRContact.company.label("company"),
            HRContact.email.label("hr_email"),
        )
        .join(Student, EmailCampaign.student_id == Student.id)
        .join(HRContact, EmailCampaign.hr_id == HRContact.id)
        .filter(EmailCampaign.status == "failed")
    )
    if not include_demo:
        recent_q = recent_q.filter(HRContact.is_demo.is_(False))
    recent_rows = (
        recent_q.order_by(
            EmailCampaign.sent_at.desc().nullslast(),
            EmailCampaign.created_at.desc(),
        )
        .limit(recent_limit)
        .all()
    )
    recent_failed = [
        {
            "id": str(r.id),
            "student_name": r.student_name,
            "company": r.company,
            "hr_email": r.hr_email,
            "email_type": r.email_type,
            "failed_at": to_ist(r.event_ts),
            "error": _norm_campaign_error(r.error),
        }
        for r in recent_rows
    ]

    return {
        "total_failed": int(total_failed),
        "top_errors": top_errors,
        "recent_failed": recent_failed,
    }
