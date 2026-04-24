"""Reply ingestion (IMAP / Gmail): normalize body, classify, persist EmailCampaign."""
from __future__ import annotations

import logging
from email.utils import parseaddr
from sqlalchemy.orm import Session

from app.models import HRContact, BlockedHR
from app.models.email_campaign import EmailCampaign
from app.services.campaign_lifecycle import assert_legal_email_campaign_transition
from app.services.campaign_terminal_outcomes import (
    BOUNCED as TERMINAL_BOUNCED,
    record_pair_terminal_outcome,
    terminal_outcome_for_replied_campaign,
)
from app.services.hr_validity import inbound_bounce_should_block_hr, mark_hr_invalid_if_valid
from app.services.reply_utils import BOUNCE, clean_reply, classify_reply

logger = logging.getLogger(__name__)

SELF_EMAILS = frozenset({"habin936@gmail.com"})

_MAX_REPLY_STORE = 100_000
_MAX_ERROR_STORE = 16_000


def _delivery_subtype(raw: str) -> str:
    """Granular failure for bounce handling (HR invalid, sheets); raw = original inbound."""
    t = raw.lower()
    if any(
        k in t
        for k in (
            "delivery incomplete",
            "delayed",
            "temporary failure",
            "temporar",
            "try again later",
            "greylisted",
            "mailbox full",
            "quota exceeded",
            "451 ",
            "452 ",
            "421 ",
        )
    ):
        return "TEMP_FAIL"
    if any(
        k in t
        for k in (
            "message blocked",
            "blocked by",
            "550 5.7.1",
            "554 5.7.1",
            "policy violation",
            "violates the policy",
            "spam",
            "rejected for policy",
            "rejected by server",
        )
    ):
        return "BLOCKED"
    return "BOUNCED"


def should_send_followup(campaign: EmailCampaign, db: Session | None = None) -> bool:
    if campaign.reply_status is None:
        return False
    rs = (campaign.reply_status or "").strip().upper()
    if rs in ("UNKNOWN", "INITIAL"):
        return False
    if rs in (
        "INTERVIEW",
        "INTERESTED",
        "REPLIED",
        "OTHER",
        "AUTO_REPLY",
        "BOUNCED",
        "BLOCKED",
        "TEMP_FAIL",
        "BOUNCE",
        "REJECTED",
        "NOT_INTERESTED",
        "OOO",
        "UNKNOWN",
    ):
        return False
    return True


def _normalized_inbound_sender(
    reply_from_header: str | None, sender_for_classify: str
) -> str:
    if reply_from_header and str(reply_from_header).strip():
        _, addr = parseaddr(str(reply_from_header).strip())
        a = (addr or "").strip().lower()
        if a:
            return a
    _, addr = parseaddr(str(sender_for_classify or "").strip())
    a = (addr or "").strip().lower()
    if a:
        return a
    return (sender_for_classify or "").strip().lower()


def get_followup_stage(days_since_sent: int) -> int:
    if days_since_sent >= 21:
        return 3
    if days_since_sent >= 14:
        return 2
    if days_since_sent >= 7:
        return 1
    return 0


FOLLOWUP_TEMPLATES = {
    1: "Hi, just following up on my previous email...",
    2: "Hi, checking again regarding my earlier message...",
    3: "Hi, this is my final follow-up...",
}


def apply_inbound_reply_to_campaign(
    db: Session,
    campaign: EmailCampaign,
    body: str,
    *,
    sender_for_classify: str,
    reply_from_header: str | None,
    when,
    inbound_message_id: str | None = None,
) -> str:
    raw = (body or "").strip()
    if not raw:
        return "IGNORED"

    sender_l = (sender_for_classify or "").lower()
    is_mta = (
        "mailer-daemon" in sender_l
        or "postmaster" in sender_l
        or "mail delivery subsystem" in sender_l
        or "noreply-daemon" in sender_l
        or "microsoftexchange" in sender_l
    )
    text_full = raw.lower()
    mta_body = any(
        x in text_full
        for x in (
            "delivery status notification",
            "undelivered mail returned to sender",
            "returned mail:",
            "failure notice",
            "undeliverable:",
            "could not be delivered",
        )
    )

    cleaned = clean_reply(raw)
    if not cleaned.strip():
        cleaned = raw.strip()[:_MAX_REPLY_STORE]

    rtype = classify_reply(cleaned)
    if is_mta or mta_body:
        rtype = BOUNCE

    sub = _delivery_subtype(raw)
    if rtype == BOUNCE and sub in ("BOUNCED", "BLOCKED"):
        sender_norm = _normalized_inbound_sender(reply_from_header, sender_for_classify)
        if sender_norm in SELF_EMAILS:
            return "IGNORED"

    campaign.reply_detected_at = when
    if reply_from_header:
        campaign.reply_from = reply_from_header[:512]
    if inbound_message_id:
        campaign.last_reply_message_id = str(inbound_message_id).strip()[:128]

    hr = db.query(HRContact).filter(HRContact.id == campaign.hr_id).first()

    if rtype == BOUNCE:
        campaign.delivery_status = "FAILED" if sub != "TEMP_FAIL" else "DELAYED"
        campaign.failure_type = sub
        campaign.error = raw[:_MAX_ERROR_STORE]
        campaign.reply_text = cleaned
        campaign.reply_snippet = cleaned[:500]
        campaign.reply_status = BOUNCE
        campaign.reply_type = BOUNCE

        if sub in ("BOUNCED", "BLOCKED") and hr is not None:
            if inbound_bounce_should_block_hr(hr.email, sub):
                mark_hr_invalid_if_valid(db, hr.id)
                existing = db.query(BlockedHR).filter(BlockedHR.email == hr.email).first()
                if not existing:
                    reason = "bounce" if sub == "BOUNCED" else "blocked"
                    db.add(
                        BlockedHR(
                            email=hr.email,
                            company=hr.company,
                            reason=reason,
                        )
                    )

        if sub in ("BOUNCED", "BLOCKED"):
            campaign.replied = False
            campaign.replied_at = None
            assert_legal_email_campaign_transition(campaign.status, "failed", context="reply_classifier/bounce-hard")
            campaign.status = "failed"
        else:
            campaign.replied = False
            campaign.replied_at = None
            assert_legal_email_campaign_transition(campaign.status, "sent", context="reply_classifier/bounce-soft")
            campaign.status = "sent"

        db.add(campaign)
        if sub in ("BOUNCED", "BLOCKED"):
            record_pair_terminal_outcome(
                db,
                student_id=campaign.student_id,
                hr_id=campaign.hr_id,
                outcome=TERMINAL_BOUNCED,
                tag_campaign=campaign,
            )
        logger.info(
            "Reply normalized: campaign_id=%s type=BOUNCE delivery=%s",
            campaign.id,
            sub,
        )

        if sub in ("BOUNCED", "BLOCKED"):
            db.commit()
            try:
                from app.services.sheet_sync_trigger import trigger_sheet_sync_async

                trigger_sheet_sync_async(reason="reply_classifier bounce/block")
            except Exception:
                logger.exception("sheet_sync after bounce/block commit failed")
            try:
                from app.services.blocked_hr_sync import sync_blocked_hrs

                sync_blocked_hrs(db)
            except Exception:
                logger.exception("blocked_hr sheet sync failed (DB updated; sheet may lag)")
        return BOUNCE

    campaign.delivery_status = None
    campaign.failure_type = None
    campaign.error = None
    campaign.reply_text = cleaned[:_MAX_REPLY_STORE]
    campaign.reply_snippet = cleaned[:500]
    campaign.reply_status = rtype
    campaign.reply_type = rtype
    campaign.replied = True
    campaign.replied_at = when
    assert_legal_email_campaign_transition(campaign.status, "replied", context="reply_classifier/human-reply")
    campaign.status = "replied"
    db.add(campaign)
    record_pair_terminal_outcome(
        db,
        student_id=campaign.student_id,
        hr_id=campaign.hr_id,
        outcome=terminal_outcome_for_replied_campaign(campaign),
        tag_campaign=campaign,
    )
    logger.info("Reply normalized: campaign_id=%s type=%s", campaign.id, rtype)
    return rtype
