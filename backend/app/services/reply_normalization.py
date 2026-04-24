"""
Canonical reply labels + legacy parsing.

Body clean/classify: ``app.services.reply_utils``.
"""
from __future__ import annotations

from app.services.reply_utils import (
    AUTO_REPLY,
    BOUNCE,
    INTERESTED,
    INTERVIEW,
    OTHER,
    OOO,
    REJECTED,
    UNKNOWN,
    classify_reply,
    clean_reply,
)

CANONICAL_REPLY_TYPES = frozenset(
    {INTERESTED, INTERVIEW, REJECTED, AUTO_REPLY, BOUNCE, OTHER, OOO, UNKNOWN}
)

# Alias for older call sites
classify_reply_text = classify_reply


def internal_status_to_canonical(status: str) -> str:
    s = (status or "").strip().upper()
    if s == BOUNCE or s in ("BOUNCED", "BLOCKED", "TEMP_FAIL"):
        return BOUNCE
    if s in ("REJECTED", "NOT_INTERESTED"):
        return REJECTED
    if s == AUTO_REPLY:
        return AUTO_REPLY
    if s == INTERVIEW:
        return INTERVIEW
    if s == INTERESTED:
        return INTERESTED
    if s == OOO:
        return OOO
    if s == UNKNOWN:
        return UNKNOWN
    if s in ("REPLIED", "INITIAL", ""):
        return OTHER
    return OTHER


def canonical_to_reply_status(
    canonical: str, *, previous_delivery_status: str | None = None
) -> str:
    if canonical == BOUNCE:
        prev = (previous_delivery_status or "").strip().upper()
        if prev in ("BLOCKED", "TEMP_FAIL", "BOUNCED"):
            return prev
        return "BOUNCED"
    if canonical == OTHER:
        return "REPLIED"
    if canonical in (INTERESTED, INTERVIEW, REJECTED, AUTO_REPLY, OOO, UNKNOWN):
        return canonical
    return "REPLIED"


def parse_legacy_reply_type_column(value: str | None) -> str | None:
    if not value or not str(value).strip():
        return None
    v = str(value).strip().upper()
    if v in CANONICAL_REPLY_TYPES:
        return v
    low = v.lower()
    m = {
        "bounce": BOUNCE,
        "auto_reply": AUTO_REPLY,
        "interview": INTERVIEW,
        "interested": INTERESTED,
        "rejected": REJECTED,
        "not_interested": REJECTED,
        "other": OTHER,
        "ooo": OOO,
        "unknown": UNKNOWN,
    }
    return m.get(low)
