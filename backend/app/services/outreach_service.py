"""Run outreach: active assignments, campaign rows, and SMTP (direct send where used).

send_selected_outreach queues pending campaigns for the scheduler only.
"""
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from app.models import Student, HRContact, Assignment, EmailCampaign
from app.services.email_dispatcher import send_with_fallback
from app.services.campaign_generator import generate_campaigns_for_assignment
from app.services.sequence_service import ensure_four_step_campaign_rows
from app.utils.datetime_utils import ensure_utc
from app.utils.email_campaign_persist import persist_sent_email_campaign
from app.services.hr_validity import mark_hr_invalid_if_valid, outbound_failure_should_invalidate_hr
from app.services.student_email_health import (
    is_student_email_sending_blocked,
    refresh_student_email_health,
)
from app.services.sheet_sync_trigger import trigger_sheet_sync_async
from app.services.campaign_lifecycle import assert_legal_email_campaign_transition
from app.services.deliverability_layer import evaluate_deliverability_for_send

logger = logging.getLogger(__name__)


def normalize_template_label(template_label: str | None) -> str | None:
    if template_label is None:
        return None
    s = (template_label or "").strip()
    return s or None


def run_outreach(db: Session) -> list[dict]:
    """
    For each active assignment (student–HR pair), send one outreach email and log it.
    Uses student's gmail_address, app_password, and resume_path like before.
    """
    assignments = (
        db.query(Assignment)
        .join(HRContact, Assignment.hr_id == HRContact.id)
        .filter(Assignment.status == "active", HRContact.is_valid.is_(True))
        .options(joinedload(Assignment.hr_contact))
        .all()
    )
    results = []

    for assignment in assignments:
        student = db.query(Student).filter(Student.id == assignment.student_id).first()
        hr = assignment.hr_contact
        if not student or not hr:
            continue
        if student.status != "active":
            continue
        if is_student_email_sending_blocked(student):
            logger.warning("run_outreach skip: student %s email health flagged", student.id)
            continue

        existing = (
            db.query(EmailCampaign)
            .filter(
                EmailCampaign.student_id == assignment.student_id,
                EmailCampaign.hr_id == hr.id,
                # allow resend if previous campaign failed
                EmailCampaign.status.in_(("sent", "scheduled", "pending")),
            )
            .first()
        )
        if existing:
            continue

        try:
            send_res = send_one(db, student.id, hr.id)
            status = "SENT" if send_res.get("ok") else "FAILED"
        except Exception:
            status = "FAILED"

        results.append({
            "student": student.name,
            "company": hr.company,
            "status": status,
        })
        time.sleep(20)  # rate limit like before

    return results


def send_one(
    db: Session,
    student_id,
    hr_id,
    template_label: str | None = None,
    subject: str | None = None,
    body: str | None = None,
) -> dict:
    """
    Explicit controlled send for one student–HR pair (must be an active assignment).

    Creates the initial campaign row on first send only, then sends using campaign subject/body (SMTP).
    Optional subject/body override the template for this send (passed to resolve_email_content).
    """
    assignment = (
        db.query(Assignment)
        .filter(
            Assignment.student_id == student_id,
            Assignment.hr_id == hr_id,
            Assignment.status == "active",
        )
        .first()
    )
    if not assignment:
        return {"ok": False, "message": "No active assignment for this student and HR"}

    student = db.query(Student).filter(Student.id == student_id).first()
    hr = (
        db.query(HRContact)
        .filter(HRContact.id == hr_id, HRContact.is_valid.is_(True))
        .first()
    )
    if not student:
        return {"ok": False, "message": "Student not found"}
    if is_student_email_sending_blocked(student):
        logger.warning("send_one blocked: student %s email_health_status=flagged", student_id)
        return {
            "ok": False,
            "message": "Student email health is flagged; sending paused until metrics recover",
            "email_health_blocked": True,
        }
    if not hr:
        if (
            db.query(HRContact)
            .filter(HRContact.id == hr_id, HRContact.is_valid.is_(False))
            .first()
        ):
            return {
                "ok": False,
                "message": "HR is invalid (delivery failed previously)",
                "skipped_invalid_hr": True,
            }
        return {"ok": False, "message": "Student or HR not found"}
    if not student.app_password:
        return {"ok": False, "message": "Student has no app_password configured for SMTP"}

    existing = (
        db.query(EmailCampaign)
        .filter(EmailCampaign.student_id == student_id, EmailCampaign.hr_id == hr_id)
        .count()
    )
    if existing == 0:
        generate_campaigns_for_assignment(db, assignment)

    # Pick the next campaign step to send.
    # If initial is already sent, allow follow-ups over time (do not permanently block per HR).
    next_campaign = (
        db.query(EmailCampaign)
        .filter(
            EmailCampaign.student_id == student_id,
            EmailCampaign.hr_id == hr_id,
            EmailCampaign.status.in_(("pending", "scheduled", "failed")),
        )
        .order_by(EmailCampaign.sequence_number.asc(), EmailCampaign.created_at.asc())
        .first()
    )
    if not next_campaign:
        created = generate_campaigns_for_assignment(db, assignment)
        if created:
            next_campaign = created[0]
    if not next_campaign:
        return {"ok": False, "message": "Could not create or load campaign"}

    # Idempotency safety: claim the campaign for immediate send to avoid
    # manual vs scheduler collisions and double-click duplicate sends.
    # (Scheduler only selects status=scheduled.)
    if next_campaign.status in ("pending", "scheduled"):
        now_claim = ensure_utc(datetime.now(timezone.utc))
        claimed = (
            db.query(EmailCampaign)
            .filter(
                EmailCampaign.id == next_campaign.id,
                EmailCampaign.status.in_(("pending", "scheduled")),
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
            return {"ok": False, "message": "Send already in progress; try again shortly"}
        next_campaign = db.query(EmailCampaign).filter(EmailCampaign.id == next_campaign.id).first()
        if not next_campaign:
            return {"ok": False, "message": "Could not load campaign after claim"}

    subj = (subject or "").strip() or None
    bod = (body or "").strip() or None
    result = send_one_immediate(
        db,
        student=student,
        hr=hr,
        subject=subj,
        body=bod,
        include_resume=True,
        stored_subject=next_campaign.subject,
        stored_body=next_campaign.body,
    )
    if not result.get("ok"):
        # Keep EmailCampaign as the single source of truth: reflect the send outcome here.
        if next_campaign.status in ("scheduled", "pending", "processing"):
            if result.get("skipped_invalid_hr"):
                assert_legal_email_campaign_transition(
                    next_campaign.status, "cancelled", context="outreach_service/send_one/skip-hr"
                )
                next_campaign.status = "cancelled"
                next_campaign.error = "skipped_invalid_hr"
            else:
                assert_legal_email_campaign_transition(
                    next_campaign.status, "failed", context="outreach_service/send_one/failure"
                )
                next_campaign.status = "failed"
                err_msg = result.get("message", "Send failed")
                next_campaign.error = err_msg
                next_campaign.sent_at = ensure_utc(datetime.now(timezone.utc))
                if outbound_failure_should_invalidate_hr(getattr(hr, "email", None), err_msg):
                    mark_hr_invalid_if_valid(db, hr_id)
                try:
                    trigger_sheet_sync_async(reason="send_one failure")
                except Exception:
                    logger.warning("sheet_sync after send_one failure failed")
            next_campaign.processing_started_at = None
            next_campaign.processing_lock_acquired_at = None
            db.commit()
            try:
                refresh_student_email_health(db, student_id)
            except Exception:
                logger.warning("refresh_student_email_health after send failure failed", exc_info=True)
        return result

    if next_campaign.status in ("scheduled", "pending", "processing"):
        assert_legal_email_campaign_transition(next_campaign.status, "sent", context="outreach_service/send_one/success")
        next_campaign.status = "sent"
        if not next_campaign.sent_at:
            next_campaign.sent_at = ensure_utc(datetime.now(timezone.utc))
        next_campaign.subject = result.get("resolved_subject", next_campaign.subject)
        next_campaign.body = result.get("resolved_body", next_campaign.body)
        next_campaign.gmail_thread_id = None
        next_campaign.gmail_message_id = None
        if result.get("message_id"):
            next_campaign.message_id = result.get("message_id")
        next_campaign.processing_started_at = None
        next_campaign.processing_lock_acquired_at = None
        lab = normalize_template_label(template_label)
        if lab is not None:
            next_campaign.template_label = lab[:128] if len(lab) > 128 else lab
        persist_sent_email_campaign(db, next_campaign)
        try:
            refresh_student_email_health(db, student_id)
        except Exception:
            logger.warning("refresh_student_email_health after send_one success failed", exc_info=True)
        try:
            trigger_sheet_sync_async(reason="send_one success")
        except Exception:
            logger.warning("sheet_sync after send_one success failed", exc_info=True)

    return {
        "ok": True,
        "message": "Email sent successfully",
        "status": result.get("status"),
        "gmail_message_id": None,
        "gmail_thread_id": None,
    }


def send_selected_outreach(
    db: Session,
    student: Student,
    hr_ids: list[UUID],
    subject: str | None = None,
    body: str | None = None,
    template_label: str | None = None,
) -> dict:
    """
    Queue initial campaigns for the scheduler only (no SMTP send in this path).
    Creates EmailCampaign rows as pending when missing; scheduler picks them up and sends.
    """
    from app.services.email_templates import resolve_email_content

    student_id = student.id

    seen: set[UUID] = set()
    ordered_unique: list[UUID] = []
    for hid in hr_ids:
        if hid not in seen:
            seen.add(hid)
            ordered_unique.append(hid)

    refresh_student_email_health(db, student_id)
    student = db.query(Student).filter(Student.id == student_id).first()
    if student and is_student_email_sending_blocked(student):
        logger.warning("send_selected_outreach blocked: student %s flagged", student.id)
        return {
            "student_id": str(student_id),
            "summary": {
                "total": len(ordered_unique),
                "queued": 0,
                "sent": 0,
                "skipped": 0,
                "errors": len(ordered_unique),
            },
            "results": [
                {
                    "hr_id": str(hid),
                    "status": "error",
                    "message": "Student email health is flagged; sending paused until metrics recover",
                }
                for hid in ordered_unique
            ],
        }

    results: list[dict] = []

    # Smart scheduling: stagger scheduled_at to reduce spam signals and smooth load.
    base_now = datetime.now(timezone.utc)
    for i, hr_id in enumerate(ordered_unique):
        row: dict = {"hr_id": str(hr_id), "status": "pending"}

        hr = (
            db.query(HRContact)
            .filter(HRContact.id == hr_id, HRContact.is_valid.is_(True))
            .first()
        )
        if not hr:
            row["status"] = "error"
            row["message"] = "HR not found or invalid"
            results.append(row)
            continue

        # Prevent accidental rapid re-send, but do NOT permanently block all future emails.
        # Windowed duplicate rule: if any campaign for this student–HR was sent recently, skip.
        recent_cutoff = ensure_utc(datetime.now(timezone.utc) - timedelta(hours=24))
        last_sent = (
            db.query(EmailCampaign)
            .filter(
                EmailCampaign.student_id == student_id,
                EmailCampaign.hr_id == hr_id,
                EmailCampaign.status == "sent",
                EmailCampaign.sent_at.isnot(None),
            )
            .order_by(EmailCampaign.sent_at.desc())
            .first()
        )
        if last_sent and last_sent.sent_at:
            s_at = last_sent.sent_at
            if s_at.tzinfo is None:
                s_at = s_at.replace(tzinfo=timezone.utc)
            if s_at >= recent_cutoff:
                row["status"] = "skipped"
                row["message"] = "Recently emailed this HR; try again after 24h"
                results.append(row)
                continue

        assignment = (
            db.query(Assignment)
            .filter(
                Assignment.student_id == student_id,
                Assignment.hr_id == hr_id,
                Assignment.status == "active",
            )
            .first()
        )
        if not assignment:
            assignment = Assignment(student_id=student_id, hr_id=hr_id, status="active")
            db.add(assignment)
            db.commit()
            db.refresh(assignment)

        scheduled_for = (
            base_now + timedelta(minutes=i * 5, seconds=random.randint(0, 119))
        ).replace(tzinfo=None)

        ensure_four_step_campaign_rows(db, assignment, anchor=scheduled_for)

        campaign = (
            db.query(EmailCampaign)
            .filter(
                EmailCampaign.student_id == student_id,
                EmailCampaign.hr_id == hr_id,
                EmailCampaign.status.in_(("pending", "scheduled", "processing", "failed")),
            )
            .order_by(EmailCampaign.sequence_number.asc(), EmailCampaign.created_at.asc())
            .first()
        )
        if campaign and campaign.status == "processing":
            row["status"] = "error"
            row["message"] = "A send is in progress for this HR; try again shortly"
            results.append(row)
            continue

        if campaign is None:
            row["status"] = "error"
            row["message"] = "Could not create or load campaign"
            results.append(row)
            continue

        if campaign.status == "failed":
            assert_legal_email_campaign_transition(campaign.status, "pending", context="outreach_service/retry-failed")
            campaign.status = "pending"
            campaign.error = None

        campaign.scheduled_at = scheduled_for
        if campaign.status not in ("pending", "scheduled"):
            assert_legal_email_campaign_transition(
                campaign.status, "pending", context="outreach_service/force-pending-for-queue"
            )
            campaign.status = "pending"

        try:
            res_subj, res_body = resolve_email_content(
                student,
                hr,
                subject,
                body,
                stored_subject=campaign.subject,
                stored_body=campaign.body,
                email_type=campaign.email_type or "initial",
            )
        except Exception as e:
            logger.error("Internal server error", exc_info=e)
            row["status"] = "error"
            row["message"] = "Internal server error"
            results.append(row)
            continue

        campaign.subject = res_subj
        campaign.body = res_body
        lab = normalize_template_label(template_label)
        if lab is not None:
            campaign.template_label = lab[:128] if len(lab) > 128 else lab

        db.commit()
        db.refresh(campaign)

        row["status"] = "queued"
        row["message"] = "Campaign queued; scheduler will send"
        row["campaign_id"] = str(campaign.id)
        results.append(row)

    queued_n = sum(1 for x in results if x["status"] == "queued")
    skipped_n = sum(1 for x in results if x["status"] == "skipped")
    err_n = sum(1 for x in results if x["status"] == "error")

    try:
        refresh_student_email_health(db, student_id)
    except Exception:
        logger.warning("refresh_student_email_health after send_selected_outreach failed", exc_info=True)

    return {
        "student_id": str(student_id),
        "summary": {
            "total": len(results),
            "queued": queued_n,
            "sent": 0,
            "skipped": skipped_n,
            "errors": err_n,
        },
        "results": results,
    }


def send_one_immediate(
    db: Session,
    *,
    student: Student,
    hr: HRContact,
    subject: str | None = None,
    body: str | None = None,
    include_resume: bool = True,
    stored_subject: str | None = None,
    stored_body: str | None = None,
    email_type: str = "initial",
    in_reply_to: str | None = None,
    references: list[str] | None = None,
) -> dict:
    """Send one email immediately via Gmail SMTP (app password)."""
    from app.services.email_templates import resolve_email_content

    if hr.is_valid is not True:
        logger.info("Skipped invalid HR")
        return {
            "ok": False,
            "message": "HR is invalid (delivery failed previously)",
            "skipped_invalid_hr": True,
        }

    if is_student_email_sending_blocked(student):
        logger.warning("send_one_immediate blocked: student %s email_health_status=flagged", student.id)
        return {
            "ok": False,
            "message": "Student email health is flagged; sending paused until metrics recover",
            "email_health_blocked": True,
        }

    res_subj, res_body = resolve_email_content(
        student,
        hr,
        subject,
        body,
        stored_subject=stored_subject,
        stored_body=stored_body,
        email_type=email_type,
    )
    gate = evaluate_deliverability_for_send(db, student, res_subj, res_body)
    if not gate.get("allow"):
        return {
            "ok": False,
            "message": "Deliverability gate: " + "; ".join(gate.get("block_reasons") or []),
            "deliverability_blocked": True,
            "deliverability": gate,
        }

    try:
        from_email = (getattr(student, "gmail_address", None) or "").strip()
        app_password = (getattr(student, "app_password", None) or "").strip()
        resume_path = (getattr(student, "resume_path", None) or "").strip()

        # Resume is required for every email.
        if include_resume and not resume_path:
            logger.debug("NO RESUME: %s", student.id)
            raise RuntimeError(f"NO RESUME: {student.id}")

        result = send_with_fallback(
            student_email=from_email,
            hr_email=hr.email,
            subject=res_subj,
            body=res_body,
            smtp_app_password=app_password or None,
            resume_path=(resume_path if include_resume else None),
            student_name=student.name,
            in_reply_to=in_reply_to,
            references=references,
        )

        rfc_message_id = result.get("message_id")
    except Exception as e:
        logger.error("Internal server error", exc_info=e)
        return {"ok": False, "message": "Internal server error"}
    return {
        "ok": True,
        "status": "SENT",
        "gmail_message_id": None,
        "gmail_thread_id": None,
        "message_id": rfc_message_id,
        "resolved_subject": res_subj,
        "resolved_body": res_body,
    }
