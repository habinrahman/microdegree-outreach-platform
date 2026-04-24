"""
Pre-created 4-step outreach sequence (INITIAL + 3 follow-ups).

Autonomous Sequencer v1:
- At assignment materialization, **all four** rows exist with **immutable** ``scheduled_at``
  (anchor day 0 / +7 / +14 / +21).
- Outages delay sends; they **do not** silently expire or slip the calendar — recovery sends
  catch up while ``scheduled_at <= now`` and gates allow.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import Assignment, EmailCampaign, HRContact, Student
from app.services.email_templates import pick_template, render_template

logger = logging.getLogger(__name__)

# (sequence_number, email_type, days from anchor at creation — fixed calendar)
_STEP_SPECS: tuple[tuple[int, str, int], ...] = (
    (1, "initial", 0),
    (2, "followup_1", 7),
    (3, "followup_2", 14),
    (4, "followup_3", 21),
)


def reschedule_followups_from_initial_sent(
    db: Session,
    *,
    student_id,
    hr_id,
    initial_sent_at: datetime,
) -> None:
    """
    Deprecated (v1 no-op).

    Historical behavior realigned FU ``scheduled_at`` to ``initial.sent_at + 7/14/21``.
    Sequencer v1 uses **immutable** anchor dates only; send-time must not mutate the calendar.
    """
    _ = (db, student_id, hr_id, initial_sent_at)


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _template_context(student: Student, hr: HRContact) -> dict[str, Any]:
    return {
        "hr_name": hr.name,
        "company": hr.company,
        "student_name": student.name,
        "skills": student.skills or "N/A",
        "experience": str(student.experience_years or 0),
    }


def ensure_four_step_campaign_rows(
    db: Session,
    assignment: Assignment,
    *,
    anchor: datetime | None = None,
    student: Student | None = None,
    hr: HRContact | None = None,
) -> list[EmailCampaign]:
    """
    Ensure exactly four EmailCampaign rows exist (sequences 1–4).
    Does not delete existing **sent** rows; creates only missing sequence slots.
    Does **not** rewrite ``scheduled_at`` on existing rows (idempotent / safe rerun).
    """
    student = student or db.query(Student).filter(Student.id == assignment.student_id).first()
    hr = hr or (
        db.query(HRContact)
        .filter(HRContact.id == assignment.hr_id, HRContact.is_valid.is_(True))
        .first()
    )
    if not student or not hr:
        return []

    if anchor is None:
        anchor = datetime.now(timezone.utc)
    anchor_naive = _naive_utc(anchor)

    existing = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == assignment.student_id, EmailCampaign.hr_id == assignment.hr_id)
        .order_by(EmailCampaign.sequence_number.asc())
        .all()
    )
    by_seq: dict[int, EmailCampaign] = {int(c.sequence_number): c for c in existing if c.sequence_number}

    ctx = _template_context(student, hr)
    created: list[EmailCampaign] = []

    for seq, email_type, day_offset in _STEP_SPECS:
        if seq in by_seq:
            continue
        tpl = pick_template(email_type)
        subject = render_template(tpl["subject"], ctx)
        body = render_template(tpl["body"], ctx)
        scheduled_at = anchor_naive + timedelta(days=day_offset)
        c = EmailCampaign(
            student_id=assignment.student_id,
            hr_id=assignment.hr_id,
            sequence_number=seq,
            email_type=email_type,
            scheduled_at=scheduled_at,
            status="pending",
            subject=subject,
            body=body,
        )
        db.add(c)
        created.append(c)

    if created:
        try:
            db.commit()
            for c in created:
                db.refresh(c)
        except Exception:
            db.rollback()
            logger.exception("ensure_four_step_campaign_rows: commit failed")
            raise

    out = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == assignment.student_id, EmailCampaign.hr_id == assignment.hr_id)
        .order_by(EmailCampaign.sequence_number.asc())
        .all()
    )
    return out
