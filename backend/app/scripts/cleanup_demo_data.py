"""
Safe cleanup of likely seeded/demo/synthetic rows (non-destructive unless --apply).

Requires DATABASE_URL. Destructive mode requires ``--apply`` and ``--i-understand``.

Suggested flow:
  1) python -m app.scripts.cleanup_demo_data
  2) python -m app.scripts.cleanup_demo_data --export-dir ./cleanup_export
  3) python -m app.scripts.cleanup_demo_data --apply --i-understand --export-dir ./cleanup_export

HR scores, priority queue, and ``/analytics/summary`` are computed on read — there is
no persisted queue or analytics table to refresh after deletion.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import not_, or_
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class CleanupPreview:
    student_ids: list[str]
    hr_ids: list[str]
    student_reasons: dict[str, list[str]]
    hr_reasons: dict[str, list[str]]
    assignment_count: int
    email_campaign_count: int
    campaign_entity_count: int
    response_count: int
    interview_count: int
    notification_count: int
    hr_ignore_count: int
    student_template_count: int
    blocked_hr_count: int
    orphan_campaign_ids: list[str]


def _chunked(xs: list[UUID], size: int = 400) -> list[list[UUID]]:
    return [xs[i : i + size] for i in range(0, len(xs), size)]


def _chunked_str(xs: list[str], size: int = 400) -> list[list[str]]:
    return [xs[i : i + size] for i in range(0, len(xs), size)]


def _parse_uuid_set(raw: str | None) -> set[UUID]:
    if not raw:
        return set()
    out: set[UUID] = set()
    for part in raw.replace(";", ",").split(","):
        p = part.strip()
        if not p:
            continue
        out.add(UUID(p))
    return out


def _export_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")


def _export_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in columns})


def build_preview(
    db: Session,
    *,
    min_score: int,
    only_is_demo: bool,
    protect_student_ids: set[UUID],
    protect_hr_ids: set[UUID],
) -> CleanupPreview:
    from app.models import (
        Assignment,
        Campaign,
        EmailCampaign,
        HRContact,
        HRIgnored,
        Interview,
        Notification,
        Response,
        Student,
        StudentTemplate,
        BlockedHR,
    )
    from app.services.demo_data_heuristics import assess_hr, assess_student

    student_rows = db.query(Student).all()
    hr_rows = db.query(HRContact).all()

    student_reasons: dict[str, list[str]] = {}
    hr_reasons: dict[str, list[str]] = {}
    student_ids: list[UUID] = []
    hr_ids: list[UUID] = []

    for s in student_rows:
        if s.id in protect_student_ids:
            continue
        if only_is_demo and not s.is_demo:
            continue
        r = assess_student(name=s.name, gmail_address=s.gmail_address, is_demo=s.is_demo)
        if r.score >= min_score:
            student_ids.append(s.id)
            student_reasons[str(s.id)] = [*(r.reasons or ()), f"risk_score:{r.score}"]

    for h in hr_rows:
        if h.id in protect_hr_ids:
            continue
        if only_is_demo and not h.is_demo:
            continue
        r = assess_hr(name=h.name, company=h.company, email=h.email, is_demo=h.is_demo)
        if r.score >= min_score:
            hr_ids.append(h.id)
            hr_reasons[str(h.id)] = [*(r.reasons or ()), f"risk_score:{r.score}"]

    s_set = set(student_ids)
    h_set = set(hr_ids)

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
        db.query(Interview)
        .filter(or_(Interview.student_id.in_(s_set), Interview.hr_id.in_(h_set)))
        .count()
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
        student_reasons=student_reasons,
        hr_reasons=hr_reasons,
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


def run_export(db: Session, preview: CleanupPreview, export_dir: Path, min_score: int) -> Path:
    from app.models import Assignment, EmailCampaign, HRContact, Student

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    root = export_dir / f"demo_cleanup_snapshot_{ts}"
    root.mkdir(parents=True, exist_ok=True)

    s_ids = [UUID(x) for x in preview.student_ids]
    h_ids = [UUID(x) for x in preview.hr_ids]
    s_set, h_set = set(s_ids), set(h_ids)

    meta = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "min_score": min_score,
        "student_ids": preview.student_ids,
        "hr_ids": preview.hr_ids,
        "counts": asdict(preview),
    }
    (root / "manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    rows_s: list[dict[str, Any]] = []
    if s_ids:
        for ch in _chunked(s_ids):
            for s in db.query(Student).filter(Student.id.in_(ch)).all():
                rows_s.append(
                    {
                        "id": str(s.id),
                        "name": s.name,
                        "gmail_address": s.gmail_address,
                        "is_demo": s.is_demo,
                        "status": s.status,
                        "reasons": preview.student_reasons.get(str(s.id), []),
                    }
                )
    _export_jsonl(root / "students.jsonl", rows_s)
    _export_csv(
        root / "students.csv",
        ["id", "name", "gmail_address", "is_demo", "status", "reasons"],
        [{**r, "reasons": ";".join(r["reasons"])} for r in rows_s],
    )

    rows_h: list[dict[str, Any]] = []
    if h_ids:
        for ch in _chunked(h_ids):
            for h in db.query(HRContact).filter(HRContact.id.in_(ch)).all():
                rows_h.append(
                    {
                        "id": str(h.id),
                        "name": h.name,
                        "company": h.company,
                        "email": h.email,
                        "is_demo": h.is_demo,
                        "status": h.status,
                        "reasons": preview.hr_reasons.get(str(h.id), []),
                    }
                )
    _export_jsonl(root / "hr_contacts.jsonl", rows_h)
    _export_csv(
        root / "hr_contacts.csv",
        ["id", "name", "company", "email", "is_demo", "status", "reasons"],
        [{**r, "reasons": ";".join(r["reasons"])} for r in rows_h],
    )

    rows_a: list[dict[str, Any]] = []
    if s_set or h_set:
        for a in db.query(Assignment).filter(or_(Assignment.student_id.in_(s_set), Assignment.hr_id.in_(h_set))).all():
            rows_a.append({"id": str(a.id), "student_id": str(a.student_id), "hr_id": str(a.hr_id), "status": a.status})
    _export_jsonl(root / "assignments.jsonl", rows_a)

    rows_c: list[dict[str, Any]] = []
    if s_set or h_set:
        q = db.query(EmailCampaign).filter(or_(EmailCampaign.student_id.in_(s_set), EmailCampaign.hr_id.in_(h_set)))
        for c in q.all():
            rows_c.append(
                {
                    "id": str(c.id),
                    "student_id": str(c.student_id),
                    "hr_id": str(c.hr_id),
                    "campaign_id": str(c.campaign_id) if c.campaign_id else None,
                    "sequence_number": c.sequence_number,
                    "status": c.status,
                }
            )
    _export_jsonl(root / "email_campaigns.jsonl", rows_c)

    logger.info("Export written under %s", root)
    return root


def run_delete(
    db: Session,
    preview: CleanupPreview,
    *,
    clean_blocked_hrs: bool,
    clean_audit_logs: bool,
) -> None:
    from app.models import (
        Assignment,
        AuditLog,
        Campaign,
        EmailCampaign,
        HRContact,
        HRIgnored,
        Interview,
        Notification,
        Response,
        Student,
        StudentTemplate,
        BlockedHR,
    )

    s_ids = [UUID(x) for x in preview.student_ids]
    h_ids = [UUID(x) for x in preview.hr_ids]
    s_set, h_set = set(s_ids), set(h_ids)
    if not s_set and not h_set:
        return

    blocked_emails: list[str] = []
    if clean_blocked_hrs and h_set:
        for ch in _chunked(list(h_set)):
            blocked_emails.extend(
                r[0].strip().lower() for r in db.query(HRContact.email).filter(HRContact.id.in_(ch)).all() if r[0]
            )

    ec_ids: list[UUID] = [
        r[0]
        for r in db.query(EmailCampaign.id)
        .filter(or_(EmailCampaign.student_id.in_(s_set), EmailCampaign.hr_id.in_(h_set)))
        .all()
    ]

    if ec_ids:
        for ch in _chunked(ec_ids):
            db.query(Response).filter(Response.source_campaign_id.in_(ch)).delete(synchronize_session=False)
    db.query(Response).filter(or_(Response.student_id.in_(s_set), Response.hr_id.in_(h_set))).delete(
        synchronize_session=False
    )

    if ec_ids:
        for ch in _chunked(ec_ids):
            db.query(Notification).filter(Notification.reply_for_campaign_id.in_(ch)).delete(synchronize_session=False)

    db.query(EmailCampaign).filter(or_(EmailCampaign.student_id.in_(s_set), EmailCampaign.hr_id.in_(h_set))).delete(
        synchronize_session=False
    )
    db.query(Assignment).filter(or_(Assignment.student_id.in_(s_set), Assignment.hr_id.in_(h_set))).delete(
        synchronize_session=False
    )
    db.query(Interview).filter(or_(Interview.student_id.in_(s_set), Interview.hr_id.in_(h_set))).delete(
        synchronize_session=False
    )
    db.query(HRIgnored).filter(or_(HRIgnored.student_id.in_(s_set), HRIgnored.hr_id.in_(h_set))).delete(
        synchronize_session=False
    )
    if s_set:
        db.query(StudentTemplate).filter(StudentTemplate.student_id.in_(s_set)).delete(synchronize_session=False)

    if s_set:
        db.query(Campaign).filter(Campaign.student_id.in_(s_set)).delete(synchronize_session=False)

    for cid_str in preview.orphan_campaign_ids:
        cid = UUID(cid_str)
        if db.query(EmailCampaign).filter(EmailCampaign.campaign_id == cid).count() == 0:
            db.query(Campaign).filter(Campaign.id == cid).delete(synchronize_session=False)

    if s_set:
        db.query(Student).filter(Student.id.in_(s_set)).delete(synchronize_session=False)
    if h_set:
        db.query(HRContact).filter(HRContact.id.in_(h_set)).delete(synchronize_session=False)

    if clean_blocked_hrs and blocked_emails:
        for i in range(0, len(blocked_emails), 400):
            part = blocked_emails[i : i + 400]
            db.query(BlockedHR).filter(BlockedHR.email.in_(part)).delete(synchronize_session=False)

    if clean_audit_logs and (s_set or h_set):
        all_str = [str(u) for u in s_set] + [str(u) for u in h_set]
        for ch in _chunked_str(all_str):
            db.query(AuditLog).filter(AuditLog.entity_id.in_(ch)).delete(synchronize_session=False)

    db.flush()


def _print_preview(preview: CleanupPreview) -> None:
    print("=== Demo / synthetic cleanup preview ===\n")
    print(f"Students flagged: {len(preview.student_ids)}")
    for sid in preview.student_ids[:50]:
        print(f"  - {sid}  reasons={';'.join(preview.student_reasons.get(sid, []))}")
    if len(preview.student_ids) > 50:
        print(f"  ... and {len(preview.student_ids) - 50} more")

    print(f"\nHR contacts flagged: {len(preview.hr_ids)}")
    for hid in preview.hr_ids[:50]:
        print(f"  - {hid}  reasons={';'.join(preview.hr_reasons.get(hid, []))}")
    if len(preview.hr_ids) > 50:
        print(f"  ... and {len(preview.hr_ids) - 50} more")

    print("\n=== Linked rows (will be removed with FK-safe order) ===")
    print(f"  assignments:              {preview.assignment_count}")
    print(f"  email_campaigns:          {preview.email_campaign_count}")
    print(f"  responses:                {preview.response_count}")
    print(f"  interviews:               {preview.interview_count}")
    print(f"  notifications:            {preview.notification_count}")
    print(f"  hr_ignores:               {preview.hr_ignore_count}")
    print(f"  student_templates:        {preview.student_template_count}")
    print(f"  campaigns (approx):       {preview.campaign_entity_count}")
    print(f"  blocked_hrs (matched):    {preview.blocked_hr_count}")
    if preview.orphan_campaign_ids:
        print(f"  orphan campaign_ids:      {len(preview.orphan_campaign_ids)}")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    argv = argv if argv is not None else sys.argv[1:]

    p = argparse.ArgumentParser(description="Preview or remove likely demo/synthetic DB rows.")
    p.add_argument("--min-score", type=int, default=50, help="Minimum heuristic risk score (is_demo=100, disposable domain=50).")
    p.add_argument(
        "--only-is-demo",
        action="store_true",
        help="Only consider rows with is_demo=true (safest narrow cleanup).",
    )
    p.add_argument("--protect-student-ids", type=str, default=None, help="Comma-separated UUIDs never to delete.")
    p.add_argument("--protect-hr-ids", type=str, default=None, help="Comma-separated UUIDs never to delete.")
    p.add_argument("--export-dir", type=str, default=None, help="Directory for JSONL/CSV snapshot before apply.")
    p.add_argument("--apply", action="store_true", help="Perform destructive delete (requires --i-understand).")
    p.add_argument("--i-understand", action="store_true", help="Acknowledge irreversible data loss.")
    p.add_argument("--no-clean-blocked-hrs", action="store_true", help="Do not delete blocked_hrs rows matching removed HR emails.")
    p.add_argument("--clean-audit-logs", action="store_true", help="Also delete audit_logs rows whose entity_id matches removed UUIDs.")

    args = p.parse_args(argv)

    if args.apply and not args.i_understand:
        print("Refusing --apply without --i-understand.", file=sys.stderr)
        return 2

    try:
        from app.database.config import SessionLocal
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    protect_s = _parse_uuid_set(args.protect_student_ids)
    protect_h = _parse_uuid_set(args.protect_hr_ids)

    db = SessionLocal()
    try:
        preview = build_preview(
            db,
            min_score=args.min_score,
            only_is_demo=args.only_is_demo,
            protect_student_ids=protect_s,
            protect_hr_ids=protect_h,
        )
        _print_preview(preview)

        export_root: Path | None = None
        if args.export_dir:
            export_root = run_export(db, preview, Path(args.export_dir), args.min_score)
            print(f"\nSnapshot written to: {export_root}")

        if args.apply:
            if not args.export_dir:
                logger.warning("You ran --apply without --export-dir; no automatic JSONL backup was written.")
            run_delete(
                db,
                preview,
                clean_blocked_hrs=not args.no_clean_blocked_hrs,
                clean_audit_logs=args.clean_audit_logs,
            )
            db.commit()
            print("\nCommitted: demo/synthetic rows and linked data removed.")
        else:
            db.rollback()
            print("\nDry run only (no changes). Re-run with --apply --i-understand to delete.")
        return 0
    except Exception:
        db.rollback()
        logger.exception("Cleanup failed")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
