"""Shared EmailCampaign filters for /campaigns, /replies, /outreach/logs."""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from app.models.email_campaign import EmailCampaign
from app.models.hr_contact import HRContact


def email_campaigns_scoped_to_hr(db: Session, *, include_demo: bool) -> Query:
    """EmailCampaign rows joined to HR; when include_demo is False, exclude demo HRs (dashboard scope)."""
    q = db.query(EmailCampaign).join(HRContact, EmailCampaign.hr_id == HRContact.id)
    if not include_demo:
        q = q.filter(HRContact.is_demo.is_(False))
    return q


def apply_campaign_filters(
    q: Query,
    *,
    status: str | None = None,
    reply_status: str | None = None,
    delivery_status: str | None = None,
) -> Query:
    """Apply to any query whose FROM includes EmailCampaign."""
    if status:
        q = q.filter(EmailCampaign.status == status)
    if reply_status:
        q = q.filter(EmailCampaign.reply_status == reply_status)
    if delivery_status == "FAILED":
        q = q.filter(EmailCampaign.delivery_status == "FAILED")
    elif delivery_status == "SENT":
        q = q.filter(
            or_(
                EmailCampaign.delivery_status.is_(None),
                EmailCampaign.delivery_status != "FAILED",
            )
        )
    return q
