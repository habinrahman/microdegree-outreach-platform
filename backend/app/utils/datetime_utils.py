"""Datetime serialization helpers for API responses."""
from datetime import datetime, timezone


def ensure_utc(dt):
    """Reject naive datetimes before persisting or combining with other UTC-aware values."""
    if dt and dt.tzinfo is None:
        raise RuntimeError("Naive datetime detected — must use timezone.utc")
    return dt


def utc_now():
    """Timezone-aware current UTC instant (for Column defaults and inserts)."""
    return ensure_utc(datetime.now(timezone.utc))


def to_ist(dt):
    if not dt:
        return None
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    from pytz import timezone as pytz_timezone
    ist = pytz_timezone("Asia/Kolkata")
    return dt.astimezone(ist).isoformat()

