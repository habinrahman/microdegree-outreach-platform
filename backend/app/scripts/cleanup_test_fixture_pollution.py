"""
Purge rows that match **pytest fixture email local-part prefixes** (see ``fixture_email_guard``).

Does not use demo heuristics — only the explicit prefix list used by backend tests.

Examples:
  python -m app.scripts.cleanup_test_fixture_pollution --audit
  python -m app.scripts.cleanup_test_fixture_pollution --dry-run
  python -m app.scripts.cleanup_test_fixture_pollution --apply --i-understand
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any
from uuid import UUID

from sqlalchemy import not_, or_
from sqlalchemy.orm import Session

from app.database.config import SessionLocal
from app.database.fixture_email_guard import (
    ALWAYS_BLOCKED_SYNTHETIC_EMAIL_LOCAL_PREFIXES,
    DISPOSABLE_DOMAIN_BLOCKED_LOCAL_PREFIXES,
    email_matches_blocked_fixture_taxonomy,
)
from app.scripts.cleanup_demo_data import CleanupPreview, _chunked, run_delete

logger = logging.getLogger(__name__)


def build_fixture_pollution_audit_report(db: Session) -> dict[str, Any]:
    """
    Read-only snapshot: synthetic rows by prefix, totals, and dangling FK rows
    (assignments / email_campaigns / responses pointing at missing parents).
    """
    from app.models import Assignment, EmailCampaign, HRContact, Response, Student

    all_prefixes_unsorted = (*ALWAYS_BLOCKED_SYNTHETIC_EMAIL_LOCAL_PREFIXES, *DISPOSABLE_DOMAIN_BLOCKED_LOCAL_PREFIXES)
    # Longer first so bucketing is stable (e.g. s2_ shouldn't count as s_).
    all_prefixes = tuple(sorted(all_prefixes_unsorted, key=len, reverse=True))
    st_by_prefix: dict[str, int] = {p: 0 for p in all_prefixes}
    hr_by_prefix: dict[str, int] = {p: 0 for p in all_prefixes}
    synthetic_students = 0
    synthetic_hrs = 0

    for s in db.query(Student).all():
        if not email_matches_blocked_fixture_taxonomy(s.gmail_address):
            continue
        synthetic_students += 1
        local = s.gmail_address.split("@", 1)[0].strip().lower()
        for p in all_prefixes:
            if local.startswith(p):
                st_by_prefix[p] += 1
                break

    for h in db.query(HRContact).all():
        if not email_matches_blocked_fixture_taxonomy(h.email):
            continue
        synthetic_hrs += 1
        local = h.email.split("@", 1)[0].strip().lower()
        for p in all_prefixes:
            if local.startswith(p):
                hr_by_prefix[p] += 1
                break

    student_ids = {s.id for s in db.query(Student).all()}
    hr_ids = {h.id for h in db.query(HRContact).all()}
    campaign_ids = {c.id for c in db.query(EmailCampaign).all()}

    orphan_assignments = 0
    for a in db.query(Assignment).all():
        if a.student_id not in student_ids or a.hr_id not in hr_ids:
            orphan_assignments += 1

    orphan_email_campaigns = 0
    for c in db.query(EmailCampaign).all():
        if c.student_id not in student_ids or c.hr_id not in hr_ids:
            orphan_email_campaigns += 1

    orphan_responses = 0
    for r in db.query(Response).all():
        if r.student_id not in student_ids or r.hr_id not in hr_ids:
            orphan_responses += 1
        elif r.source_campaign_id is not None and r.source_campaign_id not in campaign_ids:
            orphan_responses += 1

    return {
        "synthetic_students_total": synthetic_students,
        "synthetic_hr_contacts_total": synthetic_hrs,
        "synthetic_students_by_prefix": st_by_prefix,
        "synthetic_hr_contacts_by_prefix": hr_by_prefix,
        "orphan_assignments": orphan_assignments,
        "orphan_email_campaigns": orphan_email_campaigns,
        "orphan_responses": orphan_responses,
        "prefix_list": list(all_prefixes),
    }


def _scan_fixture_targets(db: Session) -> tuple[list[UUID], list[UUID], dict[str, list[str]], dict[str, list[str]]]:
    from app.models import HRContact, Student

    student_ids: list[UUID] = []
    hr_ids: list[UUID] = []
    sr: dict[str, list[str]] = {}
    hr: dict[str, list[str]] = {}
    for s in db.query(Student).all():
        if email_matches_blocked_fixture_taxonomy(s.gmail_address) or getattr(s, "is_fixture_test_data", False):
            student_ids.append(s.id)
            sr[str(s.id)] = ["fixture_email_prefix", str(s.gmail_address)]
    for h in db.query(HRContact).all():
        if email_matches_blocked_fixture_taxonomy(h.email) or getattr(h, "is_fixture_test_data", False):
            hr_ids.append(h.id)
            hr[str(h.id)] = ["fixture_email_prefix", str(h.email)]
    return student_ids, hr_ids, sr, hr


def _build_preview(db: Session, student_ids: list[UUID], hr_ids: list[UUID], sr: dict, hr_r: dict) -> CleanupPreview:
    from app.models import Assignment, Campaign, EmailCampaign, HRIgnored, Interview, Notification, Response, StudentTemplate, BlockedHR, HRContact

    s_set, h_set = set(student_ids), set(hr_ids)
    if not s_set and not h_set:
        return CleanupPreview(
            student_ids=[],
            hr_ids=[],
            student_reasons={},
            hr_reasons={},
            assignment_count=0,
            email_campaign_count=0,
            campaign_entity_count=0,
            response_count=0,
            interview_count=0,
            notification_count=0,
            hr_ignore_count=0,
            student_template_count=0,
            blocked_hr_count=0,
            orphan_campaign_ids=[],
        )

    ec_ids = [
        r[0]
        for r in db.query(EmailCampaign.id)
        .filter(or_(EmailCampaign.student_id.in_(s_set), EmailCampaign.hr_id.in_(h_set)))
        .all()
    ]
    doomed_ec_set = set(ec_ids)

    camp_ids = {
        r[0]
        for r in db.query(EmailCampaign.campaign_id)
        .filter(or_(EmailCampaign.student_id.in_(s_set), EmailCampaign.hr_id.in_(h_set)), EmailCampaign.campaign_id.isnot(None))
        .distinct()
        .all()
        if r[0] is not None
    }

    asg = db.query(Assignment).filter(or_(Assignment.student_id.in_(s_set), Assignment.hr_id.in_(h_set))).count()
    ec_count = len(ec_ids)

    resp_parts = [Response.student_id.in_(s_set), Response.hr_id.in_(h_set)]
    if ec_ids:
        resp_parts.append(Response.source_campaign_id.in_(ec_ids))
    resp = db.query(Response).filter(or_(*resp_parts)).count()

    intr = (
        db.query(Interview).filter(or_(Interview.student_id.in_(s_set), Interview.hr_id.in_(h_set))).count()
    )

    notif = 0
    if ec_ids:
        for chunk in _chunked(ec_ids):
            notif += db.query(Notification).filter(Notification.reply_for_campaign_id.in_(chunk)).count()

    ign = db.query(HRIgnored).filter(or_(HRIgnored.student_id.in_(s_set), HRIgnored.hr_id.in_(h_set))).count()
    tmpl = 0
    if s_set:
        tmpl = db.query(StudentTemplate).filter(StudentTemplate.student_id.in_(s_set)).count()

    blocked = 0
    if h_set:
        elower: list[str] = []
        for ch in _chunked(list(h_set)):
            elower.extend(r[0].strip().lower() for r in db.query(HRContact.email).filter(HRContact.id.in_(ch)).all() if r[0])
        for i in range(0, len(elower), 400):
            part = elower[i : i + 400]
            blocked += db.query(BlockedHR).filter(BlockedHR.email.in_(part)).count()

    orphan_campaign_ids: list[str] = []
    for cid in camp_ids:
        total = db.query(EmailCampaign.id).filter(EmailCampaign.campaign_id == cid).count()
        if total == 0:
            continue
        outside = (
            db.query(EmailCampaign.id)
            .filter(EmailCampaign.campaign_id == cid, not_(EmailCampaign.id.in_(doomed_ec_set)))
            .count()
        )
        if outside == 0:
            orphan_campaign_ids.append(str(cid))

    student_campaigns = db.query(Campaign.id).filter(Campaign.student_id.in_(s_set)).count() if s_set else 0
    camp_entity = int(student_campaigns) + len(orphan_campaign_ids)

    return CleanupPreview(
        student_ids=[str(x) for x in student_ids],
        hr_ids=[str(x) for x in hr_ids],
        student_reasons=sr,
        hr_reasons=hr_r,
        assignment_count=int(asg),
        email_campaign_count=int(ec_count),
        campaign_entity_count=int(camp_entity),
        response_count=int(resp),
        interview_count=int(intr),
        notification_count=int(notif),
        hr_ignore_count=int(ign),
        student_template_count=int(tmpl),
        blocked_hr_count=int(blocked),
        orphan_campaign_ids=orphan_campaign_ids,
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--audit",
        action="store_true",
        help="Read-only JSON report: synthetic counts by prefix + orphan FK rows (no writes).",
    )
    p.add_argument("--dry-run", action="store_true", help="Print counts only (default if neither flag).")
    p.add_argument("--apply", action="store_true", help="Perform deletion after export.")
    p.add_argument("--i-understand", action="store_true", help="Required with --apply.")
    p.add_argument("--clean-blocked-hrs", action="store_true", help="Also delete blocked_hrs rows for removed HR emails.")
    p.add_argument("--clean-audit-logs", action="store_true", help="Also delete audit_logs rows keyed by removed UUID strings.")
    args = p.parse_args(argv)

    if args.audit and (args.apply or args.dry_run):
        print("Use --audit without --apply/--dry-run (audit is read-only).", file=sys.stderr)
        return 2

    if args.audit:
        db = SessionLocal()
        try:
            print(json.dumps(build_fixture_pollution_audit_report(db), indent=2))
            return 0
        finally:
            db.close()

    dry = args.dry_run or not args.apply
    if args.apply and not args.i_understand:
        print("Refusing --apply without --i-understand", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        s_ids, h_ids, sr, hr_r = _scan_fixture_targets(db)
        preview = _build_preview(db, s_ids, h_ids, sr, hr_r)
        print("=== Test fixture prefix cleanup ===")
        print(f"students matched: {len(preview.student_ids)}")
        print(f"hr_contacts matched: {len(preview.hr_ids)}")
        print(f"assignments (linked): {preview.assignment_count}")
        print(f"email_campaigns (linked): {preview.email_campaign_count}")
        print(f"responses (linked): {preview.response_count}")
        print(f"orphan campaign entities: {len(preview.orphan_campaign_ids)}")
        if dry:
            print("\nDry run only. Pass --apply --i-understand to delete.")
            return 0
        run_delete(
            db,
            preview,
            clean_blocked_hrs=args.clean_blocked_hrs,
            clean_audit_logs=args.clean_audit_logs,
        )
        db.commit()
        print("\nApply completed.")
        return 0
    except Exception:
        db.rollback()
        logger.exception("cleanup_test_fixture_pollution failed")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
