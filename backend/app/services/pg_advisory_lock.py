"""Cross-process idempotency locks (Postgres advisory locks).

Used to prevent duplicate sends when multiple workers are invoked with the same campaign id.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session


def _uuid_to_lock_keys(u: uuid.UUID) -> tuple[int, int]:
    # pg_try_advisory_lock takes signed int4,int4 for the 2-key variant.
    n = int(u)
    hi = (n >> 64) & ((1 << 64) - 1)
    lo = n & ((1 << 64) - 1)
    k1 = hi & 0xFFFFFFFF
    k2 = lo & 0xFFFFFFFF
    # convert to signed 32-bit
    if k1 >= 2**31:
        k1 -= 2**32
    if k2 >= 2**31:
        k2 -= 2**32
    return int(k1), int(k2)


@contextmanager
def campaign_send_lock(db: Session, campaign_id: str):
    """
    Best-effort global lock:
    - Postgres: pg_try_advisory_lock(k1,k2) / unlock
    - Others: no-op lock (assume single-process dev)
    """
    acquired = True
    keys = None
    try:
        bind = db.get_bind()
        dialect = getattr(getattr(bind, "dialect", None), "name", "") if bind is not None else ""
        if dialect == "postgresql":
            u = uuid.UUID(str(campaign_id))
            k1, k2 = _uuid_to_lock_keys(u)
            keys = (k1, k2)
            acquired = bool(
                db.execute(text("select pg_try_advisory_lock(:k1, :k2)"), {"k1": k1, "k2": k2}).scalar()
            )
        yield acquired
    finally:
        try:
            if keys is not None:
                k1, k2 = keys
                db.execute(text("select pg_advisory_unlock(:k1, :k2)"), {"k1": k1, "k2": k2})
                # unlock result is best-effort; ignore.
        except Exception:
            pass

