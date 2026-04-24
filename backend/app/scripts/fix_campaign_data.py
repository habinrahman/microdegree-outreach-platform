"""Idempotent repair for campaign reply fields (optional manual / dev use)."""
from datetime import datetime, timezone

from app.database.config import SessionLocal
from app.models import EmailCampaign, HRContact, BlockedHR
from app.services.reply_utils import BOUNCE, clean_reply, classify_reply

_fix_done = False

_MAX = 100_000


def run_fix():
    global _fix_done
    if _fix_done:
        return
    _fix_done = True

    db = SessionLocal()

    try:
        campaigns = db.query(EmailCampaign).all()

        for c in campaigns:
            updated = False

            if c.reply_text:
                raw = c.reply_text
                cleaned = clean_reply(raw)
                if not cleaned.strip():
                    cleaned = raw.strip()[:_MAX]
                else:
                    cleaned = cleaned[:_MAX]
                rtype = classify_reply(cleaned)

                if c.reply_text != cleaned:
                    c.reply_text = cleaned
                    updated = True
                if c.reply_status != rtype:
                    c.reply_status = rtype
                    updated = True
                if c.reply_type != rtype:
                    c.reply_type = rtype
                    updated = True
                snip = cleaned[:500]
                if c.reply_snippet != snip:
                    c.reply_snippet = snip
                    updated = True

                if rtype == BOUNCE:
                    c.replied = False
                    c.replied_at = None
                    sub = (c.failure_type or "BOUNCED").strip().upper()
                    if sub == "TEMP_FAIL":
                        c.delivery_status = "DELAYED"
                        if c.status not in ("failed", "sent"):
                            c.status = "sent"
                    else:
                        c.delivery_status = "FAILED"
                        if c.status != "failed":
                            c.status = "failed"
                    updated = True
                else:
                    if not c.replied:
                        c.replied = True
                        updated = True
                    if not c.replied_at:
                        c.replied_at = c.reply_detected_at or datetime.now(timezone.utc)
                        updated = True
                    if c.status != "replied":
                        c.status = "replied"
                        updated = True

                rs = (c.reply_status or "").strip().upper()
                if rs == "INITIAL":
                    c.reply_status = "OTHER"
                    c.reply_type = "OTHER"
                    updated = True

            if not c.reply_text and c.status == "replied":
                c.status = "sent"
                updated = True

            if getattr(c, "delivery_status", None) == "FAILED" and c.status != "failed":
                c.status = "failed"
                updated = True

            if updated:
                db.add(c)

        for hr in db.query(HRContact).filter(HRContact.status == "invalid").all():
            if db.query(BlockedHR).filter(BlockedHR.email == hr.email).first():
                continue
            db.add(
                BlockedHR(
                    email=hr.email,
                    company=hr.company,
                    reason="bounce",
                    created_at=datetime.now(timezone.utc),
                )
            )

        db.commit()
    finally:
        db.close()

    print("✅ Campaign data fixed")
