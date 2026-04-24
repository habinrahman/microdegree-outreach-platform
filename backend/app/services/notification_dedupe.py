"""Collapse duplicate type=reply notifications (same campaign) for API display."""
from __future__ import annotations

import re
from typing import Any

_CAMPAIGN_ID = re.compile(r"campaign\s+([0-9a-f-]{36})", re.I)


def reply_dedupe_key(n: Any) -> str | None:
    if getattr(n, "type", None) != "reply":
        return None
    rfc = getattr(n, "reply_for_campaign_id", None)
    if rfc is not None:
        return str(rfc).lower()
    m = _CAMPAIGN_ID.search(n.body or "")
    return m.group(1).lower() if m else None


def dedupe_notifications_for_display(rows: list[Any], *, max_items: int) -> list[Any]:
    """Newest-first rows: keep first (newest) per reply campaign id; passthrough other types."""
    seen: set[str] = set()
    out: list[Any] = []
    for n in rows:
        key = reply_dedupe_key(n)
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        out.append(n)
        if len(out) >= max_items:
            break
    return out
