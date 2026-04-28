"""Session hygiene after transient Postgres / pooler disconnects (schedulers + request-scoped DB)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy.exc import OperationalError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def recover_db_session(db: Session, exc: BaseException | None = None, *, log: logging.Logger | None = None) -> None:
    """
    Roll back an aborted or invalid transaction; invalidate the pooled connection after OperationalError
    so the next checkout is fresh. Safe to call from ``except`` blocks and before ``session.close()``.
    """
    lg = log or logger
    try:
        db.rollback()
    except Exception:
        lg.warning("db session rollback failed during disconnect recovery", exc_info=True)
    if isinstance(exc, OperationalError):
        try:
            db.connection().invalidate(exc)
        except Exception:
            lg.warning("db connection invalidate failed after OperationalError", exc_info=True)
