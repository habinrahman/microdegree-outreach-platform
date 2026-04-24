"""Mark HR contacts invalid after delivery failure (bounce, block, or send failed)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import HRContact


def hr_email_is_consumer_gmail(email: str | None) -> bool:
    e = (email or "").strip().lower()
    return e.endswith("@gmail.com") or e.endswith("@googlemail.com")


def inbound_bounce_should_block_hr(hr_email: str | None, delivery_subtype: str) -> bool:
    """
    Consumer Gmail addresses are not added to the blocklist (or marked invalid) on generic
    bounces; only on explicit SMTP/policy blocks (subtype BLOCKED).
    """
    sub = (delivery_subtype or "").strip().upper()
    if sub not in ("BOUNCED", "BLOCKED"):
        return False
    if hr_email_is_consumer_gmail(hr_email):
        return sub == "BLOCKED"
    return True


def _explicit_smtp_policy_block_in_text(text: str) -> bool:
    t = (text or "").lower()
    return any(
        k in t
        for k in (
            "message blocked",
            "blocked by",
            "550 5.7.1",
            "554 5.7.1",
            "policy violation",
            "violates the policy",
            "spam",
            "rejected for policy",
            "rejected by server",
        )
    )


def outbound_failure_should_invalidate_hr(hr_email: str | None, error_text: str) -> bool:
    """After outbound SMTP failure: do not invalidate consumer Gmail unless policy block signals."""
    if not hr_email_is_consumer_gmail(hr_email):
        return True
    return _explicit_smtp_policy_block_in_text(error_text or "")


def mark_hr_invalid_if_valid(db: Session, hr_id) -> bool:
    """
    Set is_valid False and status 'invalid' only when the HR is currently valid.
    Returns True if the row was updated (does not commit).
    """
    if hr_id is None:
        return False
    hr = db.query(HRContact).filter(HRContact.id == hr_id).first()
    if hr is None or hr.is_valid is False:
        return False
    hr.is_valid = False
    hr.status = "invalid"
    db.add(hr)
    return True
