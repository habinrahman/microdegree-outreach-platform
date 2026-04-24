"""Shared HR listing queries (e.g. exclude HRs who already received the first campaign email)."""
from uuid import UUID

from sqlalchemy import exists, or_
from sqlalchemy.orm import Session

from app.models import HRContact, EmailCampaign, BlockedHR


def query_hrs_without_initial_sent(db: Session, student_id: UUID | None = None):
    """
    HRs for which there is NO email_campaigns row with:
    - same hr_id
    - sequence_number == 1 (first step in the 4-email sequence)
    - status == 'sent'

    If ``student_id`` is set, only that student's sends count (per-student controlled outreach).
    If ``student_id`` is None, any student's sent initial hides the HR (legacy global list).

    Uses NOT EXISTS for efficiency (single subquery per list, index-friendly on hr_id).
    """
    conditions = [
        EmailCampaign.hr_id == HRContact.id,
        EmailCampaign.sequence_number == 1,
        EmailCampaign.status == "sent",
    ]
    if student_id is not None:
        conditions.append(EmailCampaign.student_id == student_id)
    initial_already_sent = exists().where(*conditions)
    q = (
        db.query(HRContact)
        .filter(HRContact.is_valid.is_(True))
        .filter(~initial_already_sent)
        .filter(or_(HRContact.status.is_(None), HRContact.status != "invalid"))
        .filter(~HRContact.email.in_(db.query(BlockedHR.email)))
    )
    if hasattr(HRContact, "is_fixture_test_data"):
        q = q.filter(HRContact.is_fixture_test_data.is_(False))
    return q
