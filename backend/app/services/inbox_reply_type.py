"""Resolve canonical reply_type (UPPERCASE) for API + SQL filters."""
from __future__ import annotations

from app.models.email_campaign import EmailCampaign
from app.services.reply_normalization import (
    AUTO_REPLY,
    BOUNCE,
    INTERESTED,
    INTERVIEW,
    OTHER,
    OOO,
    REJECTED,
    UNKNOWN,
    parse_legacy_reply_type_column,
)

# Filter query param (lowercase) → canonical
FILTER_TO_CANONICAL = {
    "bounce": BOUNCE,
    "auto_reply": AUTO_REPLY,
    "interview": INTERVIEW,
    "interested": INTERESTED,
    "rejected": REJECTED,
    "ooo": OOO,
    "unknown": UNKNOWN,
    "other": OTHER,
}


def canonical_reply_type_for_api(ec: EmailCampaign) -> str:
    """Single UPPERCASE bucket for responses and filtering."""
    parsed = parse_legacy_reply_type_column(getattr(ec, "reply_type", None))
    if parsed:
        return parsed
    rs = (getattr(ec, "reply_status", None) or "").strip().upper()
    if rs == BOUNCE or rs in ("BOUNCED", "BLOCKED", "TEMP_FAIL"):
        return BOUNCE
    if rs == "AUTO_REPLY":
        return AUTO_REPLY
    if rs == "INTERVIEW":
        return INTERVIEW
    if rs in ("REJECTED", "NOT_INTERESTED"):
        return REJECTED
    if rs == "INTERESTED":
        return INTERESTED
    if rs == OOO:
        return OOO
    if rs == UNKNOWN:
        return UNKNOWN
    if rs in ("INITIAL", "REPLIED", ""):
        return OTHER
    if getattr(ec, "replied", None) and (ec.reply_text or "").strip():
        return OTHER
    return OTHER


def normalize_inbox_reply_type(ec: EmailCampaign) -> str:
    """Backward-compatible lowercase slug (e.g. campaign list UI)."""
    c = canonical_reply_type_for_api(ec)
    return {
        INTERESTED: "interested",
        INTERVIEW: "interview",
        REJECTED: "rejected",
        AUTO_REPLY: "auto_reply",
        BOUNCE: "bounce",
        OOO: "ooo",
        UNKNOWN: "unknown",
        OTHER: "other",
    }.get(c, "other")
