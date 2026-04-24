"""Outreach API – send emails, run batch, logs, stats (same setup as before).

Includes manual outreach endpoint to add HR details and send immediately.
"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.auth import require_api_key
from app.database import get_db
from datetime import datetime, timedelta, timezone
from app.models import Student, HRContact, Assignment, Response
from app.models.email_campaign import EmailCampaign
from app.services.outreach_service import (
    send_one,
    send_selected_outreach,
    normalize_template_label,
)
from app.services.campaign_generator import generate_campaigns_for_assignment
from app.utils.datetime_utils import ensure_utc, to_ist
from app.services.campaign_lifecycle import assert_legal_email_campaign_transition

router = APIRouter(
    prefix="/outreach",
    tags=["outreach"],
    dependencies=[Depends(require_api_key)],
)


def _clear_response_fks_for_pending_campaigns(db: Session, student_id: UUID, hr_id: UUID) -> None:
    """responses.source_campaign_id FK blocks deleting non-sent campaigns; clear before regenerate."""
    pending_ids = [
        row[0]
        for row in db.query(EmailCampaign.id)
        .filter(
            EmailCampaign.student_id == student_id,
            EmailCampaign.hr_id == hr_id,
            EmailCampaign.status != "sent",
        )
        .all()
    ]
    if not pending_ids:
        return
    db.query(Response).filter(Response.source_campaign_id.in_(pending_ids)).update(
        {Response.source_campaign_id: None},
        synchronize_session=False,
    )


class SendOutreachBody(BaseModel):
    student_id: UUID
    hr_id: UUID | None = None
    hr_email: str | None = Field(None, max_length=512)
    template_label: str | None = Field(None, max_length=128)
    subject: str | None = Field(None, max_length=2048)
    body: str | None = Field(None, max_length=1_000_000)

    @model_validator(mode="after")
    def require_hr_target(self) -> "SendOutreachBody":
        has_id = self.hr_id is not None
        has_em = self.hr_email is not None and str(self.hr_email).strip() != ""
        if not has_id and not has_em:
            raise ValueError("Either hr_id or hr_email is required")
        return self


def resolve_outreach_hr_id(db: Session, body: SendOutreachBody) -> UUID:
    """Resolve HR from hr_id or hr_email (case-insensitive email match)."""
    if body.hr_id is not None:
        hr = db.query(HRContact).filter(HRContact.id == body.hr_id).first()
        if not hr:
            raise HTTPException(status_code=404, detail="HR not found")
        if body.hr_email and str(body.hr_email).strip():
            if hr.email.strip().lower() != str(body.hr_email).strip().lower():
                raise HTTPException(status_code=400, detail="hr_id does not match hr_email")
        return body.hr_id
    em = str(body.hr_email).strip().lower()
    hr = db.query(HRContact).filter(func.lower(HRContact.email) == em).first()
    if not hr:
        raise HTTPException(status_code=404, detail="HR not found for this email")
    return hr.id


class SendSelectedBody(BaseModel):
    """Primary controlled outreach: send initial email to multiple HRs for one student."""

    student_id: UUID
    hr_ids: list[UUID]
    subject: str | None = None
    body: str | None = None
    template_label: str | None = Field(None, max_length=128)


class ManualOutreachBody(BaseModel):
    student_id: UUID
    company: str
    hr_name: str
    email: str
    domain: str | None = None
    subject: str | None = None
    body: str | None = None
    include_resume: bool = True
    template_label: str | None = Field(None, max_length=128)


class ManualScheduleSelectedBody(BaseModel):
    student_id: UUID
    hr_ids: list[UUID]
    subject: str
    body: str
    template_label: str | None = Field(None, max_length=128)


@router.post("/send")
def send_outreach(
    body: SendOutreachBody,
    db: Session = Depends(get_db),
):
    """Send one outreach email for this student–HR pair (must be an active assignment)."""
    hr_uuid = resolve_outreach_hr_id(db, body)
    result = send_one(
        db,
        body.student_id,
        hr_uuid,
        template_label=body.template_label,
        subject=body.subject,
        body=body.body,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message", "Send failed"))
    return {"message": "Email sent successfully"}


@router.post("/send_selected")
def send_selected_endpoint(body: SendSelectedBody, db: Session = Depends(get_db)):
    """
    Queue initial campaigns for the background scheduler (no immediate SMTP send).
    Creates pending EmailCampaign rows when needed; scheduler sends and sets status to sent.
    """
    student = db.query(Student).filter(Student.id == body.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    if student.status != "active":
        raise HTTPException(status_code=400, detail="Student is inactive")
    if not student.app_password:
        raise HTTPException(
            status_code=400,
            detail="Student has no app_password configured for SMTP",
        )
    return send_selected_outreach(
        db,
        student,
        body.hr_ids,
        subject=body.subject,
        body=body.body,
        template_label=body.template_label,
    )


@router.post("/manual_send")
def manual_send_outreach(body: ManualOutreachBody, db: Session = Depends(get_db)):
    """Manual: create/find HR by email, ensure active assignment.
    Schedules initial campaign for the scheduler instead of sending immediately."""
    student = db.query(Student).filter(Student.id == body.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    if student.status != "active":
        raise HTTPException(status_code=400, detail="Student is inactive")

    email = (body.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Missing HR email")

    hr = (
        db.query(HRContact)
        .filter(HRContact.email == email, HRContact.is_valid.is_(True))
        .first()
    )
    if hr is None:
        blocked = (
            db.query(HRContact)
            .filter(HRContact.email == email, HRContact.is_valid.is_(False))
            .first()
        )
        if blocked is not None:
            raise HTTPException(
                status_code=400,
                detail="HR contact is invalid (delivery failed previously)",
            )
    created_hr = False
    if not hr:
        hr = HRContact(
            name=(body.hr_name or "").strip(),
            company=(body.company or "").strip(),
            email=email,
            domain=(body.domain or None),
            status="active",
            is_valid=True,
        )
        if not hr.name or not hr.company:
            raise HTTPException(status_code=400, detail="Missing HR name/company")
        db.add(hr)
        db.commit()
        db.refresh(hr)
        created_hr = True

    # ensure assignment exists
    assignment = (
        db.query(Assignment)
        .filter(
            Assignment.student_id == student.id,
            Assignment.hr_id == hr.id,
        )
        .first()
    )
    if not assignment:
        assignment = Assignment(student_id=student.id, hr_id=hr.id, status="active")
        db.add(assignment)
        db.commit()
        db.refresh(assignment)

    existing = (
        db.query(EmailCampaign)
        .filter(
            EmailCampaign.student_id == student.id,
            EmailCampaign.hr_id == hr.id,
            EmailCampaign.sequence_number == 1,
            EmailCampaign.status == "sent",
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Initial email already sent to this HR",
        )
    # Queue only (do not send now); scheduler will send later.
    selected_hrs = [hr]
    base_time = ensure_utc(datetime.now(timezone.utc))
    queued = 0
    lab = normalize_template_label(body.template_label)
    for index, queued_hr in enumerate(selected_hrs):
        scheduled_time = base_time + timedelta(minutes=5 * index)
        # Pre-create four EmailCampaign rows (INITIAL + 3 follow-ups) with deterministic cadence.
        _clear_response_fks_for_pending_campaigns(db, student.id, queued_hr.id)
        db.query(EmailCampaign).filter(
            EmailCampaign.student_id == student.id,
            EmailCampaign.hr_id == queued_hr.id,
            EmailCampaign.status != "sent",
        ).delete(synchronize_session=False)
        db.commit()

        generate_campaigns_for_assignment(db, assignment, anchor=scheduled_time)

        initial = (
            db.query(EmailCampaign)
            .filter(
                EmailCampaign.student_id == student.id,
                EmailCampaign.hr_id == queued_hr.id,
                EmailCampaign.sequence_number == 1,
            )
            .order_by(EmailCampaign.created_at.desc())
            .first()
        )
        if initial:
            initial.subject = body.subject
            initial.body = body.body
            assert_legal_email_campaign_transition(
                initial.status, "scheduled", context="outreach/schedule-selected"
            )
            initial.status = "scheduled"
            initial.scheduled_at = scheduled_time
            if lab is not None:
                initial.template_label = lab[:128] if len(lab) > 128 else lab

        queued += 1
    db.commit()

    return {
        "message": "Email scheduled successfully",
        "status": "scheduled",
        "hr_id": str(hr.id),
        "created_hr": created_hr,
        "campaigns_created": queued > 0,
    }


@router.post("/manual-send")
def manual_send_selected_outreach(
    body: ManualScheduleSelectedBody,
    db: Session = Depends(get_db),
):
    """Queue initial campaigns for selected HRs using user-provided subject/body."""
    student = db.query(Student).filter(Student.id == body.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    if student.status != "active":
        raise HTTPException(status_code=400, detail="Student is inactive")

    subject = (body.subject or "").strip()
    msg_body = (body.body or "").strip()
    if not subject or not msg_body:
        raise HTTPException(status_code=400, detail="Subject and body are required")

    seen: set[UUID] = set()
    ordered_unique: list[UUID] = []
    for hid in body.hr_ids:
        if hid not in seen:
            seen.add(hid)
            ordered_unique.append(hid)

    base_time = ensure_utc(datetime.now(timezone.utc))
    lab = normalize_template_label(body.template_label)
    queued = 0
    skipped = 0
    errors: list[dict] = []

    for index, hr_id in enumerate(ordered_unique):
        hr = (
            db.query(HRContact)
            .filter(HRContact.id == hr_id, HRContact.is_valid.is_(True))
            .first()
        )
        if not hr:
            errors.append({"hr_id": str(hr_id), "message": "HR not found or invalid"})
            continue

        assignment = (
            db.query(Assignment)
            .filter(
                Assignment.student_id == student.id,
                Assignment.hr_id == hr.id,
                Assignment.status == "active",
            )
            .first()
        )
        if not assignment:
            assignment = Assignment(student_id=student.id, hr_id=hr.id, status="active")
            db.add(assignment)
            db.flush()

        existing = (
            db.query(EmailCampaign)
            .filter(
                EmailCampaign.student_id == student.id,
                EmailCampaign.hr_id == hr.id,
                EmailCampaign.sequence_number == 1,
                EmailCampaign.status == "sent",
            )
            .first()
        )
        if existing:
            skipped += 1
            continue

        scheduled_time = base_time + timedelta(seconds=30 * index)

        # Pre-create four EmailCampaign rows (INITIAL + 3 follow-ups) with deterministic cadence.
        _clear_response_fks_for_pending_campaigns(db, student.id, hr.id)
        db.query(EmailCampaign).filter(
            EmailCampaign.student_id == student.id,
            EmailCampaign.hr_id == hr.id,
            EmailCampaign.status != "sent",
        ).delete(synchronize_session=False)
        db.commit()

        generate_campaigns_for_assignment(db, assignment, anchor=scheduled_time)

        initial = (
            db.query(EmailCampaign)
            .filter(
                EmailCampaign.student_id == student.id,
                EmailCampaign.hr_id == hr.id,
                EmailCampaign.sequence_number == 1,
            )
            .order_by(EmailCampaign.created_at.desc())
            .first()
        )
        if initial:
            initial.subject = subject
            initial.body = msg_body
            assert_legal_email_campaign_transition(
                initial.status, "scheduled", context="outreach/manual-send"
            )
            initial.status = "scheduled"
            initial.scheduled_at = scheduled_time
            if lab is not None:
                initial.template_label = lab[:128] if len(lab) > 128 else lab

        queued += 1

    db.commit()
    return {
        "message": "Emails scheduled successfully",
        "summary": {
            "queued": queued,
            "skipped": skipped,
            "errors": len(errors),
        },
        "errors": errors,
    }


@router.post("/start")
def start_outreach(db: Session = Depends(get_db)):
    """
    DISABLED: unsafe bulk send to all active assignments.

    Original behavior (commented, do not delete):
        results = run_outreach(db)
        return {"message": "Outreach completed", "emails_sent": results}

    Use controlled sending instead: POST /outreach/send (one pair) or POST /outreach/manual_send.
    """
    raise HTTPException(
        status_code=403,
        detail="Bulk sending is disabled. Use controlled selection instead.",
    )
    # results = run_outreach(db)
    # return {
    #     "message": "Outreach completed",
    #     "emails_sent": results,
    # }


@router.get("/logs")
def get_logs(
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    include_demo: bool = False,
):
    """Recent campaign outcomes ordered by latest sent_at (source of truth: email_campaigns)."""
    assert EmailCampaign is not None
    q = (
        db.query(
            EmailCampaign.id,
            EmailCampaign.student_id,
            EmailCampaign.hr_id,
            EmailCampaign.status,
            EmailCampaign.error,
            EmailCampaign.email_type,
            EmailCampaign.sent_at,
            Student.name.label("student_name"),
            HRContact.company.label("company"),
            HRContact.email.label("hr_email"),
        )
        .join(Student, EmailCampaign.student_id == Student.id)
        .join(HRContact, EmailCampaign.hr_id == HRContact.id)
        .filter(HRContact.status != "invalid")
    )
    if not include_demo:
        q = q.filter(HRContact.is_demo.is_(False))
    rows = (
        q.order_by(EmailCampaign.sent_at.desc().nullslast(), EmailCampaign.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(row.id),
            "campaign_id": str(row.id),
            "student_id": (str(row.student_id) if row.student_id else None),
            "hr_id": (str(row.hr_id) if row.hr_id else None),
            "student_name": row.student_name,
            "company": row.company,
            "hr_email": row.hr_email,
            "status": row.status,
            "email_type": row.email_type,
            "sent_at": to_ist(row.sent_at),
            "sent_time": to_ist(row.sent_at),
            "error": row.error,
        }
        for row in rows
    ]


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    """Return counts: students, HRs, emails_sent, success_rate."""
    students_count = db.query(func.count(Student.id)).scalar() or 0
    hrs_count = db.query(func.count(HRContact.id)).scalar() or 0
    emails_sent = (
        db.query(func.count(EmailCampaign.id))
        .filter(EmailCampaign.status == "sent")
        .scalar()
        or 0
    )
    emails_failed = (
        db.query(func.count(EmailCampaign.id))
        .filter(EmailCampaign.status == "failed")
        .scalar()
        or 0
    )
    total = emails_sent + emails_failed
    success_rate = (100 * emails_sent / total) if total > 0 else 0
    return {
        "students": students_count,
        "hrs": hrs_count,
        "emails_sent": emails_sent,
        "success_rate": round(success_rate, 1),
    }
