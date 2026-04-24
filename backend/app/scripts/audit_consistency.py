"""
Audit: scoped DB counts vs /analytics fields and sheet export alignment.

Run from backend root:
  python -m app.scripts.audit_consistency
  python -m app.scripts.audit_consistency --sync   # push pending rows to sheets via sync_new_replies + sync_blocked_hrs
"""
from __future__ import annotations

import argparse

from sqlalchemy import and_, case, func, or_

from app.database.config import SessionLocal
from app.models import BlockedHR, EmailCampaign, HRContact
from app.routers.analytics import get_analytics_summary, get_email_status
from app.utils.campaign_query_filters import email_campaigns_scoped_to_hr


def _reply_export_predicate():
    """Same idea as sheet_sync: rows eligible for Replies tab (not yet counting exported flag)."""
    normalized_reply = and_(
        EmailCampaign.reply_status.isnot(None),
        EmailCampaign.reply_status.notin_(("BOUNCED", "BLOCKED", "TEMP_FAIL", "BOUNCE")),
        or_(
            and_(
                EmailCampaign.reply_text.isnot(None),
                func.length(func.trim(EmailCampaign.reply_text)) > 0,
            ),
            and_(
                EmailCampaign.reply_snippet.isnot(None),
                func.length(func.trim(EmailCampaign.reply_snippet)) > 0,
            ),
        ),
    )
    legacy_reply = and_(
        EmailCampaign.reply_status.is_(None),
        EmailCampaign.status == "replied",
        EmailCampaign.replied.is_(True),
        or_(
            and_(
                EmailCampaign.reply_text.isnot(None),
                func.length(func.trim(EmailCampaign.reply_text)) > 0,
            ),
            and_(
                EmailCampaign.reply_snippet.isnot(None),
                func.length(func.trim(EmailCampaign.reply_snippet)) > 0,
            ),
        ),
    )
    return or_(
        EmailCampaign.replied.is_(True),
        EmailCampaign.status == "replied",
    ), or_(normalized_reply, legacy_reply)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Run sync_new_replies + sync_blocked_hrs after audit (reduces pending export drift).",
    )
    args = parser.parse_args()
    db = SessionLocal()
    mismatches: list[str] = []
    try:
        include_demo = False
        base = email_campaigns_scoped_to_hr(db, include_demo=include_demo)

        db_failed = (
            base.filter(EmailCampaign.status == "failed")
            .with_entities(func.count(EmailCampaign.id))
            .scalar()
            or 0
        )
        db_bounced = base.filter(EmailCampaign.reply_status == "BOUNCED").count()
        db_blocked = base.filter(EmailCampaign.reply_status == "BLOCKED").count()
        db_replies = (
            base.filter(EmailCampaign.replied.is_(True))
            .with_entities(func.count(EmailCampaign.id))
            .scalar()
            or 0
        )
        db_total_failed_lt = (
            base.with_entities(
                func.coalesce(
                    func.sum(case((EmailCampaign.status == "failed", 1), else_=0)), 0
                )
            ).scalar()
            or 0
        )

        pred_or, pred_body = _reply_export_predicate()
        reply_eligible = (
            db.query(EmailCampaign)
            .join(HRContact, EmailCampaign.hr_id == HRContact.id)
            .filter(HRContact.is_demo.is_(False), pred_or, pred_body)
            .count()
        )
        reply_exported = (
            db.query(EmailCampaign)
            .join(HRContact, EmailCampaign.hr_id == HRContact.id)
            .filter(
                HRContact.is_demo.is_(False),
                pred_or,
                pred_body,
                EmailCampaign.exported_to_sheet.is_(True),
            )
            .count()
        )
        reply_pending = reply_eligible - reply_exported

        failed_exported = (
            db.query(EmailCampaign)
            .join(HRContact, EmailCampaign.hr_id == HRContact.id)
            .filter(
                HRContact.is_demo.is_(False),
                EmailCampaign.status == "failed",
                EmailCampaign.exported_failure_sheet.is_(True),
            )
            .count()
        )
        failed_total = db_failed
        failed_pending = failed_total - failed_exported

        bounce_export_predicate = EmailCampaign.reply_status.in_(("BOUNCED", "BLOCKED", "BOUNCE"))
        bounce_total = (
            db.query(EmailCampaign)
            .join(HRContact, EmailCampaign.hr_id == HRContact.id)
            .filter(HRContact.is_demo.is_(False), bounce_export_predicate)
            .count()
        )
        bounce_exported = (
            db.query(EmailCampaign)
            .join(HRContact, EmailCampaign.hr_id == HRContact.id)
            .filter(
                HRContact.is_demo.is_(False),
                bounce_export_predicate,
                EmailCampaign.exported_bounce_sheet.is_(True),
            )
            .count()
        )
        bounce_pending = bounce_total - bounce_exported

        non_demo_emails = (
            db.query(HRContact.email)
            .filter(HRContact.is_demo.is_(False))
            .distinct()
        )
        blocked_hr_table = (
            db.query(func.count(BlockedHR.id))
            .filter(BlockedHR.email.in_(non_demo_emails))
            .scalar()
            or 0
        )

        # API-shaped payloads (same functions as HTTP)
        summ = get_analytics_summary(include_demo=include_demo, db=db)
        status = get_email_status(include_demo=include_demo, db=db)

        if int(summ.get("emails_failed", -1)) != db_failed:
            mismatches.append(
                f"summary.emails_failed ({summ.get('emails_failed')}) != scoped DB failed ({db_failed})"
            )
        if int(summ.get("total_failed", -1)) != int(db_total_failed_lt):
            mismatches.append(
                f"summary.total_failed ({summ.get('total_failed')}) != scoped sum failed ({db_total_failed_lt})"
            )
        if int(summ.get("total_bounced", -1)) != db_bounced:
            mismatches.append(
                f"summary.total_bounced ({summ.get('total_bounced')}) != DB BOUNCED ({db_bounced})"
            )
        if int(summ.get("blocked_hr_count", -1)) != db_blocked:
            mismatches.append(
                f"summary.blocked_hr_count ({summ.get('blocked_hr_count')}) != DB BLOCKED ({db_blocked})"
            )
        if int(summ.get("total_replies", -1)) != db_replies:
            mismatches.append(
                f"summary.total_replies ({summ.get('total_replies')}) != DB replied=True ({db_replies})"
            )
        if int(status.get("failed", -1)) != db_failed:
            mismatches.append(
                f"email-status.failed ({status.get('failed')}) != scoped DB failed ({db_failed})"
            )
        if int(status.get("total_replies", -1)) != db_replies:
            mismatches.append(
                f"email-status.total_replies ({status.get('total_replies')}) != DB replied=True ({db_replies})"
            )
        if int(status.get("total_bounced", -1)) != db_bounced:
            mismatches.append("email-status.total_bounced != summary/DB BOUNCED")

        print("=== Scoped DB (non-demo HR) ===")
        print("failed rows:", db_failed)
        print("total_failed (sum status=failed):", int(db_total_failed_lt))
        print("reply_status BOUNCED:", db_bounced)
        print("reply_status BLOCKED (blocked_hr_count KPI):", db_blocked)
        print("replied=True:", db_replies)
        print("blocked_hrs table rows (non-demo HR email match):", blocked_hr_table)
        print()
        print("=== Sheet export flags (DB) ===")
        print("Replies: eligible", reply_eligible, "| exported", reply_exported, "| pending", reply_pending)
        print("Failures: total", failed_total, "| exported", failed_exported, "| pending", failed_pending)
        print("Bounces tab cohort: total", bounce_total, "| exported", bounce_exported, "| pending", bounce_pending)
        print()
        print("=== /analytics/summary (key fields) ===")
        for k in (
            "emails_failed",
            "total_failed",
            "total_bounced",
            "blocked_hr_count",
            "total_replies",
            "failed",
        ):
            if k in summ:
                print(f"  {k}: {summ[k]}")
        print("=== /analytics/email-status (key fields) ===")
        for k in ("failed", "total_replies", "total_bounced", "blocked_hr_count"):
            if k in status:
                print(f"  {k}: {status[k]}")

        sheet_info: list[str] = []
        try:
            from app.services.google_sheets import get_blocked_sheet, get_sheet

            def _body_rows(ws) -> int:
                rows = ws.get_all_values()
                if not rows:
                    return 0
                if rows and rows[0] and any(str(c).strip() for c in rows[0]):
                    return max(0, len(rows) - 1)
                return len(rows)

            for title in ("Replies", "Failures", "Bounces"):
                n = _body_rows(get_sheet(title))
                sheet_info.append(f"{title}: {n} data rows (excl. header if present)")
            sheet_info.append(f"Blocked HRs: {_body_rows(get_blocked_sheet())} data rows")
        except Exception as e:
            sheet_info.append(f"(sheet read skipped: {e})")

        print()
        print("=== Google Sheet (row counts; mirror may include manual edits) ===")
        for line in sheet_info:
            print(" ", line)

        print()
        if mismatches:
            print("MISMATCHES (API vs DB):")
            for m in mismatches:
                print(" -", m)
        else:
            print("API vs scoped DB: OK (no mismatches).")

        print()
        print("NOTES:")
        print(
            " - total_bounced counts reply_status=BOUNCED only; Bounces sheet also exports BLOCKED/BOUNCE."
        )
        print(
            " - blocked_hr_count is campaign rows with reply_status=BLOCKED, not blocked_hrs table count."
        )
        print(f" - blocked_hrs table (non-demo): {blocked_hr_table} (informational vs KPI above).")

        if args.sync:
            from app.services.blocked_hr_sync import sync_blocked_hrs
            from app.services.sheet_sync import sync_new_replies

            sync_new_replies(db)
            sync_blocked_hrs(db)
            print()
            print("Ran sync_new_replies + sync_blocked_hrs.")

    finally:
        db.close()

    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
