"""
Database consistency checker for outreach automation.

Repairs data inconsistencies between:
- EmailCampaign (single source of truth for send/replied state)
- Response (reply records)

This script is safe to run in production-like environments because it only:
- sets missing timestamps on "sent" campaigns
- syncs EmailCampaign replied state based on Response rows
- creates missing Response rows for EmailCampaign replied rows (idempotent)
"""

from __future__ import annotations

from datetime import datetime, date, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

from app.database.config import SessionLocal
from app.models import EmailCampaign, Response
from app.utils.datetime_utils import ensure_utc


def main() -> None:
    db = SessionLocal()
    try:
        repaired = {
            "sent_missing_sent_at": 0,
            "reply_campaigns_from_responses_updated": 0,
            "reply_campaigns_missing_replied_sync": 0,
            "responses_created_for_replied_campaigns": 0,
        }
        duplicates_detected = {"responses_per_student_hr": 0}

        # 1) "sent" campaigns should always have sent_at
        missing_sent_at = (
            db.query(EmailCampaign)
            .filter(EmailCampaign.status == "sent", EmailCampaign.sent_at.is_(None))
            .all()
        )
        if missing_sent_at:
            now = ensure_utc(datetime.now(timezone.utc))
            for c in missing_sent_at:
                c.sent_at = now
            db.commit()
            repaired["sent_missing_sent_at"] = len(missing_sent_at)

        # 2) Sync EmailCampaign replied state from existing Response rows.
        #    Prefer source_campaign_id when available.
        response_rows = (
            db.query(Response)
            .filter(Response.source_campaign_id.isnot(None))
            .all()
        )
        for r in response_rows:
            ec = (
                db.query(EmailCampaign)
                .filter(EmailCampaign.id == r.source_campaign_id)
                .first()
            )
            if not ec:
                continue
            if not ec.replied or ec.status != "replied":
                ec.replied = True
                ec.status = "replied"
                if not ec.replied_at:
                    ec.replied_at = ensure_utc(datetime.now(timezone.utc))
                repaired["reply_campaigns_from_responses_updated"] += 1
        if repaired["reply_campaigns_from_responses_updated"]:
            db.commit()

        # 3) Ensure EmailCampaign status=replied implies replied=True/replied_at
        need_sync = (
            db.query(EmailCampaign)
            .filter(EmailCampaign.status == "replied", EmailCampaign.replied.is_(False))
            .all()
        )
        if need_sync:
            now = ensure_utc(datetime.now(timezone.utc))
            for c in need_sync:
                c.replied = True
                if not c.replied_at:
                    c.replied_at = now
            db.commit()
            repaired["reply_campaigns_missing_replied_sync"] = len(need_sync)

        # 4) Detect duplicate responses per (student_id, hr_id)
        #    We do not delete duplicates; we only report.
        dup_rows = (
            db.query(Response.student_id, Response.hr_id, db.query(Response.id).count())
        )

        # Better duplicate detection without complex SQLAlchemy aggregates:
        # count rows in Python for small datasets.
        resp_counts = {}
        all_responses = db.query(Response.student_id, Response.hr_id).all()
        for sid, hid in all_responses:
            key = (str(sid), str(hid))
            resp_counts[key] = resp_counts.get(key, 0) + 1
        duplicates_detected["responses_per_student_hr"] = sum(1 for v in resp_counts.values() if v > 1)

        # 5) Create missing Response rows for replied campaigns
        replied_campaigns = (
            db.query(EmailCampaign)
            .filter(EmailCampaign.status == "replied")
            .all()
        )
        for c in replied_campaigns:
            has_response = (
                db.query(Response)
                .filter(Response.student_id == c.student_id, Response.hr_id == c.hr_id)
                .first()
                is not None
            )
            if has_response:
                continue

            rt = (c.reply_type or "").strip().upper()
            resp_type = "other"
            if rt in ("INTERESTED", "INTERVIEW"):
                resp_type = "positive"
            elif rt == "REJECTED":
                resp_type = "negative"
            r = Response(
                student_id=c.student_id,
                hr_id=c.hr_id,
                response_date=date.today(),
                response_type=resp_type,
                notes=c.reply_snippet,
                source_email_type=c.email_type,
                source_sequence_number=c.sequence_number,
                source_campaign_id=c.id,
            )
            db.add(r)
            repaired["responses_created_for_replied_campaigns"] += 1
        if repaired["responses_created_for_replied_campaigns"]:
            db.commit()

        # Final health summary
        sent = db.query(EmailCampaign).filter(EmailCampaign.status == "sent").count()
        failed = db.query(EmailCampaign).filter(EmailCampaign.status == "failed").count()
        replied = db.query(EmailCampaign).filter(EmailCampaign.status == "replied").count()
        resp_total = db.query(Response).count()

        replied_pairs = (
            db.query(EmailCampaign.student_id, EmailCampaign.hr_id)
            .filter(EmailCampaign.status == "replied")
            .distinct()
            .all()
        )
        replied_pairs = [(str(a), str(b)) for a, b in replied_pairs]

        missing_response_pairs = 0
        for sid, hid in replied_pairs:
            exists = (
                db.query(Response)
                .filter(Response.student_id == sid, Response.hr_id == hid)
                .first()
                is not None
            )
            if not exists:
                missing_response_pairs += 1

        health = {
            "EmailCampaign": {"sent": sent, "failed": failed, "replied": replied},
            "Response": {
                "total": resp_total,
                "duplicates_per_student_hr": duplicates_detected["responses_per_student_hr"],
                "missing_response_pairs_for_replied_campaigns": missing_response_pairs,
            },
            "Repaired": repaired,
            "status": "ok" if missing_response_pairs == 0 else "needs_attention",
        }

        print(health)
    finally:
        db.close()


if __name__ == "__main__":
    main()

