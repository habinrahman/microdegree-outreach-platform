"""Strict persistence for EmailCampaign rows marked sent (sent_at + commit + refresh + guards)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.utils.datetime_utils import ensure_utc
from app.services.student_email_usage import record_student_successful_email

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.email_campaign import EmailCampaign


def persist_sent_email_campaign(
    db: Session,
    campaign: EmailCampaign,
    *,
    record_student_usage: bool = True,
) -> None:
    """
    Call after campaign.status == \"sent\" and in-memory fields are final.
    Ensures sent_at is timezone-aware UTC, commits, refreshes, and verifies persistence.
    """
    if not campaign.sent_at:
        campaign.sent_at = ensure_utc(datetime.now(timezone.utc))
    if not campaign.sent_at:
        raise RuntimeError("CRITICAL: sent_at not set after send")
    if record_student_usage:
        record_student_successful_email(db, campaign.student_id)
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    if not campaign.sent_at:
        raise RuntimeError("CRITICAL: sent_at not persisted")
