"""Cancel remaining follow-up campaigns when HR responds."""
from uuid import UUID
from sqlalchemy.orm import Session

from app.models import EmailCampaign
from app.services.campaign_lifecycle import assert_legal_email_campaign_transition
from app.services.sequence_state_service import mark_sequence_terminated_replied


def cancel_followups_for_hr_response(
    db: Session,
    student_id: UUID,
    hr_id: UUID,
    *,
    commit: bool = True,
    reason: str = "hr_replied",
) -> int:
    """
    When HR has replied (e.g. response recorded), cancel all scheduled follow-up
    campaigns for this (student_id, hr_id). Returns count cancelled.
    """
    updated = (
        db.query(EmailCampaign)
        .filter(
            EmailCampaign.student_id == student_id,
            EmailCampaign.hr_id == hr_id,
            EmailCampaign.status.in_(("scheduled", "pending")),
            EmailCampaign.email_type.in_(("followup_1", "followup_2", "followup_3")),
        )
        .all()
    )
    note = (reason or "hr_replied")[:2000]
    for c in updated:
        assert_legal_email_campaign_transition(c.status, "cancelled", context="cancel_followups/hr-replied")
        c.status = "cancelled"
        c.suppression_reason = note
    mark_sequence_terminated_replied(db, student_id=student_id, hr_id=hr_id)
    if commit:
        db.commit()
    return len(updated)
