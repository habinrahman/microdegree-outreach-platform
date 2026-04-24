"""
Single gate for whether an EmailCampaign row may be claimed/sent by the scheduler (or worker).

Keeps scheduler behavior aligned with follow-up eligibility invariants: no FU without env +
operator toggle, no FU before prior step sent, stop if pair already replied on initial row.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import FOLLOWUPS_ENABLED
from app.models import EmailCampaign, HRContact, Student
from app.services.runtime_settings_store import get_followups_dispatch_enabled
from app.services.sequence_state_service import sequence_state_allows_followup_send


def _lower(x: str | None) -> str:
    return (x or "").strip().lower()


def scheduler_may_send_campaign(
    db: Session,
    campaign: EmailCampaign,
    *,
    now_utc: datetime | None = None,
    ignore_due_time: bool = False,
) -> tuple[bool, str | None]:
    """
    Return (allowed, reason_if_blocked). Intended for ``scheduled`` rows about to be claimed.
    """
    now = now_utc or datetime.now(timezone.utc)
    st = _lower(campaign.status)
    if st not in ("scheduled", "pending"):
        return False, "not_queueable_status"

    et = _lower(campaign.email_type)
    seq = int(campaign.sequence_number or 0)

    if et != "initial":
        if not FOLLOWUPS_ENABLED:
            return False, "followups_disabled_env"
        if not get_followups_dispatch_enabled(db):
            return False, "followups_dispatch_off"

    # Prior step must be sent for follow-ups
    if seq > 1:
        prev = (
            db.query(EmailCampaign)
            .filter(
                EmailCampaign.student_id == campaign.student_id,
                EmailCampaign.hr_id == campaign.hr_id,
                EmailCampaign.sequence_number == seq - 1,
            )
            .first()
        )
        if prev is None:
            return False, "missing_prior_sequence_row"
        if _lower(prev.status) != "sent":
            return False, "prior_step_not_sent"

    # Pair-level reply stop (initial row is canonical for thread terminal)
    initial = (
        db.query(EmailCampaign)
        .filter(
            EmailCampaign.student_id == campaign.student_id,
            EmailCampaign.hr_id == campaign.hr_id,
            EmailCampaign.sequence_number == 1,
        )
        .first()
    )
    if initial:
        if bool(getattr(initial, "replied", False)) or _lower(initial.status) == "replied":
            if seq > 1:
                return False, "pair_replied_initial"
        # If initial never sent, do not send follow-ups
        if seq > 1 and _lower(initial.status) != "sent":
            return False, "initial_not_sent"
        if seq > 1 and not sequence_state_allows_followup_send(initial):
            return False, "sequence_lifecycle_not_active"

    student = db.query(Student).filter(Student.id == campaign.student_id).first()
    if not student or _lower(getattr(student, "status", None)) != "active":
        return False, "inactive_student"

    hr = db.query(HRContact).filter(HRContact.id == campaign.hr_id).first()
    if not hr or hr.is_valid is not True:
        return False, "invalid_hr"

    if not getattr(student, "app_password", None):
        return False, "missing_app_password"

    ehs = getattr(student, "email_health_status", None)
    if ehs is not None and _lower(str(ehs)) not in ("healthy", "warning", ""):
        return False, "student_email_health"

    if not ignore_due_time:
        sa = campaign.scheduled_at
        if sa is not None:
            sa_utc = sa if sa.tzinfo else sa.replace(tzinfo=timezone.utc)
            if sa_utc > now:
                return False, "not_due_yet"

    return True, None
