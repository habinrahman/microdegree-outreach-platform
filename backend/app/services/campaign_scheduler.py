"""Background scheduler: send due campaigns (IST 9:30–5:30 for cron; admin run_once can bypass).

Primary: Gmail API (OAuth refresh token).
Fallback (local/dev): Gmail SMTP using app password (legacy).
"""
import logging
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from smtplib import SMTPAuthenticationError
from typing import Any, Callable

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.config import (
    SEND_START_HOUR,
    SEND_START_MINUTE,
    SEND_END_HOUR,
    SEND_END_MINUTE,
    SEND_DELAY_MIN,
    SEND_DELAY_MAX,
    ENFORCE_IST_SEND_WINDOW,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
)
# SCHEDULER_USE_PRIORITY_QUEUE (app.config, default off): reserved for Phase 2+ optional reorder
# of `due` via priority_queue_engine — not read here in Phase 1.
from app.services.hr_health_scoring import (
    compute_health_for_hr_ids,
    parse_scheduler_min_hr_tier,
    tier_at_or_above,
)
from app.database.config import SessionLocal
from app.models import EmailCampaign, HRContact, Campaign
from app.models.student import Student
from app.workers.email_worker import process_email_campaign
from app.utils.datetime_utils import ensure_utc
from app.services.campaign_lifecycle import assert_legal_email_campaign_transition
from app.services.deliverability_layer import scheduler_should_pause_sends
from app.services.sequence_send_gate import scheduler_may_send_campaign

logger = logging.getLogger(__name__)

job_lock = Lock()

# Single BackgroundScheduler instance; avoid duplicate starts on reload / double lifespan.
_scheduler = None


@dataclass
class _JobMetric:
    last_started_at_utc: str | None = None
    last_finished_at_utc: str | None = None
    last_duration_ms: int | None = None
    last_ok: bool | None = None
    last_error: str | None = None


_job_metrics: dict[str, _JobMetric] = {}
_scheduler_metrics: dict[str, Any] = {
    "last_event_at_utc": None,
    "missed_runs": 0,
    "job_errors": 0,
}


def scheduler_metrics_snapshot() -> dict[str, Any]:
    """Safe, JSON-friendly scheduler metrics (no secrets)."""
    return {
        "running": bool(_scheduler is not None and getattr(_scheduler, "running", False)),
        "jobs": {k: vars(v) for k, v in _job_metrics.items()},
        **_scheduler_metrics,
    }


def _timed_job(job_id: str, fn: Callable[[], Any]) -> Callable[[], Any]:
    def _wrapped():
        m = _job_metrics.setdefault(job_id, _JobMetric())
        start = datetime.now(timezone.utc)
        m.last_started_at_utc = start.isoformat()
        t0 = time.time()
        try:
            out = fn()
            m.last_ok = True
            m.last_error = None
            return out
        except Exception as e:
            m.last_ok = False
            m.last_error = str(e)[:500]
            raise
        finally:
            end = datetime.now(timezone.utc)
            m.last_finished_at_utc = end.isoformat()
            m.last_duration_ms = int(max(0.0, (time.time() - t0) * 1000.0))
            if m.last_duration_ms is not None and m.last_duration_ms >= 20_000:
                logger.warning("scheduler job slow: %s duration_ms=%s", job_id, m.last_duration_ms)

    return _wrapped

# Asia/Kolkata fixed offset (no DST)
IST = timezone(timedelta(hours=5, minutes=30))


def _now_ist() -> datetime:
    """Current time in IST (timezone-aware)."""
    return datetime.now(IST)


def _is_in_sending_window(dt: datetime) -> bool:
    """True if time (IST) is between 9:30 AM and 5:30 PM."""
    minutes = dt.hour * 60 + dt.minute
    start = SEND_START_HOUR * 60 + SEND_START_MINUTE
    end = SEND_END_HOUR * 60 + SEND_END_MINUTE
    return start <= minutes <= end


def _scheduled_at_as_utc(dt, now_utc: datetime) -> datetime:
    """Compare scheduled_at to now_utc; treat naive DB datetimes as UTC."""
    if dt is None:
        return now_utc
    if getattr(dt, "tzinfo", None) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_hr_paused(db: Session, hr_id, now_utc: datetime) -> bool:
    """True if HR is paused (not_hiring) and paused_until is still in the future."""
    hr = db.query(HRContact).filter(HRContact.id == hr_id).first()
    if not hr or hr.status != "paused":
        return False
    if getattr(hr, "paused_until", None) is None:
        return True
    pu = hr.paused_until
    if pu.tzinfo is None:
        pu = pu.replace(tzinfo=timezone.utc)
    return pu > now_utc


def run_campaign_job(
    *,
    ignore_window: bool = False,
    ignore_scheduled_time: bool = False,
    skip_delay: bool = False,
    limit: int | None = None,
    student_id: str | None = None,
    hr_id: str | None = None,
    ignore_deliverability_pause: bool = False,
) -> dict:
    """
    Fetch due campaigns, respect IST window unless ignore_window=True (admin dry-run),
    send via worker; release stuck processing rows after 10 minutes.
    """
    acquired = job_lock.acquire(blocking=False)
    if not acquired:
        return {"sent": 0, "failed": 0, "skipped": 0, "errors": []}
    db = None
    try:
        db = SessionLocal()
        start_time = time.time()
        now_utc = datetime.now(timezone.utc)

        if not ignore_deliverability_pause:
            sp = scheduler_should_pause_sends(db)
            if sp.get("pause"):
                return {
                    "sent": 0,
                    "failed": 0,
                    "skipped": 0,
                    "errors": [],
                    "note": "deliverability_global_pause",
                    "deliverability": sp,
                }

        if (
            ENFORCE_IST_SEND_WINDOW
            and not ignore_window
            and not _is_in_sending_window(_now_ist())
        ):
            return {"sent": 0, "failed": 0, "skipped": 0, "errors": [], "note": "outside_ist_send_window"}

        logger.debug("Sending due campaigns")

        # Self-heal: recover campaigns stuck in processing (crash mid-flight).
        # IMPORTANT idempotency safety: do NOT auto-resend unknown-outcome sends.
        # If the worker crashed after SMTP accepted the message (but before DB commit),
        # resetting to scheduled could send a duplicate.
        proc_stale = now_utc - timedelta(minutes=10)
        # ORM path (was bulk UPDATE): attach ``terminal_outcome`` per pair for analytics.
        stale_processing = (
            db.query(EmailCampaign)
            .filter(
                EmailCampaign.status == "processing",
                EmailCampaign.processing_started_at.isnot(None),
                EmailCampaign.processing_started_at < proc_stale,
            )
            .all()
        )
        if stale_processing:
            from app.services.campaign_terminal_outcomes import (
                PAUSED_UNKNOWN_OUTCOME,
                record_pair_terminal_outcome,
            )

            for c in stale_processing:
                assert_legal_email_campaign_transition(
                    c.status, "paused", context="campaign_scheduler/stale-processing-pause"
                )
                c.status = "paused"
                c.processing_started_at = None
                c.processing_lock_acquired_at = None
                c.error = "stale_processing_unknown_outcome: processing >10m; paused to prevent duplicate send"
                db.add(c)
                record_pair_terminal_outcome(
                    db,
                    student_id=c.student_id,
                    hr_id=c.hr_id,
                    outcome=PAUSED_UNKNOWN_OUTCOME,
                    tag_campaign=c,
                )
            db.commit()
            logger.warning(
                "Paused %s campaign(s) from stale processing state (unknown outcome; idempotency safety)",
                len(stale_processing),
            )

        # Outage-safe: flag queueable rows far past scheduled_at (never auto-expire for lag).
        try:
            lag_m = int((os.getenv("SEQUENCE_OVERDUE_LAG_MINUTES") or "1440").strip() or "1440")
            lag_m = max(1, lag_m)
            cutoff_naive = (now_utc - timedelta(minutes=lag_m)).replace(tzinfo=None)
            overdue_rows = (
                db.query(EmailCampaign)
                .filter(
                    EmailCampaign.status == "scheduled",
                    EmailCampaign.scheduled_at < cutoff_naive,
                    EmailCampaign.overdue_late.is_(False),
                )
                .limit(5000)
                .all()
            )
            for oc in overdue_rows:
                oc.overdue_late = True
                if oc.overdue_first_seen_at is None:
                    oc.overdue_first_seen_at = cutoff_naive
                db.add(oc)
            if overdue_rows:
                db.commit()
                logger.info("Marked %s scheduled campaign(s) overdue_late (cutoff lag_minutes=%s)", len(overdue_rows), lag_m)
        except Exception as e:
            logger.debug("overdue_late marking skipped: %s", e)

        # Backward compat: older code can leave rows as pending.
        # Normalize pending -> scheduled (immediately due) so the scheduler uses a single deterministic fetch path.
        # Bulk transition: see app.services.campaign_lifecycle.BULK_PENDING_TO_SCHEDULED
        normalized = (
            db.query(EmailCampaign)
            .filter(EmailCampaign.status == "pending")
            .update({"status": "scheduled"}, synchronize_session=False)
        )
        if normalized:
            db.commit()

        # Deterministic selection + concurrency safety:
        # - only scheduled rows due now
        # - not replied
        # - row-level lock: SELECT ... FOR UPDATE SKIP LOCKED (Postgres only)
        base = (
            db.query(EmailCampaign)
            .join(HRContact, EmailCampaign.hr_id == HRContact.id)
            .join(Student, EmailCampaign.student_id == Student.id)
            .filter(
                EmailCampaign.status == "scheduled",
                EmailCampaign.replied.is_(False),
                HRContact.is_valid.is_(True),
                Student.app_password.isnot(None),
                or_(
                    Student.email_health_status.is_(None),
                    Student.email_health_status.in_(("healthy", "warning")),
                ),
            )
            .order_by(EmailCampaign.scheduled_at.asc(), EmailCampaign.created_at.asc())
        )
        if not ignore_scheduled_time:
            base = base.filter(EmailCampaign.scheduled_at <= now_utc)
        if student_id is not None:
            base = base.filter(EmailCampaign.student_id == student_id)
        if hr_id is not None:
            base = base.filter(EmailCampaign.hr_id == hr_id)
        base = base.limit(50)

        if db.bind and getattr(db.bind.dialect, "name", "") == "postgresql":
            base = base.with_for_update(skip_locked=True)

        try:
            due = base.all()
        except ProgrammingError as e:
            # Common during first boot / partial migrations: tables or columns may not exist yet.
            msg = str(e).lower()
            if "does not exist" in msg or "undefinedtable" in msg or "undefinedcolumn" in msg:
                logger.warning("Scheduler skipped (schema not ready yet): %s", e)
                try:
                    db.rollback()
                except Exception:
                    pass
                return {"sent": 0, "failed": 0, "skipped": 0, "errors": [{"error": "schema_not_ready"}]}
            raise

        logger.debug("Scheduler picked: %s", len(due))
        due = [c for c in due if not _is_hr_paused(db, c.hr_id, now_utc)]

        min_hr_tier = parse_scheduler_min_hr_tier()
        if min_hr_tier and due:
            hr_ids_sched = list({c.hr_id for c in due})
            bundles = compute_health_for_hr_ids(db, hr_ids_sched)
            before_n = len(due)
            due = [
                c
                for c in due
                if tier_at_or_above(str((bundles.get(c.hr_id) or {}).get("tier") or "D"), min_hr_tier)
            ]
            if before_n > len(due):
                logger.debug("HR tier filter (%s): %s -> %s campaigns", min_hr_tier, before_n, len(due))

        # Skip students hit by Gmail SMTP auth block in the last 10 minutes
        cooldown_cutoff = now_utc - timedelta(minutes=10)
        cooldown_student_ids = {
            sid
            for (sid,) in db.query(EmailCampaign.student_id)
            .filter(
                EmailCampaign.status == "paused",
                EmailCampaign.error == "gmail_auth_block",
                EmailCampaign.sent_at.isnot(None),
                EmailCampaign.sent_at >= cooldown_cutoff,
            )
            .distinct()
            .all()
        }
        due = [c for c in due if c.student_id not in cooldown_student_ids]

        gated: list[EmailCampaign] = []
        for c in due:
            ok, reason = scheduler_may_send_campaign(
                db, c, now_utc=now_utc, ignore_due_time=bool(ignore_scheduled_time)
            )
            if ok:
                gated.append(c)
            else:
                logger.debug("scheduler gate skip: campaign=%s reason=%s", c.id, reason)
        due = gated

        # Acquire processing lock (DB is the single source of truth).
        # Commit immediately so other scheduler instances won't pick the same rows.
        lock_time = ensure_utc(now_utc)
        to_send: list[EmailCampaign] = []
        for c in due:
            if c.status != "scheduled":
                continue
            # Overdue rows remain sendable after outages (no auto-expire by age).
            assert_legal_email_campaign_transition(c.status, "processing", context="campaign_scheduler/claim-send")
            c.status = "processing"
            c.processing_started_at = lock_time
            c.processing_lock_acquired_at = lock_time
            db.add(c)
            to_send.append(c)
        db.commit()

        if limit is not None:
            to_send = to_send[: max(0, int(limit))]

        to_send = to_send[:50]
        logger.debug("LOCKED FOR SEND: %s", len(to_send))

        sent = 0
        failed = 0
        skipped = 0
        errors: list[dict] = []

        for campaign in to_send:
            if time.time() - start_time > 50:
                break
            # Campaigns in to_send are already locked (status=processing) + committed.
            if campaign.status != "processing":
                skipped += 1
                continue

            student = db.query(Student).filter(Student.id == campaign.student_id).first()
            if not student:
                assert_legal_email_campaign_transition(
                    campaign.status, "failed", context="campaign_scheduler/missing-student"
                )
                campaign.status = "failed"
                campaign.error = "Missing student or HR record"
                campaign.sent_at = ensure_utc(datetime.now(timezone.utc))
                campaign.processing_started_at = None
                campaign.processing_lock_acquired_at = None
                db.commit()
                failed += 1
                continue

            hr = (
                db.query(HRContact)
                .filter(HRContact.id == campaign.hr_id, HRContact.is_valid.is_(True))
                .first()
            )
            if not hr:
                if db.query(HRContact.id).filter(HRContact.id == campaign.hr_id).first():
                    logger.info("Skipped invalid HR")
                    assert_legal_email_campaign_transition(
                        campaign.status, "cancelled", context="campaign_scheduler/invalid-hr-skip"
                    )
                    campaign.status = "cancelled"
                    campaign.error = "skipped_invalid_hr"
                    campaign.processing_started_at = None
                    campaign.processing_lock_acquired_at = None
                    db.add(campaign)
                    db.commit()
                    skipped += 1
                    continue
                assert_legal_email_campaign_transition(
                    campaign.status, "failed", context="campaign_scheduler/missing-hr-record"
                )
                campaign.status = "failed"
                campaign.error = "Missing student or HR record"
                campaign.sent_at = ensure_utc(datetime.now(timezone.utc))
                campaign.processing_started_at = None
                campaign.processing_lock_acquired_at = None
                db.commit()
                failed += 1
                continue

            # No additional duplicate filter here: the DB row lock prevents the same campaign row
            # from being processed twice concurrently. Cross-row duplicate rules belong upstream
            # (campaign generation / scheduling policy), not in the hot send loop.

            if campaign.campaign_id:
                campaign_group = db.query(Campaign).filter(Campaign.id == campaign.campaign_id).first()
                if campaign_group and campaign_group.status == "paused":
                    assert_legal_email_campaign_transition(
                        campaign.status, "scheduled", context="campaign_scheduler/campaign-group-paused"
                    )
                    campaign.status = "scheduled"
                    campaign.processing_started_at = None
                    campaign.processing_lock_acquired_at = None
                    db.commit()
                    skipped += 1
                    continue

            logger.debug("DIRECT SEND: %s", campaign.id)
            try:
                process_email_campaign(str(campaign.id))
                sent += 1
                if not skip_delay:
                    time.sleep(random.uniform(1.0, 4.5))
            except Exception as e:
                logger.error("Internal server error", exc_info=e)
                assert_legal_email_campaign_transition(
                    campaign.status, "failed", context="campaign_scheduler/process_email_exception"
                )
                campaign.status = "failed"
                campaign.error = str(e)
                campaign.sent_at = ensure_utc(datetime.now(timezone.utc))
                campaign.processing_started_at = None
                campaign.processing_lock_acquired_at = None
                db.commit()
                failed += 1
                errors.append(
                    {
                        "campaign_id": str(campaign.id),
                        "student_id": str(campaign.student_id),
                        "hr_id": str(campaign.hr_id),
                        "email_type": campaign.email_type,
                        "error": "internal_error",
                    }
                )
        logger.info(
            "Campaign direct-send: candidates=%s sent=%s skipped=%s failed=%s",
            len(to_send),
            sent,
            skipped,
            failed,
        )
        return {"sent": sent, "failed": failed, "skipped": skipped, "errors": errors}
    except OperationalError as e:
        logger.warning(
            "run_campaign_job: database unavailable (will retry next tick): %s", e
        )
        if db is not None:
            try:
                db.rollback()
            except Exception:
                pass
        return {
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [],
            "note": "db_unavailable",
        }
    finally:
        if db is not None:
            db.close()
        job_lock.release()


def start_scheduler():
    """Start APScheduler: campaign send, HR lifecycle, reply/IMAP jobs (jobs run in worker thread, not here)."""
    global _scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.events import (
        EVENT_JOB_ERROR,
        EVENT_JOB_EXECUTED,
        EVENT_JOB_MISSED,
    )
    from apscheduler.executors.pool import ThreadPoolExecutor

    if _scheduler is not None and getattr(_scheduler, "running", False):
        logger.info("Campaign scheduler already running; skip duplicate start.")
        return _scheduler
    if _scheduler is not None:
        _scheduler = None

    def run_gmail_monitor_job():
        from app.services.gmail_monitor import run_gmail_monitor_job as _run

        return _run()

    def safe_check_replies():
        try:
            from app.services.reply_tracker import check_replies as _check

            return _check()
        except Exception as e:
            # Reply tracking is best-effort; must never impact sending reliability.
            logger.error("Internal server error", exc_info=e)
            return {"ok": False, "ignored_error": True}

    def run_sheet_sync_job():
        """Push new replies / failures / bounces to Google Sheets on a fixed cadence."""
        from app.database.config import SessionLocal
        from app.services.sheet_sync import sync_new_replies

        db = SessionLocal()
        try:
            sync_new_replies(db)
        except Exception as e:
            logger.warning("sheet_sync job failed: %s", e)
        finally:
            db.close()

    def run_student_email_health_job():
        from app.database.config import SessionLocal
        from app.services.student_email_health import refresh_all_students_email_health

        db = SessionLocal()
        try:
            refresh_all_students_email_health(db)
        except Exception as e:
            logger.warning("student email health job failed: %s", e)
        finally:
            db.close()

    def _on_job_event(event):
        # APScheduler events are in-memory only; keep this safe + lightweight.
        _scheduler_metrics["last_event_at_utc"] = datetime.now(timezone.utc).isoformat()
        if getattr(event, "code", None) == EVENT_JOB_MISSED:
            _scheduler_metrics["missed_runs"] = int(_scheduler_metrics.get("missed_runs", 0) or 0) + 1
            logger.warning("scheduler job missed: %s", getattr(event, "job_id", "?"))
        elif getattr(event, "code", None) == EVENT_JOB_ERROR:
            _scheduler_metrics["job_errors"] = int(_scheduler_metrics.get("job_errors", 0) or 0) + 1
            logger.warning("scheduler job error: %s", getattr(event, "job_id", "?"), exc_info=True)
        elif getattr(event, "code", None) == EVENT_JOB_EXECUTED:
            # Normal completion; the per-job wrapper records duration.
            pass

    # Explicit UTC avoids tzlocal.get_localzone() during scheduler configure (can hang on Windows).
    # Bounded threadpool prevents "catch-up storm" from starving DB pool / CPU.
    scheduler = BackgroundScheduler(
        timezone="UTC",
        executors={"default": ThreadPoolExecutor(max_workers=4)},
        job_defaults={
            # Fail-safe defaults; individual jobs can override.
            "max_instances": 1,
            "coalesce": True,
            "misfire_grace_time": 90,
        },
    )
    scheduler.add_listener(_on_job_event, EVENT_JOB_MISSED | EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)
    scheduler.add_job(
        _timed_job("campaign_send", run_campaign_job),
        trigger="interval",
        minutes=2,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
        id="campaign_send",
        jitter=10,
    )
    # Follow-up / lifecycle disabled (initial emails only)
    # scheduler.add_job(run_hr_lifecycle_job, "interval", hours=24, id="hr_lifecycle")
    scheduler.add_job(
        _timed_job("gmail_monitor", run_gmail_monitor_job),
        "interval",
        minutes=5,
        id="gmail_monitor",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
        jitter=20,
    )
    scheduler.add_job(
        _timed_job("reply_tracker", safe_check_replies),
        "interval",
        minutes=5,
        id="reply_tracker",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
        jitter=20,
    )
    scheduler.add_job(
        _timed_job("student_email_health", run_student_email_health_job),
        trigger="interval",
        minutes=5,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
        id="student_email_health",
        jitter=20,
    )
    scheduler.add_job(
        _timed_job("sheet_sync_job", run_sheet_sync_job),
        trigger="interval",
        minutes=2,
        id="sheet_sync_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
        jitter=10,
    )
    if not scheduler.running:
        scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Campaign scheduler started: campaign send 2 min; Gmail monitor 5 min; reply tracker 5 min; "
        "student email health 5 min; sheet sync 2 min"
    )
    return scheduler


def shutdown_scheduler():
    """Stop background jobs on app shutdown (non-blocking)."""
    global _scheduler
    if _scheduler is None:
        return
    try:
        if getattr(_scheduler, "running", False):
            _scheduler.shutdown(wait=False)
            logger.info("Campaign scheduler shut down.")
    except Exception as e:
        logger.warning("Campaign scheduler shutdown error: %s", e)
    finally:
        _scheduler = None
