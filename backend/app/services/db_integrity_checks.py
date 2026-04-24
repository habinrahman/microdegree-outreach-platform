"""Read-only structural integrity checks for nightly verification and admin health."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models import Assignment, EmailCampaign, HRContact, Response, Student


@dataclass(frozen=True)
class IntegrityCheckResult:
    name: str
    ok: bool
    count: int
    detail: str | None = None


def _count_orphan_assignments_missing_student(db: Session) -> int:
    return (
        db.query(Assignment.id)
        .outerjoin(Student, Assignment.student_id == Student.id)
        .filter(Student.id.is_(None))
        .count()
    )


def _count_orphan_assignments_missing_hr(db: Session) -> int:
    return (
        db.query(Assignment.id)
        .outerjoin(HRContact, Assignment.hr_id == HRContact.id)
        .filter(HRContact.id.is_(None))
        .count()
    )


def _count_orphan_campaigns_missing_student(db: Session) -> int:
    return (
        db.query(EmailCampaign.id)
        .outerjoin(Student, EmailCampaign.student_id == Student.id)
        .filter(Student.id.is_(None))
        .count()
    )


def _count_orphan_campaigns_missing_hr(db: Session) -> int:
    return (
        db.query(EmailCampaign.id)
        .outerjoin(HRContact, EmailCampaign.hr_id == HRContact.id)
        .filter(HRContact.id.is_(None))
        .count()
    )


def _count_orphan_responses_missing_student(db: Session) -> int:
    return (
        db.query(Response.id)
        .outerjoin(Student, Response.student_id == Student.id)
        .filter(Student.id.is_(None))
        .count()
    )


def _count_orphan_responses_missing_hr(db: Session) -> int:
    return (
        db.query(Response.id)
        .outerjoin(HRContact, Response.hr_id == HRContact.id)
        .filter(HRContact.id.is_(None))
        .count()
    )


def _count_orphan_responses_missing_campaign(db: Session) -> int:
    """Responses pointing at a deleted email_campaign row (optional FK)."""
    return (
        db.query(Response.id)
        .filter(Response.source_campaign_id.isnot(None))
        .outerjoin(EmailCampaign, Response.source_campaign_id == EmailCampaign.id)
        .filter(EmailCampaign.id.is_(None))
        .count()
    )


def run_corruption_integrity_checks(db: Session) -> dict[str, Any]:
    """
    Logical FK / orphan checks (works even when SQLite PRAGMA foreign_keys is off).
    """
    specs: list[tuple[str, callable]] = [
        ("orphan_assignments_missing_student", _count_orphan_assignments_missing_student),
        ("orphan_assignments_missing_hr", _count_orphan_assignments_missing_hr),
        ("orphan_email_campaigns_missing_student", _count_orphan_campaigns_missing_student),
        ("orphan_email_campaigns_missing_hr", _count_orphan_campaigns_missing_hr),
        ("orphan_responses_missing_student", _count_orphan_responses_missing_student),
        ("orphan_responses_missing_hr", _count_orphan_responses_missing_hr),
        ("orphan_responses_missing_source_campaign", _count_orphan_responses_missing_campaign),
    ]
    checks: list[dict[str, Any]] = []
    all_ok = True
    for name, fn in specs:
        n = int(fn(db))
        ok = n == 0
        if not ok:
            all_ok = False
        checks.append({"name": name, "ok": ok, "count": n})
    return {"integrity_ok": all_ok, "checks": checks}
