"""Central clean + classify for reply bodies (ingestion + batch scripts)."""

from __future__ import annotations

_MAX_STORE = 100_000

INTERESTED = "INTERESTED"
INTERVIEW = "INTERVIEW"
REJECTED = "REJECTED"
AUTO_REPLY = "AUTO_REPLY"
BOUNCE = "BOUNCE"
OTHER = "OTHER"
OOO = "OOO"
UNKNOWN = "UNKNOWN"


def clean_reply(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\uFEFF", "")

    separators = [
        "-----Original Message-----",
        "From:",
        "On Mon",
        "On Tue",
        "On Wed",
        "On Thu",
        "On Fri",
        "On Sat",
        "On Sun",
    ]

    for sep in separators:
        if sep in text:
            text = text.split(sep, maxsplit=1)[0]

    out = text.strip()
    return out[:_MAX_STORE] if out else ""


def classify_reply(text: str) -> str:
    """Classify inbound reply body. Bounce heuristics first; then keyword buckets for reply_status."""
    t = (text or "").lower()

    if any(
        x in t
        for x in (
            "address not found",
            "delivery",
            "not delivered",
            "message blocked",
        )
    ):
        return BOUNCE

    if "experience" in t:
        return INTERESTED
    if "out of office" in t:
        return OOO
    if "not looking" in t:
        return REJECTED
    if "leave" in t:
        return OOO

    return UNKNOWN
