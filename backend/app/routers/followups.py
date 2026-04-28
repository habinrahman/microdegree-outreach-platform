import logging
import time

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.services.followup_eligibility import (
    compute_followup_eligibility_for_pair,
    list_followup_eligibility,
)
from app.services.campaign_lifecycle import assert_legal_email_campaign_transition

router = APIRouter(
    prefix="/followups",
    tags=["followups"],
    dependencies=[Depends(require_api_key)],
)
logger = logging.getLogger(__name__)


class FollowupsDispatchUpdate(BaseModel):
    enabled: bool
    reason: str | None = Field(
        default=None,
        max_length=4000,
        description="Optional incident / change ticket note (stored in audit log).",
    )


@router.get("/settings/dispatch")
def get_followups_dispatch_settings(db: Session = Depends(get_db)):
    """
    Operator toggle + env kill-switch (env is read-only here).

    **Precedence (unchanged):** ``FOLLOWUPS_ENABLED`` is the hard kill-switch at send time.
    When env allows follow-up sends, ``followups_dispatch_enabled`` from DB gates automated FU delivery.
    Missing DB table/row fail-opens dispatch to ON so ops-only env disable still works.
    """
    from app.config import FOLLOWUPS_ENABLED
    from app.services.runtime_settings_store import get_followups_dispatch_enabled

    try:
        dispatch_on = get_followups_dispatch_enabled(db)
    except Exception:
        logger.exception("GET /followups/settings/dispatch: degraded fail-open")
        dispatch_on = True
    return {
        "followups_env_enabled": bool(FOLLOWUPS_ENABLED),
        "followups_dispatch_enabled": bool(dispatch_on),
    }


@router.get("/settings/checksum")
def get_followups_dispatch_checksum(db: Session = Depends(get_db)):
    """Single JSON for ops: env ∧ DB follow-up dispatch (see ``source`` when degraded)."""
    from app.services.runtime_settings_store import get_followups_dispatch_config_checksum

    try:
        return get_followups_dispatch_config_checksum(db)
    except Exception:
        logger.exception("GET /followups/settings/checksum: degraded")
        from app.config import FOLLOWUPS_ENABLED

        return {
            "followups_env_enabled": bool(FOLLOWUPS_ENABLED),
            "dispatch_toggle": None,
            "effective_dispatch": bool(FOLLOWUPS_ENABLED),
            "source": "error_fail_open",
        }


@router.put("/settings/dispatch")
def put_followups_dispatch_settings(
    request: Request,
    body: FollowupsDispatchUpdate,
    db: Session = Depends(get_db),
):
    """
    Persist operator toggle. Appends an ``audit_logs`` row (immutable) with old/new values.

    Optional HTTP headers for incident review: ``X-Operator-Actor`` or ``X-Actor`` (defaults to
    ``operator_api`` when unset).
    """
    from app.services.audit import log_event
    from app.services.runtime_settings_bootstrap import KEY_FOLLOWUPS_DISPATCH
    from app.services.runtime_settings_store import (
        get_followups_dispatch_config_checksum,
        set_followups_dispatch_enabled,
    )

    try:
        before = get_followups_dispatch_config_checksum(db)
        set_followups_dispatch_enabled(db, bool(body.enabled))
        after = get_followups_dispatch_config_checksum(db)
        actor = (
            (request.headers.get("X-Operator-Actor") or request.headers.get("X-Actor") or "").strip()
            or "operator_api"
        )
        reason = (body.reason or "").strip() or None
        try:
            log_event(
                db,
                actor=actor,
                action="followups_dispatch_toggle",
                entity_type="runtime_setting",
                entity_id=KEY_FOLLOWUPS_DISPATCH,
                meta={
                    "key": KEY_FOLLOWUPS_DISPATCH,
                    "old_dispatch_toggle": before.get("dispatch_toggle"),
                    "old_source": before.get("source"),
                    "new_dispatch_toggle": after.get("dispatch_toggle"),
                    "new_source": after.get("source"),
                    "reason": reason,
                    "followups_env_enabled": after.get("followups_env_enabled"),
                    "effective_dispatch_after": after.get("effective_dispatch"),
                },
            )
        except Exception:
            logger.exception("followups_dispatch_toggle: audit log failed (DB toggle already committed)")
    except Exception:
        logger.exception("PUT /followups/settings/dispatch: persist failed")
        raise HTTPException(
            status_code=503,
            detail="runtime_settings_unavailable",
        ) from None
    return {"ok": True, "followups_dispatch_enabled": bool(body.enabled)}


@router.get("/funnel/summary")
def followup_funnel_summary(db: Session = Depends(get_db)):
    """Lightweight sequence funnel (best-effort; DB is source of truth)."""
    from app.models import EmailCampaign

    def _count(*filters) -> int:
        q = db.query(func.count(EmailCampaign.id))
        for f in filters:
            q = q.filter(f)
        return int(q.scalar() or 0)

    initial_sent = _count(
        func.lower(EmailCampaign.email_type) == "initial",
        EmailCampaign.status == "sent",
    )
    fu1_sent = _count(
        func.lower(EmailCampaign.email_type) == "followup_1",
        EmailCampaign.status == "sent",
    )
    fu2_sent = _count(
        func.lower(EmailCampaign.email_type) == "followup_2",
        EmailCampaign.status == "sent",
    )
    fu3_sent = _count(
        func.lower(EmailCampaign.email_type) == "followup_3",
        EmailCampaign.status == "sent",
    )
    followups_cancelled = _count(
        EmailCampaign.status == "cancelled",
        or_(
            func.lower(EmailCampaign.email_type) == "followup_1",
            func.lower(EmailCampaign.email_type) == "followup_2",
            func.lower(EmailCampaign.email_type) == "followup_3",
        ),
    )
    replied_rows = _count(
        EmailCampaign.replied.is_(True),
    )
    terminal_replied_status = _count(
        func.lower(EmailCampaign.status) == "replied",
    )

    from app.services.campaign_terminal_outcomes import ALL_OUTCOMES

    terminal_rows = (
        db.query(EmailCampaign.terminal_outcome, func.count(EmailCampaign.id))
        .filter(EmailCampaign.sequence_number == 1)
        .group_by(EmailCampaign.terminal_outcome)
        .all()
    )
    terminal_outcome_on_pairs: dict[str, int] = {k: 0 for k in sorted(ALL_OUTCOMES)}
    terminal_outcome_on_pairs["UNSET"] = 0
    for ov, n in terminal_rows:
        c = int(n or 0)
        if ov is None or not str(ov).strip():
            terminal_outcome_on_pairs["UNSET"] += c
        elif str(ov) in ALL_OUTCOMES:
            terminal_outcome_on_pairs[str(ov)] = c
        else:
            terminal_outcome_on_pairs["_other"] = terminal_outcome_on_pairs.get("_other", 0) + c

    from app.services.sequence_state_service import ALL_SEQUENCE_STATES

    seq_rows = (
        db.query(EmailCampaign.sequence_state, func.count(EmailCampaign.id))
        .filter(EmailCampaign.sequence_number == 1)
        .group_by(EmailCampaign.sequence_state)
        .all()
    )
    sequence_state_counts: dict[str, int] = {k: 0 for k in sorted(ALL_SEQUENCE_STATES)}
    sequence_state_counts["UNSET_OR_ACTIVE"] = 0
    for sv, n in seq_rows:
        c = int(n or 0)
        if sv is None or not str(sv).strip():
            sequence_state_counts["UNSET_OR_ACTIVE"] += c
        elif str(sv) in ALL_SEQUENCE_STATES:
            sequence_state_counts[str(sv)] = c
        else:
            sequence_state_counts["_other"] = sequence_state_counts.get("_other", 0) + c

    return {
        "initial_sent": initial_sent,
        "followup_1_sent": fu1_sent,
        "followup_2_sent": fu2_sent,
        "followup_3_sent": fu3_sent,
        "followup_rows_cancelled": followups_cancelled,
        "campaign_rows_replied_flag": replied_rows,
        "campaign_rows_status_replied": terminal_replied_status,
        "terminal_outcome_on_pairs": terminal_outcome_on_pairs,
        "sequence_state_on_pairs": sequence_state_counts,
    }


def _as_utc(dt):
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@router.get("/eligible")
def eligible_followups(
    include_demo: bool = False,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0, le=500_000),
    db: Session = Depends(get_db),
):
    """
    Read-only eligibility engine for manual follow-up orchestration.
    Does NOT send emails, does NOT mutate rows, and does NOT change scheduler behavior.

    Response includes ``status_breakdown`` (counts per ``followup_status``) for all returned
    student–HR pairs (one row per pair; ``pagination`` describes ``offset``/``limit`` windows).

    Default ``limit=50`` keeps the endpoint fast; use ``offset`` for additional pages.
    """
    return list_followup_eligibility(db, include_demo=include_demo, limit=limit, offset=offset)


@router.get("/preview")
def preview_followup(
    student_id: str,
    hr_id: str,
    db: Session = Depends(get_db),
):
    """
    Preview the next follow-up (subject/body + eligibility reasons).
    Read-only: does not claim rows and does not send.
    """
    from uuid import UUID
    from app.models import StudentTemplate, Student, HRContact, EmailCampaign

    try:
        sid = UUID(student_id)
        hid = UUID(hr_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid student_id/hr_id")

    state = compute_followup_eligibility_for_pair(db, student_id=sid, hr_id=hid)
    if not state.next_template_type:
        # Still return state so UI can show why blocked.
        return {"eligibility": state.__dict__, "template": None, "thread": None}

    tpl = (
        db.query(StudentTemplate)
        .filter(StudentTemplate.student_id == sid, StudentTemplate.template_type == state.next_template_type)
        .first()
    )
    st = db.query(Student).filter(Student.id == sid).first()
    hr = db.query(HRContact).filter(HRContact.id == hid).first()

    sent_chain = (
        db.query(EmailCampaign)
        .filter(
            EmailCampaign.student_id == sid,
            EmailCampaign.hr_id == hid,
            EmailCampaign.status == "sent",
            EmailCampaign.message_id.isnot(None),
        )
        .order_by(EmailCampaign.sequence_number.asc(), EmailCampaign.created_at.asc())
        .all()
    )
    message_ids = [str(c.message_id).strip() for c in sent_chain if getattr(c, "message_id", None)]
    in_reply_to = message_ids[-1] if message_ids else None
    references = message_ids if message_ids else None
    thread_continuity = bool(in_reply_to and references)

    return {
        "eligibility": state.__dict__,
        "template": (
            None
            if tpl is None
            else {
                "template_type": str(tpl.template_type),
                "subject": tpl.subject,
                "body": tpl.body,
            }
        ),
        "thread": {
            "student_name": getattr(st, "name", None) if st else None,
            "student_email": getattr(st, "gmail_address", None) if st else None,
            "company": getattr(hr, "company", None) if hr else None,
            "hr_email": getattr(hr, "email", None) if hr else None,
            "in_reply_to": in_reply_to,
            "references": references,
            "thread_continuity": thread_continuity,
        },
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
        "template_missing": tpl is None,
    }


@router.get("/reconcile/stale")
def list_stale_processing_followups(
    threshold_minutes: int = Query(15, ge=1, le=24 * 60),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """
    Operator tool: find follow-up rows stuck in processing beyond a threshold.
    No mutations here.
    """
    from app.models import EmailCampaign, Student, HRContact

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=int(threshold_minutes))

    q = (
        db.query(EmailCampaign, Student, HRContact)
        .join(Student, EmailCampaign.student_id == Student.id)
        .join(HRContact, EmailCampaign.hr_id == HRContact.id)
        .filter(
            EmailCampaign.status == "processing",
            EmailCampaign.processing_started_at.isnot(None),
            EmailCampaign.email_type.in_(("followup_1", "followup_2", "followup_3")),
        )
        .order_by(EmailCampaign.processing_started_at.asc())
    )

    rows = []
    for c, st, hr in q.limit(int(limit)).all():
        ps = _as_utc(getattr(c, "processing_started_at", None))
        if ps is None or ps > cutoff:
            continue
        age_min = int(max(0.0, (now - ps).total_seconds() // 60))
        rows.append(
            {
                "campaign_id": str(c.id),
                "email_type": c.email_type,
                "sequence_number": c.sequence_number,
                "student_id": str(c.student_id),
                "student_name": getattr(st, "name", None),
                "hr_id": str(c.hr_id),
                "company": getattr(hr, "company", None),
                "hr_email": getattr(hr, "email", None),
                "processing_started_at_utc": ps.isoformat(),
                "age_minutes": age_min,
                "error": c.error,
            }
        )
    return {
        "threshold_minutes": int(threshold_minutes),
        "total_stale": len(rows),
        "rows": rows,
        "checked_at_utc": now.isoformat(),
    }


@router.post("/reconcile/mark-sent")
def reconcile_mark_sent(
    campaign_id: str,
    threshold_minutes: int = Query(15, ge=1, le=24 * 60),
    db: Session = Depends(get_db),
):
    """
    Operator repair: mark a stale-processing follow-up row as sent (unknown outcome reconciliation).
    Never sends email.
    """
    from uuid import UUID
    from app.models import EmailCampaign
    from app.services.audit import log_event

    try:
        cid = UUID(campaign_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid campaign_id")

    c = db.query(EmailCampaign).filter(EmailCampaign.id == cid).first()
    if c is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if (c.email_type or "") not in ("followup_1", "followup_2", "followup_3"):
        raise HTTPException(status_code=409, detail="Not a follow-up campaign row")
    if (c.status or "") != "processing":
        raise HTTPException(status_code=409, detail="Campaign is not processing")
    ps = _as_utc(getattr(c, "processing_started_at", None))
    if ps is None:
        raise HTTPException(status_code=409, detail="Missing processing_started_at")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=int(threshold_minutes))
    if ps > cutoff:
        raise HTTPException(status_code=409, detail="Not stale enough to reconcile")

    assert_legal_email_campaign_transition(c.status, "sent", context="followups/reconcile-mark-sent")
    c.status = "sent"
    c.sent_at = now.replace(tzinfo=None)
    c.error = (c.error or "")[:1500] or None
    c.processing_started_at = None
    c.processing_lock_acquired_at = None
    db.add(c)
    db.commit()

    try:
        log_event(
            db,
            actor="operator",
            action="followup_reconciled_mark_sent",
            entity_type="EmailCampaign",
            entity_id=str(c.id),
            meta={
                "email_type": c.email_type,
                "threshold_minutes": int(threshold_minutes),
                "processing_started_at_utc": ps.isoformat(),
            },
        )
    except Exception:
        pass

    return {"ok": True, "campaign_id": str(c.id), "status": "sent", "reconciled": True}


@router.post("/reconcile/pause")
def reconcile_pause(
    campaign_id: str,
    threshold_minutes: int = Query(15, ge=1, le=24 * 60),
    db: Session = Depends(get_db),
):
    """
    Operator repair: reset a stale-processing follow-up row to paused (unknown outcome).
    Never sends email.
    """
    from uuid import UUID
    from app.models import EmailCampaign
    from app.services.audit import log_event

    try:
        cid = UUID(campaign_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid campaign_id")

    c = db.query(EmailCampaign).filter(EmailCampaign.id == cid).first()
    if c is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if (c.email_type or "") not in ("followup_1", "followup_2", "followup_3"):
        raise HTTPException(status_code=409, detail="Not a follow-up campaign row")
    if (c.status or "") != "processing":
        raise HTTPException(status_code=409, detail="Campaign is not processing")
    ps = _as_utc(getattr(c, "processing_started_at", None))
    if ps is None:
        raise HTTPException(status_code=409, detail="Missing processing_started_at")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=int(threshold_minutes))
    if ps > cutoff:
        raise HTTPException(status_code=409, detail="Not stale enough to pause")

    assert_legal_email_campaign_transition(c.status, "paused", context="followups/reconcile-pause")
    c.status = "paused"
    c.error = "stale_processing_unknown_outcome: operator_paused"
    c.processing_started_at = None
    c.processing_lock_acquired_at = None
    db.add(c)
    from app.services.campaign_terminal_outcomes import PAUSED_UNKNOWN_OUTCOME, record_pair_terminal_outcome

    record_pair_terminal_outcome(
        db,
        student_id=c.student_id,
        hr_id=c.hr_id,
        outcome=PAUSED_UNKNOWN_OUTCOME,
        tag_campaign=c,
    )
    db.commit()

    try:
        log_event(
            db,
            actor="operator",
            action="followup_reconciled_pause",
            entity_type="EmailCampaign",
            entity_id=str(c.id),
            meta={
                "email_type": c.email_type,
                "threshold_minutes": int(threshold_minutes),
                "processing_started_at_utc": ps.isoformat(),
            },
        )
    except Exception:
        pass

    return {"ok": True, "campaign_id": str(c.id), "status": "paused", "reconciled": True}


@router.post("/send")
def send_followup(
    student_id: str,
    hr_id: str,
    db: Session = Depends(get_db),
):
    """
    Single-campaign manual follow-up send (no bulk).
    Re-checks eligibility server-side and claims the campaign row for idempotency.
    """
    from uuid import UUID
    from app.config import FOLLOWUPS_DRY_RUN, FOLLOWUPS_ENABLED
    from app.models import StudentTemplate, Student, HRContact, EmailCampaign
    from app.services.outreach_service import send_one_immediate
    from app.utils.email_campaign_persist import persist_sent_email_campaign
    from app.services.audit import log_event
    from app.services.runtime_settings_store import get_outbound_enabled
    from app.services.outbound_suppression_store import is_suppressed

    if not FOLLOWUPS_ENABLED:
        raise HTTPException(status_code=409, detail="Follow-ups disabled (FOLLOWUPS_ENABLED=0)")

    try:
        sid = UUID(student_id)
        hid = UUID(hr_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid student_id/hr_id")

    state = compute_followup_eligibility_for_pair(db, student_id=sid, hr_id=hid)
    if not state.eligible_for_followup:
        raise HTTPException(status_code=409, detail=state.blocked_reason or "Not eligible")
    if state.followup_status == "SEND_IN_PROGRESS":
        raise HTTPException(status_code=409, detail="Send already in progress")
    if not state.next_followup_step or not state.next_template_type:
        raise HTTPException(status_code=409, detail="No next follow-up step available")

    tpl = (
        db.query(StudentTemplate)
        .filter(StudentTemplate.student_id == sid, StudentTemplate.template_type == state.next_template_type)
        .first()
    )
    if tpl is None:
        raise HTTPException(status_code=409, detail=f"Missing template {state.next_template_type}")

    st = db.query(Student).filter(Student.id == sid).first()
    hr = db.query(HRContact).filter(HRContact.id == hid, HRContact.is_valid.is_(True)).first()
    if st is None or hr is None:
        raise HTTPException(status_code=404, detail="Student or HR not found")

    # Global outbound kill switch (follow-up immediate send).
    if not get_outbound_enabled(db):
        raise HTTPException(status_code=409, detail="Outbound sending is disabled (outbound_enabled=false)")

    # Suppression list (follow-up immediate send).
    blocked, reason = is_suppressed(db, getattr(hr, "email", "") or "")
    if blocked:
        raise HTTPException(status_code=409, detail=f"Recipient suppressed: {reason or 'blocked'}")

    # Locate follow-up campaign row for this step (sequence_number = step+1).
    seq = int(state.next_followup_step) + 1
    c = (
        db.query(EmailCampaign)
        .filter(
            EmailCampaign.student_id == sid,
            EmailCampaign.hr_id == hid,
            EmailCampaign.sequence_number == seq,
        )
        .first()
    )
    if c is None:
        raise HTTPException(status_code=409, detail="Follow-up campaign row missing (regenerate required)")
    if (c.status or "").lower() == "sent" and getattr(c, "message_id", None):
        # Idempotent: already sent.
        return {"ok": True, "already_sent": True, "campaign_id": str(c.id)}

    # Dry-run: exercise safety checks + preview, but never send email.
    if FOLLOWUPS_DRY_RUN:
        return {
            "ok": True,
            "dry_run": True,
            "would_send": {
                "student_id": str(sid),
                "hr_id": str(hid),
                "step": int(state.next_followup_step),
                "template_type": str(state.next_template_type),
                "campaign_id": str(c.id),
                "subject": tpl.subject,
            },
        }

    # Claim for idempotency + operator collision safety.
    now_claim = datetime.now(timezone.utc).replace(tzinfo=None)
    claimed = (
        db.query(EmailCampaign)
        .filter(
            EmailCampaign.id == c.id,
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
        raise HTTPException(status_code=409, detail="Another operator already claimed this send")

    # Thread headers: reply to the last sent message-id; include References chain.
    sent_chain = (
        db.query(EmailCampaign)
        .filter(
            EmailCampaign.student_id == sid,
            EmailCampaign.hr_id == hid,
            EmailCampaign.status == "sent",
            EmailCampaign.message_id.isnot(None),
        )
        .order_by(EmailCampaign.sequence_number.asc(), EmailCampaign.created_at.asc())
        .all()
    )
    message_ids = [str(x.message_id).strip() for x in sent_chain if getattr(x, "message_id", None)]
    in_reply_to = message_ids[-1] if message_ids else None
    references = message_ids if message_ids else None

    # Send (SMTP) using the stored per-student follow-up template.
    try:
        from app.services.observability_metrics import inc, observe_latency

        inc("followup_send_attempt_total")
    except Exception:
        pass
    t_fu = time.perf_counter()
    res = send_one_immediate(
        db,
        student=st,
        hr=hr,
        subject=tpl.subject,
        body=tpl.body,
        include_resume=True,
        stored_subject=tpl.subject,
        stored_body=tpl.body,
        email_type=f"followup_{int(state.next_followup_step)}",
        in_reply_to=in_reply_to,
        references=references,
    )
    try:
        from app.services.observability_metrics import inc as _inc, observe_latency as _obs

        _obs("followup_send", (time.perf_counter() - t_fu) * 1000.0)
        _inc("followup_send_success_total" if res.get("ok") else "followup_send_failure_total")
    except Exception:
        pass
    if not res.get("ok"):
        # Mark failed and release processing lock.
        c = db.query(EmailCampaign).filter(EmailCampaign.id == c.id).first()
        if c is not None:
            assert_legal_email_campaign_transition(c.status, "failed", context="followups/send-now/failure")
            c.status = "failed"
            c.error = res.get("message") or "Send failed"
            c.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
            c.processing_started_at = None
            c.processing_lock_acquired_at = None
            db.add(c)
            db.commit()
        raise HTTPException(status_code=400, detail=res.get("message") or "Send failed")

    # Persist as sent (audit trail is the EmailCampaign row).
    c = db.query(EmailCampaign).filter(EmailCampaign.id == c.id).first()
    if c is None:
        raise HTTPException(status_code=500, detail="Campaign missing after send")
    assert_legal_email_campaign_transition(c.status, "sent", context="followups/send-now/success")
    c.status = "sent"
    c.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
    c.message_id = res.get("message_id") or c.message_id
    c.error = None
    c.processing_started_at = None
    c.processing_lock_acquired_at = None
    persist_sent_email_campaign(db, c)

    try:
        from app.observability.context import get_correlation_id

        log_event(
            db,
            actor="operator",
            action="followup_sent",
            entity_type="EmailCampaign",
            entity_id=str(c.id),
            meta={
                "student_id": str(sid),
                "hr_id": str(hid),
                "step": int(state.next_followup_step),
                "template_type": str(state.next_template_type),
                "in_reply_to": in_reply_to,
                "correlation_id": get_correlation_id(),
            },
        )
    except Exception:
        pass

    return {"ok": True, "campaign_id": str(c.id), "step": int(state.next_followup_step)}

