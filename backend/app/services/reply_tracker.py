"""IMAP-based reply detection: In-Reply-To / References match to campaign.message_id, ignore self-sent."""
from __future__ import annotations

import logging
import re
from email.utils import parseaddr

from sqlalchemy.exc import OperationalError, PendingRollbackError
from sqlalchemy.orm import Session

from app.database.config import SessionLocal
from app.database.session_resilience import recover_db_session
from app.models import EmailCampaign, Student
from app.services.campaign_cancel import cancel_followups_for_hr_response
from app.services.reply_classifier import apply_inbound_reply_to_campaign
from app.services.imap_client import fetch_inbox, fetch_messages
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

_MAX_REPLY_TEXT_LEN = 100_000

_SESSION_RESET_ERRORS = (OperationalError, PendingRollbackError)


def _rollback_db_session(db: Session, exc: BaseException | None = None) -> None:
    """Clear aborted transaction so the same Session can be reused (PgBouncer drops)."""
    recover_db_session(db, exc if isinstance(exc, OperationalError) else None, log=logger)


def _canonical_message_id(value: str | None) -> str | None:
    if not value:
        return None
    s = str(value).strip()
    m = re.search(r"<[^<>]+>", s)
    if m:
        return m.group(0).strip().lower()
    return s.lower() if s else None


def _reference_tokens(header_val: str | None) -> list[str]:
    if not header_val:
        return []
    raw = str(header_val).replace("\n", " ").strip()
    parts = re.split(r"\s+", raw)
    return [p for p in parts if p and p != ">"]


def check_replies_for_student(db: Session, student: Student) -> int:
    """
    Scan inbox; match In-Reply-To or References to outbound campaign.message_id.
    Dedupes by inbound Message-ID vs campaign.last_reply_message_id.
    """
    email_addr = (getattr(student, "gmail_address", None) or "").strip()
    app_pw = (getattr(student, "app_password", None) or "").strip()
    if not email_addr or not app_pw:
        return 0

    student_email_lower = email_addr.lower()

    message_nums: list[bytes] = []
    mail = None
    try:
        message_nums, mail = fetch_inbox(email_addr, app_pw)
        messages = fetch_messages(mail, message_nums)
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass

    try:
        candidates = (
            db.query(EmailCampaign)
            .filter(
                EmailCampaign.student_id == student.id,
                EmailCampaign.message_id.isnot(None),
                EmailCampaign.status.in_(("sent", "replied")),
            )
            .all()
        )
    except _SESSION_RESET_ERRORS as e:
        _rollback_db_session(db, e)
        raise
    by_mid: dict[str, EmailCampaign] = {}
    for c in candidates:
        key = _canonical_message_id(c.message_id)
        if key:
            # Prefer the row that actually sent (sequence tie-break: lower sequence first)
            existing = by_mid.get(key)
            if existing is None or (c.sequence_number or 99) < (existing.sequence_number or 99):
                by_mid[key] = c

    matched = 0
    capture_now = utc_now()
    pairs: set[tuple] = set()

    for msg in messages:
        raw_from = msg.get("from")
        from_header = str(raw_from or "").strip()
        _, sender_addr = parseaddr(from_header)
        sender_lower = (sender_addr or "").strip().lower()
        if not sender_lower:
            continue
        if sender_lower == student_email_lower:
            continue

        inbound_mid = _canonical_message_id(msg.get("message_id"))
        irt_key = _canonical_message_id(msg.get("in_reply_to"))
        ref_keys = [_canonical_message_id(t) for t in _reference_tokens(msg.get("references"))]
        ref_keys = [k for k in ref_keys if k]

        campaign = None
        if irt_key:
            campaign = by_mid.get(irt_key)
        if not campaign:
            for lk in ref_keys:
                campaign = by_mid.get(lk)
                if campaign:
                    break

        if not campaign:
            continue

        if inbound_mid and campaign.last_reply_message_id:
            if inbound_mid == _canonical_message_id(campaign.last_reply_message_id):
                continue

        outbound_key = _canonical_message_id(campaign.message_id)
        if not outbound_key:
            continue
        chain_keys = [k for k in [irt_key, *ref_keys] if k]
        if outbound_key not in chain_keys:
            continue

        body = (msg.get("body_plain") or "").strip()
        if not body:
            continue

        received_at = msg.get("received_at") or capture_now
        result = apply_inbound_reply_to_campaign(
            db,
            campaign,
            body[:_MAX_REPLY_TEXT_LEN],
            sender_for_classify=sender_lower,
            reply_from_header=from_header,
            when=received_at,
            inbound_message_id=msg.get("message_id"),
        )
        if result == "IGNORED":
            continue
        matched += 1
        if campaign.replied:
            pairs.add((campaign.student_id, campaign.hr_id))
        # Allow another inbound to match same outbound only if different Message-ID (dedupe above)
        if campaign.status == "failed" and campaign.failure_type in ("BOUNCED", "BLOCKED"):
            by_mid.pop(outbound_key, None)

    for sid, hid in pairs:
        cancel_followups_for_hr_response(db, sid, hid, commit=False, reason="reply_ingestion")

    if matched:
        db.commit()
        try:
            from app.services.sheet_sync_trigger import trigger_sheet_sync_async

            trigger_sheet_sync_async(reason="reply_tracker commit")
        except Exception as e:
            logger.warning("sheet_sync after reply_tracker commit failed: %s", e)
    return matched


def check_replies(*, max_students: int = 50) -> dict:
    """Periodic job: IMAP inbox per student (app password), strict reply matching."""
    import time

    t0 = time.perf_counter()
    db = SessionLocal()
    try:
        students = (
            db.query(Student)
            .filter(
                Student.app_password.isnot(None),
                Student.gmail_address.isnot(None),
            )
            .order_by(Student.created_at.desc())
            .limit(max_students)
            .all()
        )
        total = 0
        for student in students:
            try:
                total += check_replies_for_student(db, student)
            except Exception as e:
                logger.warning(
                    "IMAP reply check failed for %s (%s): %s",
                    student.id,
                    getattr(student, "gmail_address", None),
                    e,
                )
                _rollback_db_session(db, e)
        out = {"ok": True, "students_scanned": len(students), "campaigns_marked_replied": total}
        try:
            from app.services.observability_metrics import inc, observe_latency

            inc("reply_ingestion_runs_total")
            inc("reply_ingestion_replies_total", int(total))
            observe_latency("reply_job", (time.perf_counter() - t0) * 1000.0)
        except Exception:
            pass
        return out
    except OperationalError as e:
        recover_db_session(db, e, log=logger)
        logger.warning(
            "reply_tracker: database unavailable (will retry next tick): %s",
            e,
        )
        raise
    except PendingRollbackError:
        recover_db_session(db, None, log=logger)
        raise
    finally:
        db.close()
