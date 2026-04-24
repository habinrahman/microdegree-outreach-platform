"""List and manage email campaigns (Part 2)."""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_api_key
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_

from app.database import get_db
from app.models import HRContact, Student
from app.models.email_campaign import EmailCampaign
from app.schemas.email_campaign import CampaignBulkPatchBody, CampaignUpdateBody
from app.schemas.campaign_lifecycle import LifecycleVisualizationResponse
from app.services.campaign_lifecycle import (
    assert_legal_email_campaign_transition,
    build_lifecycle_visualization_payload,
)
from app.utils.datetime_utils import to_ist

router = APIRouter(
    prefix="/campaigns",
    tags=["campaigns"],
    dependencies=[Depends(require_api_key)],
)
logger = logging.getLogger(__name__)


def _campaign_to_dict(
    c: EmailCampaign,
    hr: HRContact | None = None,
    student: Student | None = None,
) -> dict:
    return {
        "id": str(c.id),
        "campaign_id": str(c.campaign_id) if c.campaign_id else None,
        "student_id": str(c.student_id),
        "student_name": student.name if student else None,
        "hr_id": str(c.hr_id),
        "company": hr.company if hr else None,
        "hr_email": hr.email if hr else None,
        "sequence_number": c.sequence_number,
        "email_type": c.email_type,
        "scheduled_at": to_ist(c.scheduled_at),
        "sent_at": to_ist(c.sent_at),
        "created_at": to_ist(c.created_at),
        "status": c.status,
        "subject": c.subject,
        "body": c.body,
        "template_label": c.template_label,
        "thread_id": c.thread_id,
        "message_id": c.message_id,
        "replied": bool(c.replied),
        "replied_at": to_ist(c.replied_at),
        "reply_type": c.reply_type,
        "reply_snippet": c.reply_snippet,
        "reply_status": c.reply_status,
        "delivery_status": c.delivery_status,
        "error": c.error,
        "reply_workflow_status": getattr(c, "reply_workflow_status", None),
        "reply_admin_notes": getattr(c, "reply_admin_notes", None),
    }


@router.get("/lifecycle", response_model=LifecycleVisualizationResponse)
def get_campaign_lifecycle_visualization(db: Session = Depends(get_db)):
    """
    Read-only: lifecycle transition model (edges, terminals, self-loops) plus live counts of
    ``email_campaigns`` rows per ``status``. Includes Mermaid ``stateDiagram-v2`` source for UI.
    """
    return LifecycleVisualizationResponse(**build_lifecycle_visualization_payload(db))


@router.get("")
def list_campaigns(
    student_id: UUID | None = None,
    hr_id: UUID | None = None,
    status: str | None = None,
    email_type: str | None = None,
    reply_status: str | None = None,
    delivery_status: str | None = None,
    campaign_type: str | None = None,
    template_label: str | None = None,
    is_valid_hr: bool | None = None,
    skip: int = 0,
    limit: int = 1000,
    include_demo: bool = False,
    db: Session = Depends(get_db),
):
    """List scheduled/sent campaigns with optional filters."""
    q = (
        db.query(EmailCampaign, HRContact, Student)
        .join(HRContact, EmailCampaign.hr_id == HRContact.id)
        .join(Student, EmailCampaign.student_id == Student.id)
    )
    if not include_demo:
        q = q.filter(HRContact.is_demo.is_(False))
    q = q.order_by(desc(EmailCampaign.sent_at).nullslast(), desc(EmailCampaign.created_at))
    q = q.filter(
        EmailCampaign.status.in_(
            ("pending", "scheduled", "processing", "sent", "failed", "expired", "replied")
        )
    )
    if student_id is not None:
        q = q.filter(EmailCampaign.student_id == student_id)
    if hr_id is not None:
        q = q.filter(EmailCampaign.hr_id == hr_id)
    if status is not None:
        q = q.filter(EmailCampaign.status == status)
    if email_type is not None:
        q = q.filter(EmailCampaign.email_type == email_type)
    if reply_status is not None:
        q = q.filter(EmailCampaign.reply_status == reply_status)
    if delivery_status is not None:
        ds = (delivery_status or "").strip().upper()
        if ds == "SENT":
            q = q.filter(
                or_(
                    EmailCampaign.delivery_status.is_(None),
                    EmailCampaign.delivery_status != "FAILED",
                )
            )
        else:
            q = q.filter(EmailCampaign.delivery_status == delivery_status)
    if campaign_type is not None:
        ct = (campaign_type or "").strip().lower()
        if ct == "followup":
            q = q.filter(
                EmailCampaign.email_type.in_(("followup_1", "followup_2", "followup_3"))
            )
        else:
            q = q.filter(EmailCampaign.email_type == campaign_type)
    if template_label is not None and str(template_label).strip():
        q = q.filter(EmailCampaign.template_label == str(template_label).strip())
    if is_valid_hr is not None:
        q = q.filter(HRContact.is_valid.is_(is_valid_hr))
    try:
        logger.info("Fetching campaigns...")
        rows = q.offset(skip).limit(max(1, min(int(limit), 1000))).all()
        out = [_campaign_to_dict(c, hr, st) for c, hr, st in rows]
        logger.info("Campaigns fetched: %s", len(out))
        return out
    except Exception:
        logger.exception("Error in list_campaigns")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("")
def patch_campaigns_bulk(
    body: CampaignBulkPatchBody,
    db: Session = Depends(get_db),
):
    """Bulk pause or cancel campaigns still in queue (pending, scheduled, or processing)."""
    target = (body.status or "").strip().lower()
    if target not in ("paused", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail="status must be 'paused' or 'cancelled'",
        )
    updated = 0
    for cid in body.campaign_ids:
        c = db.query(EmailCampaign).filter(EmailCampaign.id == cid).first()
        if not c:
            continue
        if c.status not in ("pending", "scheduled", "processing"):
            continue
        new_st = "paused" if target == "paused" else "cancelled"
        assert_legal_email_campaign_transition(c.status, new_st, context="campaigns/bulk-patch")
        c.status = new_st
        updated += 1
    db.commit()
    return {"updated": updated, "status": target}


@router.put("/{campaign_id}")
def update_campaign(
    campaign_id: UUID,
    payload: CampaignUpdateBody,
    db: Session = Depends(get_db),
):
    """
    Update subject/body for a campaign that is still scheduled.
    Does not change sent_at, sequence_number, hr_id, or student_id.
    """
    c = db.query(EmailCampaign).filter(EmailCampaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.status not in ("scheduled", "pending"):
        raise HTTPException(
            status_code=400,
            detail="Only pending or scheduled campaigns can be edited; sent emails cannot be changed.",
        )
    subj = payload.subject.strip()
    if not subj:
        raise HTTPException(status_code=400, detail="Subject cannot be empty")
    c.subject = subj
    c.body = payload.body
    db.commit()
    db.refresh(c)
    hr = db.query(HRContact).filter(HRContact.id == c.hr_id).first()
    st = db.query(Student).filter(Student.id == c.student_id).first()
    return _campaign_to_dict(c, hr, st)
