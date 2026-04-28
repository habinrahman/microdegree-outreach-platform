"""Update student resume (soft replace) and optionally refresh pending campaign bodies."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.email_campaign import EmailCampaign
from app.models.hr_contact import HRContact
from app.models.student import Student
from app.models.student_template import StudentTemplate
from app.services.email_templates import TEMPLATES, render_template
from app.services.sequence_service import _template_context

logger = logging.getLogger(__name__)

_EMAIL_TYPE_TO_TEMPLATE_TYPE = {
    "initial": "INITIAL",
    "followup_1": "FOLLOWUP_1",
    "followup_2": "FOLLOWUP_2",
    "followup_3": "FOLLOWUP_3",
}


def backend_root_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def resumes_upload_dir() -> str:
    d = os.path.join(backend_root_dir(), "uploads", "resumes")
    os.makedirs(d, exist_ok=True)
    return d


def absolute_resume_path(relative: str) -> str:
    """Resolve DB-relative resume path under backend root; reject traversal."""
    rel = (relative or "").strip().replace("\\", "/")
    if not rel or ".." in rel or rel.startswith(("/", "\\")):
        raise ValueError("invalid_resume_path")
    root = os.path.normpath(backend_root_dir())
    full = os.path.normpath(os.path.join(root, rel))
    if not full.startswith(root + os.sep) and full != root:
        raise ValueError("invalid_resume_path")
    return full


def count_queueable_campaigns_for_student(db: Session, student_id) -> int:
    return int(
        db.query(func.count(EmailCampaign.id))
        .filter(
            EmailCampaign.student_id == student_id,
            EmailCampaign.status.in_(("pending", "scheduled")),
        )
        .scalar()
        or 0
    )


def _first_builtin_template(email_type: str) -> dict:
    et = (email_type or "initial").lower()
    variants = TEMPLATES.get(et, TEMPLATES["initial"])
    return dict(variants[0])


def _render_subject_body_for_campaign(db: Session, student: Student, hr: HRContact, campaign: EmailCampaign) -> tuple[str, str]:
    ctx = _template_context(student, hr)
    et = (campaign.email_type or "initial").lower()
    tt = _EMAIL_TYPE_TO_TEMPLATE_TYPE.get(et, "INITIAL")
    row = (
        db.query(StudentTemplate)
        .filter(StudentTemplate.student_id == student.id, StudentTemplate.template_type == tt)
        .first()
    )
    if row is not None and (row.subject or "").strip() and (row.body or "").strip():
        return render_template(row.subject, ctx), render_template(row.body, ctx)
    tpl = _first_builtin_template(et)
    return render_template(tpl["subject"], ctx), render_template(tpl["body"], ctx)


def refresh_pending_campaign_templates(db: Session, student: Student) -> int:
    """
    Re-render subject/body for pending|scheduled rows using current student + HR context.
    Does not touch sent/replied/cancelled rows.
    """
    campaigns = (
        db.query(EmailCampaign)
        .filter(
            EmailCampaign.student_id == student.id,
            EmailCampaign.status.in_(("pending", "scheduled")),
        )
        .all()
    )
    n = 0
    for c in campaigns:
        hr = db.query(HRContact).filter(HRContact.id == c.hr_id).first()
        if not hr:
            continue
        try:
            subj, body = _render_subject_body_for_campaign(db, student, hr, c)
        except Exception:
            logger.exception("refresh_pending_campaign_templates: render failed campaign=%s", c.id)
            continue
        c.subject = subj
        c.body = body
        db.add(c)
        n += 1
    if n:
        db.commit()
    return n
