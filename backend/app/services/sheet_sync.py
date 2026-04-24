"""Export replies, failures, and bounces to Google Sheets (DB is source of truth; sheet is the mirror)."""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any
from datetime import datetime, timezone
import zlib

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models import EmailCampaign, Student, HRContact
import gspread

from app.services.google_sheets import get_sheet, get_worksheet, open_spreadsheet

logger = logging.getLogger(__name__)

# In-process marker for the last successful validated sync (best-effort; not persisted).
_last_success_at_utc: str | None = None
_advisory_lock_skip_count: int = 0
_last_advisory_lock_skip_at_utc: str | None = None

# Lag trend telemetry (best-effort; in-process only).
_last_pending_total_observed: int | None = None
_last_pending_increase_at_utc: str | None = None

# Step 1 follow-ups foundation: placeholder worksheet name (not used yet; no behavior change).
FOLLOWUPS_SHEET_TAB_NAME = "Follow-ups"

# Row 1 headers — must match append_rows column order in _sync_new_replies_impl (do not shorten).
_HEADER_REPLIES = [
    "student_name",
    "company",
    "hr_email",
    "campaign_id",
    "subject",
    "status",
    "email_type",
    "reply_status",
    "reply_preview",
    "reply_detected_at",
    "sequence_number",
    "outbound_message_id",
    "sent_at",
    "reply_from_header",
    "suppression_reason",
    "terminal_outcome",
    "audit_notes",
]
_HEADER_FAILURES = [
    "student_name",
    "company",
    "hr_email",
    "campaign_id",
    "subject",
    "status",
    "error",
    "sent_at",
    "email_type",
    "sequence_number",
    "suppression_reason",
    "terminal_outcome",
    "audit_notes",
]
_HEADER_BOUNCES = [
    "student_name",
    "company",
    "hr_email",
    "campaign_id",
    "subject",
    "reply_status",
    "delivery_status",
    "reply_preview",
    "sent_at",
    "email_type",
    "sequence_number",
    "suppression_reason",
    "terminal_outcome",
    "audit_notes",
]

# Sync pacing: safe mode avoids 429 during large rebuilds (smaller batches + pause between calls).
FAST_MODE = False
_SAFE_BATCH_SIZE = 20
_FAST_BATCH_SIZE = 80
_SAFE_INTER_BATCH_SLEEP_SEC = 2.0
_FAST_INTER_BATCH_SLEEP_SEC = 0.45
_APPEND_BATCH_MAX_ATTEMPTS = 10

# Re-entrant lock: rebuild_sheet_full() calls _sync_new_replies_impl() while holding the lock.
_sheet_sync_lock = threading.RLock()

_PG_ADVISORY_LOCK_KEY = int(zlib.crc32(b"sheet_sync_v1"))  # stable cross-process key


def _try_pg_advisory_lock(db: Session) -> bool:
    """
    Cross-process exclusion for Postgres deployments.
    Prevents duplicate appends when multiple API instances run schedulers.
    """
    try:
        if not db.bind or getattr(db.bind.dialect, "name", "") != "postgresql":
            return True
        got = db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _PG_ADVISORY_LOCK_KEY}).scalar()
        return bool(got)
    except Exception:
        logger.warning("sheet_sync: advisory lock failed; continuing without cross-process lock", exc_info=True)
        return True


def _release_pg_advisory_lock(db: Session) -> None:
    try:
        if not db.bind or getattr(db.bind.dialect, "name", "") != "postgresql":
            return
        db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _PG_ADVISORY_LOCK_KEY})
    except Exception:
        pass


def sheet_sync_status(db: Session) -> dict[str, Any]:
    """
    DB-backed lag status (safe; no secrets).
    Computes pending counts and oldest pending age based on DB export flags.
    """
    rep_pred = _reply_eligibility_predicate()
    bounce_pred = _bounce_eligibility_predicate()

    pending_replies = (
        db.query(func.count(EmailCampaign.id))
        .filter(rep_pred, EmailCampaign.exported_to_sheet.is_(False))
        .scalar()
        or 0
    )
    pending_failures = (
        db.query(func.count(EmailCampaign.id))
        .filter(EmailCampaign.status == "failed", EmailCampaign.exported_failure_sheet.is_(False))
        .scalar()
        or 0
    )
    pending_bounces = (
        db.query(func.count(EmailCampaign.id))
        .filter(bounce_pred, EmailCampaign.exported_bounce_sheet.is_(False))
        .scalar()
        or 0
    )
    pending_total = int(pending_replies) + int(pending_failures) + int(pending_bounces)

    now = datetime.now(timezone.utc)

    oldest_reply = (
        db.query(
            func.min(
                func.coalesce(
                    EmailCampaign.reply_detected_at,
                    EmailCampaign.replied_at,
                    EmailCampaign.created_at,
                )
            )
        )
        .filter(rep_pred, EmailCampaign.exported_to_sheet.is_(False))
        .scalar()
    )
    oldest_fail = (
        db.query(func.min(func.coalesce(EmailCampaign.sent_at, EmailCampaign.created_at)))
        .filter(EmailCampaign.status == "failed", EmailCampaign.exported_failure_sheet.is_(False))
        .scalar()
    )
    oldest_bounce = (
        db.query(func.min(func.coalesce(EmailCampaign.sent_at, EmailCampaign.created_at)))
        .filter(bounce_pred, EmailCampaign.exported_bounce_sheet.is_(False))
        .scalar()
    )

    oldest_candidates = [x for x in (oldest_reply, oldest_fail, oldest_bounce) if x is not None]
    oldest = min(oldest_candidates) if oldest_candidates else None
    if oldest is not None and getattr(oldest, "tzinfo", None) is None:
        oldest = oldest.replace(tzinfo=timezone.utc)
    age_sec = int(max(0.0, (now - oldest).total_seconds())) if oldest is not None else 0

    global _last_pending_total_observed, _last_pending_increase_at_utc
    if _last_pending_total_observed is None:
        _last_pending_total_observed = int(pending_total)
    else:
        if int(pending_total) > int(_last_pending_total_observed):
            _last_pending_increase_at_utc = now.isoformat()
        _last_pending_total_observed = int(pending_total)

    return {
        "pending_total": int(pending_total),
        "pending_replies": int(pending_replies),
        "pending_failures": int(pending_failures),
        "pending_bounces": int(pending_bounces),
        "oldest_pending_at_utc": oldest.isoformat() if oldest is not None else None,
        "oldest_pending_age_sec": int(age_sec) if pending_total else 0,
        "last_success_at_utc": _last_success_at_utc,
        "sync_lock_contention_count": int(_advisory_lock_skip_count),
        "last_lock_skip_at_utc": _last_advisory_lock_skip_at_utc,
        "last_pending_increase_at_utc": _last_pending_increase_at_utc,
    }


def _append_batch_with_retry(ws, batch: list[list]) -> None:
    """
    Single ``append_rows`` call for a full chunk. On success, DB flags are updated only by callers *after*
    this returns — so a failed batch is never treated as written. Retries only on HTTP 429 / rate strings.
    """
    if not batch:
        return
    last_exc: BaseException | None = None
    for attempt in range(_APPEND_BATCH_MAX_ATTEMPTS):
        try:
            ws.append_rows(batch, value_input_option="USER_ENTERED")
            logger.info(f"Batch success: {len(batch)} rows")
            return
        except Exception as e:
            last_exc = e
            if "429" in str(e):
                sleep_time = (2**attempt) + random.uniform(0, 2)
                logger.warning(
                    "sheet_append: 429 on batch len=%s attempt=%s/%s sleep=%.2fs",
                    len(batch),
                    attempt + 1,
                    _APPEND_BATCH_MAX_ATTEMPTS,
                    sleep_time,
                )
                time.sleep(sleep_time)
            else:
                raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("append_rows failed after retries")


def append_rows_batched_with_retry(
    ws,
    rows: list[list],
    *,
    batch_size: int | None = None,
) -> None:
    """
    Split into chunks; each chunk uses ``_append_batch_with_retry`` (429 retries, then raise — no silent skip).

    When ``FAST_MODE`` is False (default): 20 rows per batch, 2s sleep after each successful batch.
    When ``FAST_MODE`` is True: 50–100 rows per batch (default 80), short pause between batches.
    """
    if not rows:
        return
    if FAST_MODE:
        bs = batch_size if batch_size is not None else _FAST_BATCH_SIZE
        bs = max(50, min(100, int(bs)))
        inter_sleep = _FAST_INTER_BATCH_SLEEP_SEC
        log_fixed_2s = False
    else:
        bs = batch_size if batch_size is not None else _SAFE_BATCH_SIZE
        bs = max(1, min(_SAFE_BATCH_SIZE, int(bs)))
        inter_sleep = _SAFE_INTER_BATCH_SLEEP_SEC
        log_fixed_2s = True

    total = len(rows)
    for start in range(0, total, bs):
        chunk = rows[start : start + bs]
        _append_batch_with_retry(ws, chunk)
        if log_fixed_2s:
            logger.info(f"Batch completed, sleeping 2s")
        time.sleep(inter_sleep)


def _norm_sheet_id(value: Any) -> str:
    """Normalize email_campaign id as stored in sheet column ``campaign_id`` (UUID string)."""
    return str(value or "").strip().lower()


def _sheet_campaign_ids(ws, id_col: int = 3) -> set[str]:
    """Non-empty normalized ids from column ``id_col`` (0-based), excluding header row."""
    try:
        rows = ws.get_all_values()
    except Exception:
        return set()
    if len(rows) < 2:
        return set()
    out: set[str] = set()
    for row in rows[1:]:
        if len(row) <= id_col:
            continue
        rid = _norm_sheet_id(row[id_col])
        if rid:
            out.add(rid)
    return out


def _dedupe_sheet_tab_if_needed(ws, canonical_header: list[str], *, id_col: int = 3) -> int:
    """
    If the same campaign id appears more than once (column holds ``EmailCampaign.id``),
    rewrite the tab: clear + canonical header + one data row per id (first row wins).

    Returns the number of duplicate *data* rows removed (0 if already unique).
    """
    try:
        raw = ws.get_all_values()
    except Exception:
        return 0
    if not raw:
        return 0
    hlen = len(canonical_header)
    body = raw[1:] if (raw[0] and any(str(c).strip() for c in raw[0])) else raw
    seen: set[str] = set()
    kept: list[list[str]] = []
    dups = 0
    for row in body:
        r = [str(c) if c is not None else "" for c in row]
        if len(r) < hlen:
            r = r + [""] * (hlen - len(r))
        else:
            r = r[:hlen]
        rid = _norm_sheet_id(r[id_col]) if id_col < len(r) else ""
        if rid:
            if rid in seen:
                dups += 1
                continue
            seen.add(rid)
        kept.append(r)
    if dups == 0:
        return 0
    logger.warning(
        "sheet_sync: deduping tab %r — removing %s duplicate data row(s) (same id column)",
        getattr(ws, "title", "?"),
        dups,
    )
    clear_worksheet(ws, canonical_header)
    if kept:
        append_rows_batched_with_retry(ws, kept, batch_size=min(500, max(50, len(kept))))
    return dups


def _sheet_data_row_count(ws) -> int:
    """Data rows only (subtract header row if row 1 looks like a header)."""
    try:
        rows = ws.get_all_values()
    except Exception:
        return 0
    if not rows:
        return 0
    if rows[0] and any(str(c).strip() for c in rows[0]):
        return max(0, len(rows) - 1)
    return len(rows)


def clear_worksheet(ws, header: list[str]) -> None:
    """
    Wipe the tab completely, then write row 1 headers only.
    Used in rebuild before any data append so old rows cannot linger (delete_rows can miss quota edge cases).
    """
    ws.clear()
    ws.append_row(header)


def _audit_notes(c: EmailCampaign) -> str:
    parts = [
        f"status={c.status or ''}",
        f"delivery={c.delivery_status or ''}",
        f"failure_type={c.failure_type or ''}",
    ]
    err = (c.error or "").replace("\n", " ")[:400]
    if err:
        parts.append(f"error={err}")
    return " | ".join(parts)[:1500]


def _student_hr_row(db, c: EmailCampaign):
    student_name = "N/A"
    if c.student_id:
        st = db.query(Student).filter(Student.id == c.student_id).first()
        if st:
            student_name = getattr(st, "name", "N/A")
    company = "N/A"
    hr_email = ""
    if c.hr_id:
        hr = db.query(HRContact).filter(HRContact.id == c.hr_id).first()
        if hr:
            company = getattr(hr, "company", "N/A") or "N/A"
            hr_email = getattr(hr, "email", "") or ""
    return student_name, company, hr_email


def _ensure_header(ws, header: list[str]) -> None:
    try:
        first = ws.row_values(1)
    except Exception:
        first = []
    if not first or not any(str(x).strip() for x in first):
        ws.insert_row(header, 1)


def _has_inbound_reply_body():
    return or_(
        and_(
            EmailCampaign.reply_text.isnot(None),
            func.length(func.trim(EmailCampaign.reply_text)) > 0,
        ),
        and_(
            EmailCampaign.reply_snippet.isnot(None),
            func.length(func.trim(EmailCampaign.reply_snippet)) > 0,
        ),
    )


def _reply_eligibility_predicate():
    normalized_reply = and_(
        EmailCampaign.reply_status.isnot(None),
        EmailCampaign.reply_status.notin_(
            ("BOUNCED", "BLOCKED", "TEMP_FAIL", "BOUNCE")
        ),
        _has_inbound_reply_body(),
    )
    legacy_reply = and_(
        EmailCampaign.reply_status.is_(None),
        EmailCampaign.status == "replied",
        EmailCampaign.replied.is_(True),
        _has_inbound_reply_body(),
    )
    return and_(
        or_(
            EmailCampaign.replied.is_(True),
            EmailCampaign.status == "replied",
        ),
        or_(normalized_reply, legacy_reply),
    )


def _bounce_eligibility_predicate():
    return EmailCampaign.reply_status.in_(("BOUNCED", "BLOCKED", "BOUNCE"))


def _validate_mirror_counts(
    db: Session,
    replies_ws,
    failures_ws,
    bounces_ws,
) -> dict[str, Any]:
    """
    After sync: eligible DB row counts should match sheet data rows, and all eligible rows
    should have export flags True.
    """
    rep_pred = _reply_eligibility_predicate()
    replies_eligible = db.query(EmailCampaign).filter(rep_pred).count()
    replies_exported = (
        db.query(EmailCampaign)
        .filter(rep_pred, EmailCampaign.exported_to_sheet.is_(True))
        .count()
    )
    replies_sheet = _sheet_data_row_count(replies_ws)

    failed_total = db.query(EmailCampaign).filter(EmailCampaign.status == "failed").count()
    failed_exported = (
        db.query(EmailCampaign)
        .filter(
            EmailCampaign.status == "failed",
            EmailCampaign.exported_failure_sheet.is_(True),
        )
        .count()
    )
    failures_sheet = _sheet_data_row_count(failures_ws)

    bounce_pred = _bounce_eligibility_predicate()
    bounces_eligible = db.query(EmailCampaign).filter(bounce_pred).count()
    bounces_exported = (
        db.query(EmailCampaign)
        .filter(bounce_pred, EmailCampaign.exported_bounce_sheet.is_(True))
        .count()
    )
    bounces_sheet = _sheet_data_row_count(bounces_ws)

    out = {
        "replies": {
            "db_eligible": replies_eligible,
            "db_exported_flag": replies_exported,
            "sheet_rows": replies_sheet,
            "ok": replies_eligible == replies_exported == replies_sheet,
        },
        "failures": {
            "db_failed_rows": failed_total,
            "db_exported_flag": failed_exported,
            "sheet_rows": failures_sheet,
            "ok": failed_total == failed_exported == failures_sheet,
        },
        "bounces": {
            "db_eligible": bounces_eligible,
            "db_exported_flag": bounces_exported,
            "sheet_rows": bounces_sheet,
            "ok": bounces_eligible == bounces_exported == bounces_sheet,
        },
    }
    out["all_ok"] = (
        out["replies"]["ok"] and out["failures"]["ok"] and out["bounces"]["ok"]
    )
    return out


def _reconcile_export_flags_if_row_on_sheet(
    db: Session,
    ws,
    *,
    tab_label: str,
    id_col: int,
    base_filter,
    flag_name: str,
) -> int:
    """
    If the sheet already contains a row for this campaign id but the DB export flag is still
    false (e.g. duplicate appends in the past, partial failure, or multi-process race), set the
    flag true without appending again.
    """
    on_sheet = _sheet_campaign_ids(ws, id_col)
    if not on_sheet:
        return 0
    q = db.query(EmailCampaign).filter(base_filter, getattr(EmailCampaign, flag_name).is_(False))
    n = 0
    for c in q:
        if _norm_sheet_id(c.id) in on_sheet:
            setattr(c, flag_name, True)
            db.add(c)
            n += 1
    if n:
        logger.info(
            "sheet_sync %s: reconciled export flags for %s row(s) already present on sheet",
            tab_label,
            n,
        )
    return n


def sync_new_replies(db: Session) -> dict[str, Any] | None:
    """
    Thread-safe export. Returns validation dict from _validate_mirror_counts, or None on hard failure
    before validation.
    """
    with _sheet_sync_lock:
        got_lock = False
        try:
            got_lock = _try_pg_advisory_lock(db)
            if not got_lock:
                global _advisory_lock_skip_count, _last_advisory_lock_skip_at_utc
                _advisory_lock_skip_count = int(_advisory_lock_skip_count) + 1
                _last_advisory_lock_skip_at_utc = datetime.now(timezone.utc).isoformat()
                logger.info("sheet_sync: skip run (another instance holds advisory lock)")
                return None
            logger.info("sheet_sync: run starting (lock acquired)")
            _sync_new_replies_impl(db)
            replies_ws = get_sheet("Replies")
            failures_ws = get_sheet("Failures")
            bounces_ws = get_sheet("Bounces")
            validation = _validate_mirror_counts(db, replies_ws, failures_ws, bounces_ws)
            if validation["all_ok"]:
                global _last_success_at_utc
                _last_success_at_utc = datetime.now(timezone.utc).isoformat()
                logger.info(
                    "sheet_sync: mirror validation OK — Replies %s, Failures %s, Bounces %s",
                    validation["replies"]["sheet_rows"],
                    validation["failures"]["sheet_rows"],
                    validation["bounces"]["sheet_rows"],
                )
            else:
                logger.error(
                    "sheet_sync: mirror validation MISMATCH — detail=%s",
                    validation,
                )
            return validation
        except Exception:
            db.rollback()
            logger.exception("sheet_sync: run failed (session rolled back)")
            return None
        finally:
            if got_lock:
                _release_pg_advisory_lock(db)


def _sync_new_replies_impl(db: Session) -> None:
    replies_sheet = get_sheet("Replies")
    failures_sheet = get_sheet("Failures")
    bounces_sheet = get_sheet("Bounces")

    _ensure_header(replies_sheet, _HEADER_REPLIES)
    _ensure_header(failures_sheet, _HEADER_FAILURES)
    _ensure_header(bounces_sheet, _HEADER_BOUNCES)

    # Repair duplicate sheet rows (same EmailCampaign.id) and align DB flags with reality.
    _dedupe_sheet_tab_if_needed(replies_sheet, _HEADER_REPLIES, id_col=3)
    _dedupe_sheet_tab_if_needed(failures_sheet, _HEADER_FAILURES, id_col=3)
    _dedupe_sheet_tab_if_needed(bounces_sheet, _HEADER_BOUNCES, id_col=3)

    rep_pred = _reply_eligibility_predicate()
    bounce_pred = _bounce_eligibility_predicate()
    r_rec = _reconcile_export_flags_if_row_on_sheet(
        db,
        replies_sheet,
        tab_label="Replies",
        id_col=3,
        base_filter=rep_pred,
        flag_name="exported_to_sheet",
    )
    f_rec = _reconcile_export_flags_if_row_on_sheet(
        db,
        failures_sheet,
        tab_label="Failures",
        id_col=3,
        base_filter=EmailCampaign.status == "failed",
        flag_name="exported_failure_sheet",
    )
    b_rec = _reconcile_export_flags_if_row_on_sheet(
        db,
        bounces_sheet,
        tab_label="Bounces",
        id_col=3,
        base_filter=bounce_pred,
        flag_name="exported_bounce_sheet",
    )
    if r_rec or f_rec or b_rec:
        db.commit()

    # --- Replies: ONLY exported_to_sheet == False (duplicate guard) ---
    replies_total_eligible = db.query(EmailCampaign).filter(rep_pred).count()
    replies_skipped = (
        db.query(EmailCampaign)
        .filter(rep_pred, EmailCampaign.exported_to_sheet.is_(True))
        .count()
    )
    reply_rows = (
        db.query(EmailCampaign)
        .filter(rep_pred, EmailCampaign.exported_to_sheet.is_(False))
        .all()
    )
    logger.info(
        "sheet_sync Replies: eligible=%s skipped_already_exported=%s fetched_for_insert=%s",
        replies_total_eligible,
        replies_skipped,
        len(reply_rows),
    )

    pending_reply: list[tuple[EmailCampaign, list]] = []
    for c in reply_rows:
        if c.exported_to_sheet:
            continue
        student_name, company, hr_email = _student_hr_row(db, c)
        pending_reply.append(
            (
                c,
                [
                    student_name,
                    company,
                    hr_email,
                    str(c.id),
                    (c.subject or "")[:500],
                    c.status or "",
                    c.email_type or "",
                    c.reply_status or "",
                    (c.reply_text or c.reply_snippet or "").replace("\n", " ")[:500],
                    str(c.reply_detected_at or c.replied_at or ""),
                    str(c.sequence_number or ""),
                    str(c.message_id or ""),
                    str(c.sent_at or ""),
                    (c.reply_from or "")[:500],
                    (c.suppression_reason or "")[:500],
                    (c.terminal_outcome or "")[:64],
                    _audit_notes(c),
                ],
            )
        )

    if pending_reply:
        try:
            append_rows_batched_with_retry(replies_sheet, [r for _, r in pending_reply])
            for c, _ in pending_reply:
                if not c.exported_to_sheet:
                    c.exported_to_sheet = True
                    db.add(c)
            logger.info(
                "sheet_sync Replies: inserted_rows=%s",
                len(pending_reply),
            )
            db.commit()
            logger.info("sheet_sync Replies: DB commit OK")
        except Exception as e:
            logger.error("sheet_sync Replies: batch failed, rolling back session: %s", e)
            db.rollback()
            raise

    # --- Failures: query already restricts exported_failure_sheet == False ---
    failed_total = db.query(EmailCampaign).filter(EmailCampaign.status == "failed").count()
    failed_campaigns = (
        db.query(EmailCampaign)
        .filter(
            EmailCampaign.status == "failed",
            EmailCampaign.exported_failure_sheet.is_(False),
        )
        .all()
    )
    failed_skipped = failed_total - len(failed_campaigns)
    logger.info(
        "sheet_sync Failures: failed_total=%s skipped_already_exported=%s fetched_for_insert=%s",
        failed_total,
        failed_skipped,
        len(failed_campaigns),
    )

    pending_fail: list[tuple[EmailCampaign, list]] = []
    for c in failed_campaigns:
        if c.exported_failure_sheet:
            continue
        student_name, company, hr_email = _student_hr_row(db, c)
        pending_fail.append(
            (
                c,
                [
                    student_name,
                    company,
                    hr_email,
                    str(c.id),
                    (c.subject or "")[:500],
                    c.status or "",
                    (c.error or "")[:1000],
                    str(c.sent_at or ""),
                    c.email_type or "",
                    str(c.sequence_number or ""),
                    (c.suppression_reason or "")[:500],
                    (c.terminal_outcome or "")[:64],
                    _audit_notes(c),
                ],
            )
        )

    if pending_fail:
        try:
            append_rows_batched_with_retry(failures_sheet, [r for _, r in pending_fail])
            for c, _ in pending_fail:
                if not c.exported_failure_sheet:
                    c.exported_failure_sheet = True
                    db.add(c)
            logger.info("sheet_sync Failures: inserted_rows=%s", len(pending_fail))
            db.commit()
            logger.info("sheet_sync Failures: DB commit OK")
        except Exception as e:
            logger.error("sheet_sync Failures: batch failed, rolling back session: %s", e)
            db.rollback()
            raise

    # --- Bounces: ONLY exported_bounce_sheet == False ---
    bounces_total = db.query(EmailCampaign).filter(bounce_pred).count()
    bounces_skipped = (
        db.query(EmailCampaign)
        .filter(bounce_pred, EmailCampaign.exported_bounce_sheet.is_(True))
        .count()
    )
    bounce_rows = (
        db.query(EmailCampaign)
        .filter(bounce_pred, EmailCampaign.exported_bounce_sheet.is_(False))
        .all()
    )
    logger.info(
        "sheet_sync Bounces: eligible=%s skipped_already_exported=%s fetched_for_insert=%s",
        bounces_total,
        bounces_skipped,
        len(bounce_rows),
    )

    pending_bounce: list[tuple[EmailCampaign, list]] = []
    for c in bounce_rows:
        if c.exported_bounce_sheet:
            continue
        student_name, company, hr_email = _student_hr_row(db, c)
        pending_bounce.append(
            (
                c,
                [
                    student_name,
                    company,
                    hr_email,
                    str(c.id),
                    (c.subject or "")[:500],
                    c.reply_status or "",
                    c.delivery_status or "",
                    (c.reply_text or c.reply_snippet or "").replace("\n", " ")[:500],
                    str(c.sent_at or c.replied_at or ""),
                    c.email_type or "",
                    str(c.sequence_number or ""),
                    (c.suppression_reason or "")[:500],
                    (c.terminal_outcome or "")[:64],
                    _audit_notes(c),
                ],
            )
        )

    if pending_bounce:
        try:
            append_rows_batched_with_retry(bounces_sheet, [r for _, r in pending_bounce])
            for c, _ in pending_bounce:
                if not c.exported_bounce_sheet:
                    c.exported_bounce_sheet = True
                    db.add(c)
            logger.info("sheet_sync Bounces: inserted_rows=%s", len(pending_bounce))
            db.commit()
            logger.info("sheet_sync Bounces: DB commit OK")
        except Exception as e:
            logger.error("sheet_sync Bounces: batch failed, rolling back session: %s", e)
            db.rollback()
            raise

    logger.info("sheet_sync: all tabs processed")


def rebuild_sheet_full(db: Session, *, include_demo: bool = False) -> dict[str, Any]:
    """
    Safe full rebuild: clear Replies / Failures / Bounces (keep headers), reset all three
    export flags for **every** email_campaign row, then sync. Blocked HRs tab is untouched.

    Resets export flags on **all** ``email_campaigns`` rows so cleared tabs refill completely
    (avoids stale ``exported_*=True`` rows missing from the sheet after a wipe).

    ``include_demo`` is kept for call-site compatibility; full rebuild always covers all rows.
    """
    _ = include_demo
    with _sheet_sync_lock:
        logger.info("sheet_sync rebuild_sheet_full: starting")
        ids = [row[0] for row in db.query(EmailCampaign.id).all()]
        logger.info("sheet_sync rebuild_sheet_full: resetting export flags for %s campaigns", len(ids))
        chunk = 400
        for i in range(0, len(ids), chunk):
            part = ids[i : i + chunk]
            db.query(EmailCampaign).filter(EmailCampaign.id.in_(part)).update(
                {
                    "exported_to_sheet": False,
                    "exported_failure_sheet": False,
                    "exported_bounce_sheet": False,
                },
                synchronize_session=False,
            )
        db.commit()

        logger.info("Sheets cleared before rebuild")
        ss = open_spreadsheet()
        for title, hdr in (
            ("Replies", _HEADER_REPLIES),
            ("Failures", _HEADER_FAILURES),
            ("Bounces", _HEADER_BOUNCES),
        ):
            try:
                ws = ss.worksheet(title)
            except gspread.WorksheetNotFound:
                ws = get_worksheet(title)
            clear_worksheet(ws, hdr)
            logger.info("sheet_sync rebuild_sheet_full: wiped tab %r (clear + header row)", title)

        _sync_new_replies_impl(db)

        replies_ws = get_sheet("Replies")
        failures_ws = get_sheet("Failures")
        bounces_ws = get_sheet("Bounces")
        validation = _validate_mirror_counts(db, replies_ws, failures_ws, bounces_ws)
        if validation["all_ok"]:
            logger.info("sheet_sync rebuild_sheet_full: mirror validation OK — %s", validation)
        else:
            logger.error("sheet_sync rebuild_sheet_full: mirror validation MISMATCH — %s", validation)
        return validation


def test_sheet():
    ws = get_sheet()
    logger.debug("sheet ok: %s", getattr(ws, "title", ws))
