"""Outbound suppression list: deterministic recipient blocks (bounces, invalids, manual)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models.outbound_suppression import OutboundSuppression
from app.services.outbound_suppression_bootstrap import ensure_outbound_suppression_schema_connection

logger = logging.getLogger(__name__)


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def suppression_table_missing(exc: BaseException) -> bool:
    if isinstance(exc, (ProgrammingError, OperationalError)):
        msg = str(exc).lower()
        if "outbound_suppressions" in msg and (
            "does not exist" in msg or "undefinedtable" in msg.replace(" ", "") or "no such table" in msg
        ):
            return True
    orig = getattr(exc, "orig", None)
    if orig is not None and orig is not exc:
        return suppression_table_missing(orig)
    return False


def is_suppressed(db: Session, email: str, *, now_utc: datetime | None = None) -> tuple[bool, str | None]:
    """
    Returns (blocked, reason).

    Fail-safe: if suppression cannot be evaluated due to DB errors, block.
    Missing-table environments fail-open (compat) but log a warning.
    """
    e = _norm_email(email)
    if not e or "@" not in e:
        return False, None
    now = now_utc or datetime.now(timezone.utc)
    try:
        row = db.query(OutboundSuppression).filter(OutboundSuppression.email_lower == e).first()
    except Exception as exc:
        if suppression_table_missing(exc):
            # Drift safety: attempt to create the table, then retry once.
            try:
                conn = db.get_bind()
                with conn.begin() as tx_conn:  # type: ignore[attr-defined]
                    ensure_outbound_suppression_schema_connection(tx_conn)
                db.rollback()
                row = db.query(OutboundSuppression).filter(OutboundSuppression.email_lower == e).first()
            except Exception:
                logger.warning("outbound_suppressions missing and bootstrap failed; fail-open for %s", e)
                return False, None
        logger.exception("suppression check failed; blocking send for safety")
        return True, "suppression_check_error"
    if row is None:
        return False, None
    if not bool(getattr(row, "is_active", True)):
        return False, None
    until = getattr(row, "suppressed_until", None)
    if until is not None:
        # Stored naive in DB; treat as UTC.
        until_utc = until.replace(tzinfo=timezone.utc) if getattr(until, "tzinfo", None) is None else until
        if until_utc <= now:
            return False, None
    return True, (row.reason or row.source or "suppressed")


def upsert_suppression(
    db: Session,
    *,
    email: str,
    reason: str | None,
    source: str | None,
    active: bool = True,
    suppressed_until: datetime | None = None,
) -> OutboundSuppression:
    e = (email or "").strip()
    el = _norm_email(email)
    if not el or "@" not in el:
        raise ValueError("Invalid email for suppression")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    bind = db.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", "") if bind is not None else ""
    r = (reason or "").strip() or None
    s = (source or "").strip() or None

    # Concurrency-safe upsert for Postgres (prevents unique violations under parallel bounces).
    if dialect == "postgresql":
        try:
            db.execute(
                text(
                    """
                    INSERT INTO outbound_suppressions
                      (id, email, email_lower, reason, source, is_active, suppressed_until, created_at, updated_at)
                    VALUES
                      (:id, :email, :email_lower, :reason, :source, :is_active, :suppressed_until, :created_at, :updated_at)
                    ON CONFLICT (email_lower) DO UPDATE SET
                      email = EXCLUDED.email,
                      reason = EXCLUDED.reason,
                      source = EXCLUDED.source,
                      is_active = EXCLUDED.is_active,
                      suppressed_until = EXCLUDED.suppressed_until,
                      updated_at = EXCLUDED.updated_at
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "email": e,
                    "email_lower": el,
                    "reason": r,
                    "source": s,
                    "is_active": bool(active),
                    "suppressed_until": suppressed_until,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            if suppression_table_missing(exc):
                conn = db.get_bind()
                with conn.begin() as tx_conn:  # type: ignore[attr-defined]
                    ensure_outbound_suppression_schema_connection(tx_conn)
                # retry once after bootstrap
                db.execute(
                    text(
                        """
                        INSERT INTO outbound_suppressions
                          (id, email, email_lower, reason, source, is_active, suppressed_until, created_at, updated_at)
                        VALUES
                          (:id, :email, :email_lower, :reason, :source, :is_active, :suppressed_until, :created_at, :updated_at)
                        ON CONFLICT (email_lower) DO UPDATE SET
                          email = EXCLUDED.email,
                          reason = EXCLUDED.reason,
                          source = EXCLUDED.source,
                          is_active = EXCLUDED.is_active,
                          suppressed_until = EXCLUDED.suppressed_until,
                          updated_at = EXCLUDED.updated_at
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "email": e,
                        "email_lower": el,
                        "reason": r,
                        "source": s,
                        "is_active": bool(active),
                        "suppressed_until": suppressed_until,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                db.commit()
            else:
                raise
        row = db.query(OutboundSuppression).filter(OutboundSuppression.email_lower == el).first()
        if row is None:
            raise RuntimeError("suppression upsert failed to persist row")
        return row

    # Fallback: ORM path (SQLite / dev). Best-effort; no cross-process concurrency expected.
    try:
        row = db.query(OutboundSuppression).filter(OutboundSuppression.email_lower == el).first()
    except Exception as exc:
        if suppression_table_missing(exc):
            conn = db.get_bind()
            with conn.begin() as tx_conn:  # type: ignore[attr-defined]
                ensure_outbound_suppression_schema_connection(tx_conn)
            db.rollback()
            row = db.query(OutboundSuppression).filter(OutboundSuppression.email_lower == el).first()
        else:
            raise
    if row is None:
        row = OutboundSuppression(
            email=e,
            email_lower=el,
            reason=r,
            source=s,
            is_active=bool(active),
            suppressed_until=suppressed_until,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.email = e
        row.reason = r
        row.source = s
        row.is_active = bool(active)
        row.suppressed_until = suppressed_until
        row.updated_at = now
        db.add(row)
    db.commit()
    return row

