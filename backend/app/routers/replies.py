"""Read-only API: replied email campaigns (for Replies dashboard)."""

import logging
from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import require_api_key
from pydantic import BaseModel, Field
from sqlalchemy import and_, not_, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.email_campaign import EmailCampaign
from app.models.hr_contact import HRContact
from app.models.student import Student
from app.services.inbox_reply_type import FILTER_TO_CANONICAL, canonical_reply_type_for_api
from app.services.reply_normalization import (
    AUTO_REPLY,
    BOUNCE,
    INTERESTED,
    INTERVIEW,
    OTHER,
    OOO,
    REJECTED,
    UNKNOWN,
)
from app.services.replies_backfill import backfill_replies_for_db

router = APIRouter(
    prefix="/replies",
    tags=["replies"],
    dependencies=[Depends(require_api_key)],
)
logger = logging.getLogger(__name__)

_VALID_REPLY_TYPE_FILTERS = frozenset(FILTER_TO_CANONICAL.keys())

_VALID_WORKFLOW = frozenset({"OPEN", "IN_PROGRESS", "CLOSED"})


class ReplyPatchBody(BaseModel):
    status: Optional[str] = Field(None, description="OPEN | IN_PROGRESS | CLOSED")
    notes: Optional[str] = Field(None, max_length=20000)


def _dt_iso(value):
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _reply_bucket_sql(bucket_lower: str):
    """SQL predicate for filter param (lowercase) vs canonical + legacy rows."""
    canon = FILTER_TO_CANONICAL.get(bucket_lower)
    if canon is None:
        return None
    ec = EmailCampaign
    if canon == BOUNCE:
        return or_(
            ec.reply_type.in_(("BOUNCE", "bounce")),
            ec.reply_status == BOUNCE,
            and_(
                ec.reply_type.is_(None),
                ec.reply_status.in_(("BOUNCED", "BLOCKED", "TEMP_FAIL")),
            ),
        )
    if canon == AUTO_REPLY:
        return or_(
            ec.reply_type.in_(("AUTO_REPLY", "auto_reply")),
            and_(ec.reply_type.is_(None), ec.reply_status == "AUTO_REPLY"),
        )
    if canon == INTERVIEW:
        return or_(
            ec.reply_type.in_(("INTERVIEW", "interview")),
            and_(ec.reply_type.is_(None), ec.reply_status == "INTERVIEW"),
        )
    if canon == INTERESTED:
        return or_(
            ec.reply_type.in_(("INTERESTED", "interested")),
            and_(ec.reply_type.is_(None), ec.reply_status == "INTERESTED"),
        )
    if canon == REJECTED:
        return or_(
            ec.reply_type.in_(("REJECTED", "rejected", "not_interested")),
            and_(
                ec.reply_type.is_(None),
                ec.reply_status.in_(("REJECTED", "NOT_INTERESTED")),
            ),
        )
    if canon == OOO:
        return or_(
            ec.reply_type.in_(("OOO", "ooo")),
            and_(ec.reply_type.is_(None), ec.reply_status == "OOO"),
        )
    if canon == UNKNOWN:
        return or_(
            ec.reply_type.in_(("UNKNOWN", "unknown")),
            and_(ec.reply_type.is_(None), ec.reply_status == "UNKNOWN"),
        )
    if canon == OTHER:
        lower_parts = (
            "bounce",
            "auto_reply",
            "interview",
            "interested",
            "rejected",
            "ooo",
            "unknown",
        )
        return and_(*[not_(_reply_bucket_sql(p)) for p in lower_parts])
    return None


@router.get("")
def list_replies(
    student_id: UUID | None = Query(None),
    reply_type: str | None = Query(
        None,
        description="Filter: interested | interview | rejected | auto_reply | bounce | ooo | unknown | other (case-insensitive). Omit for all.",
    ),
    include_demo: bool = False,
    db: Session = Depends(get_db),
):
    q = (
        db.query(EmailCampaign, Student, HRContact)
        .select_from(EmailCampaign)
        .join(Student, EmailCampaign.student_id == Student.id)
        .join(HRContact, EmailCampaign.hr_id == HRContact.id)
        .filter(EmailCampaign.reply_text.isnot(None))
    )
    if not include_demo:
        q = q.filter(Student.is_demo.is_(False), HRContact.is_demo.is_(False))
    if student_id is not None:
        q = q.filter(EmailCampaign.student_id == student_id)

    rf = (reply_type or "").strip().lower()
    if rf in _VALID_REPLY_TYPE_FILTERS:
        clause = _reply_bucket_sql(rf)
        if clause is not None:
            q = q.filter(clause)

    q = q.order_by(
        EmailCampaign.reply_detected_at.desc().nullslast(),
        EmailCampaign.created_at.desc(),
    ).limit(500)

    try:
        logger.info("Fetching replies...")
        rows = q.all()
        out = []
        for ec, st, hr in rows:
            reply_time = ec.reply_detected_at or ec.replied_at
            rt = canonical_reply_type_for_api(ec)
            wf = getattr(ec, "reply_workflow_status", None) or "OPEN"
            out.append(
                {
                    "reply_type": rt,
                    "reply_status": ec.reply_status or rt,
                    "reply_message": ec.reply_text,
                    "student_name": st.name,
                    "company": hr.company,
                    "hr_email": hr.email,
                    "time": _dt_iso(reply_time),
                    "created_at": _dt_iso(ec.created_at),
                    "campaign_id": str(ec.id),
                    "student_id": str(st.id),
                    "subject": ec.subject,
                    "email_type": ec.email_type,
                    "reply_from": ec.reply_from,
                    "status": wf,
                    "notes": getattr(ec, "reply_admin_notes", None),
                }
            )
        logger.info("Replies fetched: %s", len(out))
        return out
    except Exception:
        logger.exception("Error in list_replies")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("/{campaign_id}")
def patch_reply_triage(
    campaign_id: UUID,
    body: ReplyPatchBody,
    db: Session = Depends(get_db),
):
    """Update workflow status and/or admin notes for a replied campaign row."""
    ec = db.query(EmailCampaign).filter(EmailCampaign.id == campaign_id).first()
    if not ec:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if body.status is not None:
        u = body.status.strip().upper()
        if u not in _VALID_WORKFLOW:
            raise HTTPException(status_code=400, detail="status must be OPEN, IN_PROGRESS, or CLOSED")
        ec.reply_workflow_status = u
    if body.notes is not None:
        ec.reply_admin_notes = body.notes
    db.commit()
    db.refresh(ec)
    st = db.query(Student).filter(Student.id == ec.student_id).first()
    hr = db.query(HRContact).filter(HRContact.id == ec.hr_id).first()
    rt = canonical_reply_type_for_api(ec)
    reply_time = ec.reply_detected_at or ec.replied_at
    return {
        "reply_type": rt,
        "reply_message": ec.reply_text,
        "student_name": st.name if st else None,
        "company": hr.company if hr else None,
        "hr_email": hr.email if hr else None,
        "time": _dt_iso(reply_time),
        "campaign_id": str(ec.id),
        "student_id": str(st.id) if st else None,
        "status": getattr(ec, "reply_workflow_status", None) or "OPEN",
        "notes": getattr(ec, "reply_admin_notes", None),
    }


@router.post("/backfill")
def backfill_old_replies(db: Session = Depends(get_db)):
    """Scan Gmail (last 14d) per OAuth-connected student; fill reply_text where null (thread match)."""
    result = backfill_replies_for_db(db)
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("error", "Backfill failed"))
    return result
