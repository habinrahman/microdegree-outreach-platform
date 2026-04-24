"""One-shot Gmail API scan + IMAP fallback to attach historical replies (reply_text was null)."""
from __future__ import annotations

import base64
import calendar
import email
import imaplib
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime

from sqlalchemy.orm import Session

from app.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from app.models import EmailCampaign, HRContact, Student
from app.services.reply_classifier import apply_inbound_reply_to_campaign

logger = logging.getLogger(__name__)

_MAX_REPLY_TEXT_LEN = 100_000
_GMAIL_QUERY = "newer_than:14d"
_MAX_LIST_RESULTS = 200


def _google_api_available() -> bool:
    try:
        import googleapiclient  # noqa: F401

        return True
    except Exception:
        return False


def _decode_b64url(data: str) -> str:
    if not data:
        return ""
    pad = 4 - len(data) % 4
    if pad != 4:
        data += "=" * pad
    try:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _plain_from_part(part: dict) -> str:
    mime = (part.get("mimeType") or "").lower()
    body = part.get("body") or {}
    chunks: list[str] = []
    if body.get("data") and "text/plain" in mime:
        chunks.append(_decode_b64url(body["data"]))
    for sub in part.get("parts") or []:
        t = _plain_from_part(sub)
        if t:
            chunks.append(t)
    return "\n".join(chunks).strip()


def _html_from_part(part: dict) -> str:
    mime = (part.get("mimeType") or "").lower()
    body = part.get("body") or {}
    if body.get("data") and "text/html" in mime:
        return _decode_b64url(body["data"]).strip()
    for sub in part.get("parts") or []:
        t = _html_from_part(sub)
        if t:
            return t
    return ""


def extract_body(msg: dict) -> str:
    payload = msg.get("payload") or {}
    body = payload.get("body") or {}
    mime = (payload.get("mimeType") or "").lower()
    if body.get("data"):
        if "text/plain" in mime:
            return _decode_b64url(body["data"]).strip()
        if "text/html" in mime:
            return _decode_b64url(body["data"]).strip()
    plain = _plain_from_part(payload)
    if plain:
        return plain
    html = _html_from_part(payload)
    return html.strip() if html else ""


def extract_from(msg: dict) -> tuple[str, str]:
    """Returns (raw From header value, sender email lowercased)."""
    headers = msg.get("payload", {}).get("headers") or []
    raw = ""
    for h in headers:
        if (h.get("name") or "").lower() == "from":
            raw = (h.get("value") or "").strip()
            break
    _, addr = parseaddr(raw)
    email_lower = (addr or "").strip().lower()
    return raw, email_lower


def _imap_since_date_30d() -> str:
    """IMAP SINCE date in English Mon abbreviation (portable, not locale-dependent)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    mon = calendar.month_abbr[cutoff.month]
    return f"{cutoff.day:02d}-{mon}-{cutoff.year}"


def _imap_extract_plain_body(msg: email.message.Message) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                raw = part.get_payload(decode=True)
                if raw is not None:
                    body = raw.decode(errors="ignore") if isinstance(raw, bytes) else str(raw)
                    if body.strip():
                        break
    else:
        raw = msg.get_payload(decode=True)
        if raw is not None:
            body = raw.decode(errors="ignore") if isinstance(raw, bytes) else str(raw)
    return body.strip()


def _imap_backfill_for_student(db: Session, student: Student, errors: list[str]) -> tuple[int, int]:
    """
    Deep inbox scan via app password: prefer HR email match, then subject match; reply_text IS NULL only.
    Returns (messages_scanned, backfilled_count).
    """
    app_pw = (student.app_password or "").strip()
    student_addr = (student.gmail_address or "").strip().lower()
    if not app_pw or not student_addr:
        return 0, 0

    logger.debug("IMAP Processing student: %s", student.gmail_address)

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    messages_scanned = 0
    backfilled = 0
    try:
        mail.login(student.gmail_address, app_pw)
        mail.select("inbox")
        since = _imap_since_date_30d()
        status, messages = mail.search(None, f'(SINCE "{since}")')
        if status != "OK" or not messages or not messages[0]:
            return 0, 0
        email_ids = messages[0].split()
        logger.debug("Total IMAP emails found: %s", len(email_ids))
        # Limit to latest 200 emails only
        email_ids = email_ids[-200:]
        logger.debug("Processing last: %s", len(email_ids))
        count = 0
        for num in email_ids:
            count += 1
            if count > 200:
                break
            try:
                _, data = mail.fetch(num, "(RFC822)")
                if not data or not data[0] or not isinstance(data[0], tuple) or len(data[0]) < 2:
                    continue
                raw_bytes = data[0][1]
                if not isinstance(raw_bytes, (bytes, bytearray)):
                    continue
                msg = email.message_from_bytes(bytes(raw_bytes))
            except Exception as e:
                errors.append(f"{student.id} IMAP fetch {num!r}: {e}")
                continue

            messages_scanned += 1
            mid = msg.get("Message-ID", "") or ""
            logger.debug("IMAP Message: %s", (mid or num)[:120])

            from_header = msg.get("From", "") or ""
            if isinstance(from_header, email.header.Header):
                from_header = str(from_header)
            _, sender_email = parseaddr(from_header)
            sender_email = (sender_email or "").strip().lower()
            if not sender_email or sender_email == student_addr:
                continue

            subject = msg.get("Subject", "") or ""
            if isinstance(subject, email.header.Header):
                subject = str(subject)
            subject_clean = subject.lower().replace("re:", "").strip()

            campaign = (
                db.query(EmailCampaign)
                .join(HRContact, EmailCampaign.hr_id == HRContact.id)
                .filter(
                    EmailCampaign.student_id == student.id,
                    HRContact.email.ilike(f"%{sender_email}%"),
                    EmailCampaign.reply_text.is_(None),
                )
                .order_by(EmailCampaign.created_at.desc())
                .first()
            )
            if campaign:
                logger.debug("IMAP matched via HR email: %s", campaign.id)
            elif subject_clean:
                campaign = (
                    db.query(EmailCampaign)
                    .filter(
                        EmailCampaign.student_id == student.id,
                        EmailCampaign.subject.isnot(None),
                        EmailCampaign.subject.ilike(f"%{subject_clean}%"),
                        EmailCampaign.reply_text.is_(None),
                    )
                    .order_by(EmailCampaign.created_at.desc())
                    .first()
                )
            if not campaign:
                continue

            body = _imap_extract_plain_body(msg)
            if not body:
                continue

            reply_dt: datetime | None = None
            date_hdr = msg.get("Date")
            if date_hdr:
                try:
                    reply_dt = parsedate_to_datetime(date_hdr)
                    if reply_dt is not None and reply_dt.tzinfo is None:
                        reply_dt = reply_dt.replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    reply_dt = None
            if reply_dt is None:
                reply_dt = datetime.now(timezone.utc)

            classify_src = f"{from_header} {sender_email}"
            result = apply_inbound_reply_to_campaign(
                db,
                campaign,
                body[:_MAX_REPLY_TEXT_LEN],
                sender_for_classify=classify_src,
                reply_from_header=from_header[:512] if from_header else None,
                when=reply_dt,
            )
            if result == "IGNORED":
                continue
            db.commit()
            backfilled += 1
            logger.debug("IMAP Backfilled: %s", campaign.id)
    except Exception as e:
        errors.append(f"{student.id}: IMAP session failed: {e}")
        logger.warning("replies_backfill IMAP failed for %s: %s", student.id, e)
    finally:
        try:
            mail.logout()
        except Exception:
            pass

    return messages_scanned, backfilled


def backfill_replies_for_db(db: Session) -> dict:
    """
    OAuth Gmail API thread match, then IMAP subject fallback for app-password students.
    """
    total_backfilled = 0
    messages_scanned = 0
    errors: list[str] = []
    student_ids_processed: set = set()

    oauth_configured = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)
    if oauth_configured and not _google_api_available():
        logger.warning(
            "replies_backfill: google-api-python-client not installed; skipping Gmail API backfill (IMAP fallback only)"
        )
        oauth_configured = False
    if not oauth_configured:
        errors.append("Gmail API backfill skipped: Google OAuth not configured")

    students = []
    if oauth_configured:
        # Lazy imports so missing optional Google deps never crash API startup.
        from googleapiclient.errors import HttpError  # type: ignore
        from app.services.gmail_sender import get_gmail_read_service

        students = (
            db.query(Student)
            .filter(
                Student.gmail_connected.is_(True),
                Student.gmail_refresh_token.isnot(None),
            )
            .all()
        )

    for student in students:
        token = (student.gmail_refresh_token or "").strip()
        if not token:
            continue
        student_email = (student.gmail_address or "").strip().lower()
        if not student_email:
            continue

        logger.debug("Processing student: %s", student.gmail_address)
        student_ids_processed.add(student.id)

        try:
            service = get_gmail_read_service(
                refresh_token=token,
                client_id=GOOGLE_CLIENT_ID,
                client_secret=GOOGLE_CLIENT_SECRET,
            )
        except Exception as e:
            errors.append(f"{student.id}: build service failed: {e}")
            logger.warning("replies_backfill service build failed for %s: %s", student.id, e)
            continue

        try:
            lst = (
                service.users()
                .messages()
                .list(userId="me", q=_GMAIL_QUERY, maxResults=_MAX_LIST_RESULTS)
                .execute()
            )
        except HttpError as e:
            errors.append(f"{student.id}: list messages failed: {e}")
            logger.warning("replies_backfill list failed for %s: %s", student.id, e)
            continue

        for mref in lst.get("messages") or []:
            mid = mref.get("id")
            if not mid:
                continue
            logger.debug("Message: %s", mid)
            try:
                msg = service.users().messages().get(userId="me", id=mid, format="full").execute()
            except HttpError as e:
                errors.append(f"{student.id}: get {mid}: {e}")
                continue

            messages_scanned += 1
            thread_id = msg.get("threadId")
            if not thread_id:
                continue

            campaign = (
                db.query(EmailCampaign)
                .filter(
                    EmailCampaign.student_id == student.id,
                    EmailCampaign.gmail_thread_id == str(thread_id),
                    EmailCampaign.reply_text.is_(None),
                )
                .first()
            )
            if not campaign:
                continue

            logger.debug("Thread matched: %s", thread_id)

            raw_from, sender_lower = extract_from(msg)
            if not sender_lower:
                continue
            if sender_lower == student_email:
                continue

            reply_body = extract_body(msg)
            if not reply_body:
                continue

            internal = msg.get("internalDate")
            if internal is None:
                continue
            try:
                timestamp_ms = int(internal)
            except (TypeError, ValueError):
                continue

            reply_dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)

            classify_src = f"{raw_from} {sender_lower}"
            result = apply_inbound_reply_to_campaign(
                db,
                campaign,
                reply_body[:_MAX_REPLY_TEXT_LEN],
                sender_for_classify=classify_src,
                reply_from_header=(raw_from[:512] if raw_from else None),
                when=reply_dt,
            )
            if result == "IGNORED":
                continue
            db.commit()
            total_backfilled += 1
            logger.debug("Backfilled: %s", campaign.id)

    imap_students = (
        db.query(Student)
        .filter(
            Student.app_password.isnot(None),
            Student.gmail_address.isnot(None),
        )
        .all()
    )
    imap_messages = 0
    imap_filled = 0
    for student in imap_students:
        if not (student.app_password or "").strip() or not (student.gmail_address or "").strip():
            continue
        m_cnt, b_cnt = _imap_backfill_for_student(db, student, errors)
        imap_messages += m_cnt
        imap_filled += b_cnt
        student_ids_processed.add(student.id)

    messages_scanned += imap_messages
    total_backfilled += imap_filled

    return {
        "ok": True,
        "students_scanned": len(student_ids_processed),
        "messages_scanned": messages_scanned,
        "backfilled": total_backfilled,
        "imap_messages_scanned": imap_messages,
        "imap_backfilled": imap_filled,
        "errors": errors[:20],
    }
