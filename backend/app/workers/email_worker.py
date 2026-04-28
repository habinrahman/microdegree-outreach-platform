import logging
import time
from datetime import datetime, timezone
from email.utils import parseaddr
from smtplib import SMTPException, SMTPAuthenticationError

logger = logging.getLogger(__name__)

from app.database.config import SessionLocal
from app.database.session_resilience import recover_db_session
from sqlalchemy.exc import OperationalError
from app.models import EmailCampaign, HRContact, Student
from app.services.email_dispatcher import send_with_fallback
from app.services.hr_validity import mark_hr_invalid_if_valid, outbound_failure_should_invalidate_hr
from app.utils.datetime_utils import ensure_utc
from app.utils.email_campaign_persist import persist_sent_email_campaign
from app.services.campaign_lifecycle import assert_legal_email_campaign_transition
from app.services.student_email_health import is_student_email_sending_blocked, refresh_student_email_health
from app.services.deliverability_layer import evaluate_deliverability_for_send
from app.services.runtime_settings_store import get_outbound_enabled
from app.services.outbound_suppression_store import is_suppressed, upsert_suppression
from app.services.pg_advisory_lock import campaign_send_lock
from app.services.audit import log_event
from app.services.campaign_terminal_outcomes import (
    BOUNCED as TERMINAL_BOUNCED,
    NO_RESPONSE_COMPLETED,
    record_pair_terminal_outcome,
)


def _smtp_thread_headers(db, campaign: EmailCampaign) -> tuple[str | None, list[str] | None]:
    """Build In-Reply-To / References from prior sent steps in the same student–HR sequence."""
    seq = int(campaign.sequence_number or 0)
    if seq <= 1:
        return None, None
    chain = (
        db.query(EmailCampaign)
        .filter(
            EmailCampaign.student_id == campaign.student_id,
            EmailCampaign.hr_id == campaign.hr_id,
            EmailCampaign.status == "sent",
            EmailCampaign.message_id.isnot(None),
            EmailCampaign.sequence_number < seq,
        )
        .order_by(EmailCampaign.sequence_number.asc(), EmailCampaign.created_at.asc())
        .all()
    )
    ids = [str(x.message_id).strip() for x in chain if getattr(x, "message_id", None)]
    if not ids:
        return None, None
    return ids[-1], ids


def _error_indicates_smtp_bounce(err: BaseException) -> bool:
    """
    Map SMTP / provider errors to reply_status=BOUNCED for sheet + analytics.
    Excludes our pre-flight ValueError('Invalid HR email: ...') — that stays failure-only.
    """
    s = str(err).lower()
    if "invalid hr email" in s:
        return False
    if any(code in s for code in ("550", "551", "552", "553")):
        return True
    if "bounce" in s:
        return True
    if "invalid" in s:
        return True
    return False


def _safe_sync_sheets(db, reason: str) -> None:
    try:
        from app.services.sheet_sync_trigger import trigger_sheet_sync_async

        trigger_sheet_sync_async(reason=f"email_worker {reason}")
    except Exception:
        logger.warning("sheet_sync after %s failed", reason, exc_info=True)


def process_email_campaign(campaign_id: str) -> None:
    db = SessionLocal()
    campaign = None

    try:
        # Cross-process idempotency lock: prevents duplicate sends if multiple workers are invoked
        # for the same campaign id (scheduler overlap, retries, manual + scheduler collision).
        with campaign_send_lock(db, campaign_id) as acquired:
            if not acquired:
                logger.debug("SKIP: send lock held for %s", campaign_id)
                try:
                    log_event(
                        db,
                        actor="system",
                        action="duplicate_send_blocked",
                        entity_type="EmailCampaign",
                        entity_id=str(campaign_id),
                        meta={"reason": "pg_advisory_lock_held"},
                    )
                except Exception:
                    pass
                return

        # Strict pre-guard:
        # - scheduled/pending: worker may claim itself
        # - processing: scheduler may have already claimed + committed the processing lock
        campaign = db.query(EmailCampaign).filter(EmailCampaign.id == campaign_id).first()
        if campaign is None:
            logger.debug("Campaign not found: %s", campaign_id)
            return
        if campaign.status not in ("scheduled", "pending", "processing"):
            logger.debug("SKIP: already processed %s %s", campaign.id, campaign.status)
            return

        now_claim = ensure_utc(datetime.now(timezone.utc))

        # Atomic claim: pending|scheduled -> processing, unless already claimed by scheduler.
        if campaign.status in ("scheduled", "pending"):
            claimed = (
                db.query(EmailCampaign)
                .filter(
                    EmailCampaign.id == campaign_id,
                    EmailCampaign.status.in_(("scheduled", "pending")),
                )
                .update(
                    {
                        "status": "processing",
                        "processing_started_at": now_claim,
                        "processing_lock_acquired_at": now_claim,
                    },
                    synchronize_session=False,
                )
            )
            db.commit()

            if claimed != 1:
                existing = db.query(EmailCampaign).filter(EmailCampaign.id == campaign_id).first()
                if existing is None:
                    logger.debug("Campaign not found: %s", campaign_id)
                    return
                if existing.status not in ("scheduled", "pending", "processing"):
                    logger.debug("SKIP: %s %s", existing.id, existing.status)
                    return
                logger.debug("Skipping: %s", campaign_id)
                return
        else:
            # Already processing: only proceed when this is a scheduler-claimed lock.
            if not campaign.processing_lock_acquired_at:
                logger.debug("SKIP: processing without lock %s", campaign.id)
                return

        campaign = db.query(EmailCampaign).filter(EmailCampaign.id == campaign_id).first()
        if not campaign:
            logger.debug("Campaign not found: %s", campaign_id)
            return

        logger.debug("[SEND START] Campaign=%s", campaign.id)

        # Global kill switch: release processing claim back to scheduled (do not cancel).
        if not get_outbound_enabled(db):
            logger.warning("Outbound disabled: blocking send campaign=%s", campaign.id)
            assert_legal_email_campaign_transition(campaign.status, "scheduled", context="email_worker/outbound_disabled")
            campaign.status = "scheduled"
            campaign.error = "outbound_disabled"
            campaign.processing_started_at = None
            campaign.processing_lock_acquired_at = None
            db.add(campaign)
            db.commit()
            try:
                log_event(
                    db,
                    actor="system",
                    action="kill_switch_blocked_send",
                    entity_type="EmailCampaign",
                    entity_id=str(campaign.id),
                    meta={"note": "outbound_disabled"},
                )
            except Exception:
                pass
            return

        student = db.query(Student).filter(Student.id == campaign.student_id).first()
        if not student:
            raise RuntimeError("Missing student or HR record")

        if is_student_email_sending_blocked(student):
            logger.warning(
                "Skipping campaign %s: student %s email_health_status=flagged (reputation)",
                campaign.id,
                student.id,
            )
            assert_legal_email_campaign_transition(campaign.status, "cancelled", context="email_worker/student_flagged")
            campaign.status = "cancelled"
            campaign.error = "student_email_health_flagged"
            campaign.processing_started_at = None
            campaign.processing_lock_acquired_at = None
            db.add(campaign)
            db.commit()
            return

        hr = (
            db.query(HRContact)
            .filter(HRContact.id == campaign.hr_id, HRContact.is_valid.is_(True))
            .first()
        )
        if not hr:
            if db.query(HRContact.id).filter(HRContact.id == campaign.hr_id).first():
                logger.debug("Skipped invalid HR %s %s", campaign.id, campaign.hr_id)
                assert_legal_email_campaign_transition(campaign.status, "cancelled", context="email_worker/invalid_hr")
                campaign.status = "cancelled"
                campaign.error = "skipped_invalid_hr"
                campaign.processing_started_at = None
                campaign.processing_lock_acquired_at = None
                db.add(campaign)
                db.commit()
                return
            raise RuntimeError("Missing student or HR record")

        # Basic invalid email classification (no new deps; deterministic).
        hr_email = (getattr(hr, "email", None) or "").strip()
        _, parsed = parseaddr(hr_email)
        if not parsed or "@" not in parsed:
            raise ValueError(f"Invalid HR email: {hr_email}")

        # Suppression list: hard block (recipient-specific).
        blocked, sup_reason = is_suppressed(db, hr_email)
        if blocked:
            logger.warning("Suppression blocked send campaign=%s hr_email=%s reason=%s", campaign.id, hr_email, sup_reason)
            assert_legal_email_campaign_transition(campaign.status, "cancelled", context="email_worker/suppressed")
            campaign.status = "cancelled"
            campaign.error = f"suppressed:{sup_reason or 'blocked'}"
            campaign.suppression_reason = "suppression_list"
            campaign.processing_started_at = None
            campaign.processing_lock_acquired_at = None
            db.add(campaign)
            db.commit()
            try:
                log_event(
                    db,
                    actor="system",
                    action="suppression_triggered",
                    entity_type="EmailCampaign",
                    entity_id=str(campaign.id),
                    meta={"hr_email": hr_email, "reason": sup_reason, "source": "suppression_list"},
                )
            except Exception:
                pass
            return

        # Safety check: if message_id already exists, this campaign has been sent before.
        if campaign.message_id:
            logger.debug("SKIP: already sent %s", campaign.id)
            # Ensure status reflects reality and avoid leaving it stuck in processing.
            already_counted = campaign.status == "sent" and campaign.sent_at is not None
            if campaign.status != "sent":
                assert_legal_email_campaign_transition(campaign.status, "sent", context="email_worker/dedupe-sent")
                campaign.status = "sent"
            campaign.processing_started_at = None
            campaign.processing_lock_acquired_at = None
            if not campaign.sent_at:
                campaign.sent_at = ensure_utc(datetime.now(timezone.utc))
            et_dedupe = (campaign.email_type or "").strip().lower()
            if et_dedupe == "followup_3" or int(campaign.sequence_number or 0) >= 4:
                record_pair_terminal_outcome(
                    db,
                    student_id=campaign.student_id,
                    hr_id=campaign.hr_id,
                    outcome=NO_RESPONSE_COMPLETED,
                    tag_campaign=campaign,
                )
            persist_sent_email_campaign(
                db,
                campaign,
                record_student_usage=not already_counted,
            )
            logger.debug("SAVED sent_at: %s %s", campaign.id, campaign.sent_at)
            return

        result = None
        student_email = (getattr(student, "gmail_address", None) or "").strip()
        app_password = (getattr(student, "app_password", None) or "").strip()
        resume_path = (getattr(student, "resume_path", None) or "").strip()

        # Resume is required for every email (local path; Drive not used for SMTP-only send).
        if not resume_path:
            logger.debug("NO RESUME: %s", student.id)
            raise RuntimeError(f"NO RESUME: {student.id}")

        gate = evaluate_deliverability_for_send(db, student, campaign.subject or "", campaign.body or "")
        if not gate.get("allow"):
            logger.warning(
                "deliverability gate blocked campaign=%s reasons=%s",
                campaign.id,
                gate.get("block_reasons"),
            )
            assert_legal_email_campaign_transition(
                campaign.status, "cancelled", context="email_worker/deliverability_gate"
            )
            campaign.status = "cancelled"
            campaign.error = "deliverability_gate:" + ";".join(gate.get("block_reasons") or [])
            campaign.suppression_reason = "deliverability_gate"
            campaign.processing_started_at = None
            campaign.processing_lock_acquired_at = None
            db.add(campaign)
            db.commit()
            return

        in_reply_to, references = _smtp_thread_headers(db, campaign)

        t_smtp = time.perf_counter()
        try:
            result = send_with_fallback(
                student_email=student_email,
                hr_email=hr.email,
                subject=campaign.subject or "",
                body=campaign.body or "",
                smtp_app_password=app_password or None,
                resume_path=resume_path or None,
                student_name=student.name,
                in_reply_to=in_reply_to,
                references=references,
            )
        finally:
            try:
                from app.services.observability_metrics import observe_latency

                observe_latency("smtp", (time.perf_counter() - t_smtp) * 1000.0)
            except Exception:
                pass

        try:
            from app.services.observability_metrics import inc

            inc("smtp_send_success_total")
        except Exception:
            pass

        assert_legal_email_campaign_transition(campaign.status, "sent", context="email_worker/send-success")
        campaign.status = "sent"
        if not campaign.sent_at:
            campaign.sent_at = ensure_utc(datetime.now(timezone.utc))
        campaign.processing_started_at = None
        campaign.processing_lock_acquired_at = None
        campaign.gmail_message_id = None
        campaign.gmail_thread_id = None
        campaign.message_id = result.get("message_id") or campaign.message_id
        campaign.error = None
        campaign.failure_type = None

        et_ok = (campaign.email_type or "").strip().lower()
        if et_ok == "followup_3" or int(campaign.sequence_number or 0) >= 4:
            record_pair_terminal_outcome(
                db,
                student_id=campaign.student_id,
                hr_id=campaign.hr_id,
                outcome=NO_RESPONSE_COMPLETED,
                tag_campaign=campaign,
            )

        persist_sent_email_campaign(db, campaign)
        try:
            log_event(
                db,
                actor="system",
                action="campaign_sent",
                entity_type="EmailCampaign",
                entity_id=str(campaign.id),
                meta={
                    "student_id": str(campaign.student_id),
                    "hr_id": str(campaign.hr_id),
                    "email_type": campaign.email_type,
                    "message_id": campaign.message_id,
                },
            )
        except Exception:
            pass

        logger.debug("SAVED sent_at: %s %s", campaign.id, campaign.sent_at)

        # Sequencer v1.1 correctness: follow-up calendar must be anchored to the actual initial send time.
        # Keep the pre-created 4-row architecture; update only queueable follow-up rows.
        if et_ok == "initial" and int(campaign.sequence_number or 0) == 1 and campaign.sent_at:
            try:
                from app.services.sequence_service import reschedule_followups_from_initial_sent

                reschedule_followups_from_initial_sent(
                    db,
                    student_id=campaign.student_id,
                    hr_id=campaign.hr_id,
                    initial_sent_at=campaign.sent_at,
                )
            except Exception:
                logger.warning("followup reschedule after initial send failed", exc_info=True)

        from app.services.log_stream import broadcast_log_sync
        broadcast_log_sync(
            {
                "campaign_id": str(campaign.id),
                "status": campaign.status,
                "student_id": str(campaign.student_id),
                "student_name": getattr(student, "name", None),
                "company": getattr(hr, "company", None),
                "hr_id": str(campaign.hr_id),
                "hr_email": getattr(hr, "email", None),
                "email_type": campaign.email_type,
                "sent_time": campaign.sent_at.isoformat() if campaign.sent_at else None,
                "error": campaign.error,
                "timestamp": campaign.sent_at.isoformat() if campaign.sent_at else None,
            }
        )

        logger.debug("[SEND SUCCESS] Campaign=%s", campaign.id)
        try:
            refresh_student_email_health(db, student.id)
        except Exception:
            logger.warning("refresh_student_email_health after worker success failed", exc_info=True)
        _safe_sync_sheets(db, "worker send success")

    except Exception as e:
        recover_db_session(db, e if isinstance(e, OperationalError) else None, log=logger)
        cid = None
        try:
            cid = campaign.id if campaign is not None else None
        except Exception:
            cid = None
        logger.error("Internal server error", exc_info=e)
        target = campaign
        if target is None:
            target = db.query(EmailCampaign).filter(EmailCampaign.id == campaign_id).first()
        if target is not None:
            if isinstance(e, ValueError) and "Invalid HR email" in str(e):
                bad_hr = db.query(HRContact).filter(HRContact.id == target.hr_id).first()
                if bad_hr is not None:
                    bad_hr.status = "invalid"
                    bad_hr.is_valid = False
                    db.add(bad_hr)
                    db.commit()
                # Suppress the raw email to prevent future sends even if HR is re-imported.
                try:
                    if bad_hr is not None and getattr(bad_hr, "email", None):
                        upsert_suppression(
                            db,
                            email=str(bad_hr.email),
                            reason="invalid_email",
                            source="invalid_email",
                            active=True,
                        )
                except Exception:
                    pass
                target = db.query(EmailCampaign).filter(EmailCampaign.id == campaign_id).first()
            if target is not None:
                assert_legal_email_campaign_transition(target.status, "failed", context="email_worker/send-failure")
                target.status = "failed"
                target.error = str(e)
                target.processing_started_at = None
                target.processing_lock_acquired_at = None
                if isinstance(e, ValueError) and "Invalid HR email" in str(e):
                    target.failure_type = "INVALID_EMAIL"
                elif isinstance(e, SMTPAuthenticationError) or isinstance(e, SMTPException):
                    target.failure_type = "SMTP_ERROR"
                else:
                    target.failure_type = "UNKNOWN"
                if _error_indicates_smtp_bounce(e):
                    target.reply_status = "BOUNCED"
                    target.delivery_status = "FAILED"
                    record_pair_terminal_outcome(
                        db,
                        student_id=target.student_id,
                        hr_id=target.hr_id,
                        outcome=TERMINAL_BOUNCED,
                        tag_campaign=target,
                    )
                    # Suppress recipient email on bounce to prevent repeated harm.
                    try:
                        hr_fail = db.query(HRContact).filter(HRContact.id == target.hr_id).first()
                        if hr_fail is not None and getattr(hr_fail, "email", None):
                            upsert_suppression(
                                db,
                                email=str(hr_fail.email),
                                reason="bounce_detected",
                                source="bounce",
                                active=True,
                            )
                    except Exception:
                        pass
                target.sent_at = ensure_utc(datetime.now(timezone.utc))
                hr_fail = db.query(HRContact).filter(HRContact.id == target.hr_id).first()
                hr_email = getattr(hr_fail, "email", None) if hr_fail else None
                if outbound_failure_should_invalidate_hr(hr_email, str(e)):
                    mark_hr_invalid_if_valid(db, target.hr_id)
                db.commit()
                _safe_sync_sheets(
                    db,
                    "worker send failure (failed"
                    + (", reply_status=BOUNCED" if target.reply_status == "BOUNCED" else "")
                    + ")",
                )
                hr = db.query(HRContact).filter(HRContact.id == target.hr_id).first()
                student = db.query(Student).filter(Student.id == target.student_id).first()
                from app.services.log_stream import broadcast_log_sync
                broadcast_log_sync(
                    {
                        "campaign_id": str(target.id),
                        "status": target.status,
                        "student_id": str(target.student_id),
                        "student_name": student.name if student else None,
                        "company": hr.company if hr else None,
                        "hr_id": str(target.hr_id),
                        "hr_email": hr.email if hr else None,
                        "email_type": target.email_type,
                        "sent_time": target.sent_at.isoformat() if target.sent_at else None,
                        "error": target.error,
                        "timestamp": target.sent_at.isoformat() if target.sent_at else None,
                    }
                )
                try:
                    refresh_student_email_health(db, target.student_id)
                except Exception:
                    logger.warning("refresh_student_email_health after worker failure failed", exc_info=True)
                try:
                    from app.services.observability_metrics import inc

                    inc("smtp_send_failure_total")
                except Exception:
                    pass

    finally:
        db.close()

