"""Generate email campaign schedule when HR contacts are assigned to a student."""

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models import Assignment, EmailCampaign
from app.services.sequence_service import ensure_four_step_campaign_rows


def generate_campaigns_for_assignment(
    db: Session,
    assignment: Assignment,
    assigned_date: date | None = None,
    anchor: datetime | None = None,
) -> list[EmailCampaign]:
    """
    Ensure the pre-created 4-step sequence exists for this assignment.

    Returns a one-element list containing the **lowest-sequence** active row when one exists
    (backward compatible with callers using ``created[0]`` as the head of the queue), otherwise
    the initial row (sequence 1) after creation.
    """
    _ = assigned_date  # legacy signature; anchor drives scheduling instead

    active = (
        db.query(EmailCampaign)
        .filter(
            EmailCampaign.student_id == assignment.student_id,
            EmailCampaign.hr_id == assignment.hr_id,
            EmailCampaign.status.in_(("pending", "scheduled", "processing")),
        )
        .order_by(EmailCampaign.sequence_number.asc(), EmailCampaign.created_at.asc())
        .first()
    )
    if active:
        ensure_four_step_campaign_rows(db, assignment, anchor=anchor)
        return [active]

    anchor_dt = anchor or datetime.now(timezone.utc)
    ensure_four_step_campaign_rows(db, assignment, anchor=anchor_dt)

    initial = (
        db.query(EmailCampaign)
        .filter(
            EmailCampaign.student_id == assignment.student_id,
            EmailCampaign.hr_id == assignment.hr_id,
            EmailCampaign.sequence_number == 1,
        )
        .first()
    )
    return [initial] if initial else []


def generate_campaigns_for_assignments(
    db: Session,
    assignments: list[Assignment],
) -> list[EmailCampaign]:
    """Generate campaigns for multiple assignments (e.g. after bulk assign)."""
    all_campaigns: list[EmailCampaign] = []
    for a in assignments:
        all_campaigns.extend(generate_campaigns_for_assignment(db, a))
    return all_campaigns
