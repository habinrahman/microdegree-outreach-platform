"""Derived outreach log rows from EmailCampaign (single source of truth)."""
from __future__ import annotations

from typing import Any

from app.utils.datetime_utils import to_ist


def outreach_log_dict(
    *,
    campaign: Any,
    student_name: str,
    company: str,
    hr_email: str,
) -> dict:
    """Build the same shape as GET /outreach/logs with unified status + delivery fields."""
    display_status = campaign.status
    note = None
    if getattr(campaign, "delivery_status", None) == "FAILED":
        display_status = "failed"
    elif getattr(campaign, "reply_status", None):
        display_status = "replied"
        note = "Reply recorded"

    sent = to_ist(campaign.sent_at)
    return {
        "id": str(campaign.id),
        "campaign_id": str(campaign.id),
        "student_id": str(campaign.student_id),
        "hr_id": str(campaign.hr_id),
        "student_name": student_name,
        "company": company,
        "hr_email": hr_email,
        "status": display_status,
        "email_type": campaign.email_type,
        "sent_at": sent,
        "sent_time": sent,
        "error": campaign.error,
        "reply_status": getattr(campaign, "reply_status", None),
        "delivery_status": getattr(campaign, "delivery_status", None),
        "note": note,
        "timestamp": sent,
    }
