"""
Post-cleanup checks for synthetic HR removal and basic referential integrity.

Use after ``cleanup_synthetic_hr_only`` / HR cascades to confirm:
- no remaining rows match synthetic patterns
- assignments / campaigns / email_campaigns have no dangling FKs (common orphan shapes)
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class SyntheticHRAuditResult:
    synthetic_hr_count: int
    orphan_assignments: int
    orphan_campaigns_missing_student: int
    email_campaigns_missing_student: int
    email_campaigns_missing_hr: int
    email_campaigns_broken_campaign_fk: int

    @property
    def ok(self) -> bool:
        return (
            self.synthetic_hr_count == 0
            and self.orphan_assignments == 0
            and self.orphan_campaigns_missing_student == 0
            and self.email_campaigns_missing_student == 0
            and self.email_campaigns_missing_hr == 0
            and self.email_campaigns_broken_campaign_fk == 0
        )


def count_synthetic_hr_contacts(db: Session) -> int:
    from app.models import HRContact
    from app.services.synthetic_hr_cleanup import is_synthetic_hr

    n = 0
    for h in db.query(HRContact).all():
        if is_synthetic_hr(email=h.email, name=h.name, company=h.company):
            n += 1
    return n


def count_orphan_assignments(db: Session) -> int:
    """Assignments whose student or HR row no longer exists."""
    from app.models import Assignment, HRContact, Student

    return (
        db.query(Assignment)
        .outerjoin(Student, Assignment.student_id == Student.id)
        .outerjoin(HRContact, Assignment.hr_id == HRContact.id)
        .filter(or_(Student.id.is_(None), HRContact.id.is_(None)))
        .count()
    )


def count_orphan_campaigns_missing_student(db: Session) -> int:
    """``Campaign`` rows pointing at a deleted ``students`` row."""
    from app.models import Campaign, Student

    return (
        db.query(Campaign)
        .outerjoin(Student, Campaign.student_id == Student.id)
        .filter(Student.id.is_(None))
        .count()
    )


def count_email_campaigns_missing_student_or_hr(db: Session) -> tuple[int, int]:
    """Returns (missing_student, missing_hr) for ``email_campaigns``."""
    from app.models import EmailCampaign, HRContact, Student

    ms = (
        db.query(EmailCampaign)
        .outerjoin(Student, EmailCampaign.student_id == Student.id)
        .filter(Student.id.is_(None))
        .count()
    )
    mh = (
        db.query(EmailCampaign)
        .outerjoin(HRContact, EmailCampaign.hr_id == HRContact.id)
        .filter(HRContact.id.is_(None))
        .count()
    )
    return ms, mh


def count_email_campaigns_broken_campaign_fk(db: Session) -> int:
    """``email_campaigns.campaign_id`` set but no matching ``campaigns`` row."""
    from app.models import Campaign, EmailCampaign

    return (
        db.query(EmailCampaign)
        .outerjoin(Campaign, EmailCampaign.campaign_id == Campaign.id)
        .filter(EmailCampaign.campaign_id.isnot(None), Campaign.id.is_(None))
        .count()
    )


def run_synthetic_hr_audit(db: Session) -> SyntheticHRAuditResult:
    ms, mh = count_email_campaigns_missing_student_or_hr(db)
    return SyntheticHRAuditResult(
        synthetic_hr_count=count_synthetic_hr_contacts(db),
        orphan_assignments=count_orphan_assignments(db),
        orphan_campaigns_missing_student=count_orphan_campaigns_missing_student(db),
        email_campaigns_missing_student=ms,
        email_campaigns_missing_hr=mh,
        email_campaigns_broken_campaign_fk=count_email_campaigns_broken_campaign_fk(db),
    )
