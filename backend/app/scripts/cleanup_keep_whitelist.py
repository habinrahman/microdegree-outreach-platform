"""
Whitelist student cleanup: KEEP an explicit set (names + UUIDs), remove all other students
and their dependent rows in FK-safe order.

Commands:
  python -m app.scripts.cleanup_keep_whitelist preview
  python -m app.scripts.cleanup_keep_whitelist apply --export-dir ./snap --i-understand

Does not delete ``hr_contacts``. HR scores / analytics are computed on read.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import not_, or_
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _chunked(xs: list[UUID], size: int = 400) -> list[list[UUID]]:
    return [xs[i : i + size] for i in range(0, len(xs), size)]


def _chunked_str(xs: list[str], size: int = 400) -> list[list[str]]:
    return [xs[i : i + size] for i in range(0, len(xs), size)]


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


@dataclass
class RemoveImpact:
    """Counts of rows tied to students that will be removed."""

    remove_student_count: int = 0
    assignment_count: int = 0
    email_campaign_count: int = 0
    response_count: int = 0
    interview_count: int = 0
    notification_count: int = 0
    hr_ignore_count: int = 0
    student_template_count: int = 0
    campaign_owned_count: int = 0
    orphan_campaign_ids: list[str] = field(default_factory=list)
    email_campaign_ids: list[str] = field(default_factory=list)


def compute_remove_impact(db: Session, remove_ids: set[UUID]) -> RemoveImpact:
    from app.models import (
        Assignment,
        Campaign,
        EmailCampaign,
        HRIgnored,
        Interview,
        Notification,
        Response,
        StudentTemplate,
    )

    out = RemoveImpact()
    if not remove_ids:
        return out

    out.remove_student_count = len(remove_ids)

    ec_rows = (
        db.query(EmailCampaign.id, EmailCampaign.campaign_id)
        .filter(EmailCampaign.student_id.in_(remove_ids))
        .all()
    )
    ec_ids = [r[0] for r in ec_rows]
    out.email_campaign_count = len(ec_ids)
    out.email_campaign_ids = [str(i) for i in ec_ids]
    doomed_ec_set = set(ec_ids)

    camp_ids = {r[1] for r in ec_rows if r[1] is not None}

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
    out.orphan_campaign_ids = orphan_campaign_ids

    out.assignment_count = db.query(Assignment).filter(Assignment.student_id.in_(remove_ids)).count()
    out.student_template_count = db.query(StudentTemplate).filter(StudentTemplate.student_id.in_(remove_ids)).count()
    out.hr_ignore_count = db.query(HRIgnored).filter(HRIgnored.student_id.in_(remove_ids)).count()
    out.interview_count = db.query(Interview).filter(Interview.student_id.in_(remove_ids)).count()

    resp_parts = [Response.student_id.in_(remove_ids)]
    if ec_ids:
        resp_parts.append(Response.source_campaign_id.in_(ec_ids))
    out.response_count = db.query(Response).filter(or_(*resp_parts)).count()

    notif = 0
    if ec_ids:
        for ch in _chunked(ec_ids):
            notif += db.query(Notification).filter(Notification.reply_for_campaign_id.in_(ch)).count()
    out.notification_count = notif

    out.campaign_owned_count = db.query(Campaign.id).filter(Campaign.student_id.in_(remove_ids)).count()

    return out


def run_export_remove_snapshot(
    db: Session,
    *,
    export_dir: Path,
    remove_rows: list[tuple[UUID, str, str]],
    impact: RemoveImpact,
    resolution_manifest: dict[str, Any],
) -> Path:
    from app.models import Assignment, EmailCampaign

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    root = export_dir / f"whitelist_cleanup_{ts}"
    root.mkdir(parents=True, exist_ok=True)

    (root / "manifest.json").write_text(
        json.dumps({"generated_at_utc": datetime.now(timezone.utc).isoformat(), **resolution_manifest}, indent=2, default=str),
        encoding="utf-8",
    )

    remove_ids = {r[0] for r in remove_rows}
    rows_rm = [{"id": str(i), "name": n, "gmail_address": g} for i, n, g in remove_rows]
    _export_jsonl(root / "students_to_remove.jsonl", rows_rm)
    _export_csv(root / "students_to_remove.csv", ["id", "name", "gmail_address"], rows_rm)

    rows_a: list[dict[str, Any]] = []
    if remove_ids:
        for a in db.query(Assignment).filter(Assignment.student_id.in_(remove_ids)).all():
            rows_a.append({"id": str(a.id), "student_id": str(a.student_id), "hr_id": str(a.hr_id), "status": a.status})
    _export_jsonl(root / "assignments_to_remove.jsonl", rows_a)

    rows_c: list[dict[str, Any]] = []
    if remove_ids:
        for c in db.query(EmailCampaign).filter(EmailCampaign.student_id.in_(remove_ids)).all():
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
    _export_jsonl(root / "email_campaigns_to_remove.jsonl", rows_c)

    (root / "impact.json").write_text(json.dumps(asdict(impact), indent=2), encoding="utf-8")
    logger.info("Snapshot written to %s", root)
    return root


def run_delete_removed_students(
    db: Session,
    remove_ids: set[UUID],
    orphan_campaign_ids: list[str],
    *,
    clean_audit_logs: bool,
) -> None:
    from app.models import (
        Assignment,
        AuditLog,
        Campaign,
        EmailCampaign,
        HRIgnored,
        Interview,
        Notification,
        Response,
        Student,
        StudentTemplate,
    )

    if not remove_ids:
        return

    ec_ids: list[UUID] = [
        r[0] for r in db.query(EmailCampaign.id).filter(EmailCampaign.student_id.in_(remove_ids)).all()
    ]

    if ec_ids:
        for ch in _chunked(ec_ids):
            db.query(Response).filter(Response.source_campaign_id.in_(ch)).delete(synchronize_session=False)
    db.query(Response).filter(Response.student_id.in_(remove_ids)).delete(synchronize_session=False)

    if ec_ids:
        for ch in _chunked(ec_ids):
            db.query(Notification).filter(Notification.reply_for_campaign_id.in_(ch)).delete(synchronize_session=False)

    db.query(EmailCampaign).filter(EmailCampaign.student_id.in_(remove_ids)).delete(synchronize_session=False)
    db.query(Assignment).filter(Assignment.student_id.in_(remove_ids)).delete(synchronize_session=False)
    db.query(Interview).filter(Interview.student_id.in_(remove_ids)).delete(synchronize_session=False)
    db.query(HRIgnored).filter(HRIgnored.student_id.in_(remove_ids)).delete(synchronize_session=False)
    db.query(StudentTemplate).filter(StudentTemplate.student_id.in_(remove_ids)).delete(synchronize_session=False)

    db.query(Campaign).filter(Campaign.student_id.in_(remove_ids)).delete(synchronize_session=False)

    for cid_str in orphan_campaign_ids:
        cid = UUID(cid_str)
        if db.query(EmailCampaign).filter(EmailCampaign.campaign_id == cid).count() == 0:
            db.query(Campaign).filter(Campaign.id == cid).delete(synchronize_session=False)

    db.query(Student).filter(Student.id.in_(remove_ids)).delete(synchronize_session=False)

    if clean_audit_logs:
        all_str = [str(u) for u in remove_ids]
        for ch in _chunked_str(all_str):
            db.query(AuditLog).filter(AuditLog.entity_id.in_(ch)).delete(synchronize_session=False)

    db.flush()


def _print_report(
    *,
    resolution,
    keep_rows: list[tuple[UUID, str, str]],
    remove_rows: list[tuple[UUID, str, str]],
    impact: RemoveImpact,
    total_student_count: int,
) -> None:
    print("=== Whitelist student cleanup ===\n")

    print("--- KEEP (matched whitelist) ---")
    if not keep_rows:
        print("  (none — check tokens / DB)")
    for sid, name, em in keep_rows:
        print(f"  {sid}  |  {name!r}  |  {em}")

    print("\n--- REMOVE (not on whitelist) ---")
    if not remove_rows:
        print("  (none)")
    else:
        print(f"  count: {len(remove_rows)}")
        for sid, name, em in remove_rows[:80]:
            print(f"  {sid}  |  {name!r}  |  {em}")
        if len(remove_rows) > 80:
            print(f"  ... {len(remove_rows) - 80} more (see export CSV)")

    print("\n--- Linked rows removed with these students ---")
    print(f"  assignments:           {impact.assignment_count}")
    print(f"  email_campaigns:       {impact.email_campaign_count}")
    print(f"  responses:             {impact.response_count}")
    print(f"  interviews:            {impact.interview_count}")
    print(f"  notifications:         {impact.notification_count}")
    print(f"  hr_ignores:            {impact.hr_ignore_count}")
    print(f"  student_templates:     {impact.student_template_count}")
    print(f"  campaigns (by student): {impact.campaign_owned_count}")
    print(f"  orphan campaigns:      {len(impact.orphan_campaign_ids)}")

    if resolution.unmatched_tokens:
        print("\n*** BLOCKING ISSUES: unmatched keep tokens ***")
        for t in resolution.unmatched_tokens:
            print(f"  - {t!r}")
            sug = resolution.fuzzy_suggestions.get(t, [])
            if sug:
                print("    Suggestions (substring match, verify spelling):")
                for sid, name, em in sug:
                    print(f"      {sid}  {name!r}  {em}")

    if resolution.ambiguous_tokens:
        print("\n*** BLOCKING ISSUES: ambiguous name (multiple students) ***")
        for tok, hits in resolution.ambiguous_tokens.items():
            print(f"  token {tok!r}:")
            for sid, name, em in hits:
                print(f"    {sid}  {name!r}  {em}")
            print("    Fix: keep one row by UUID in keep-file instead of display name.")

    print("\n--- Confirm no real student is listed under REMOVE ---")
    if resolution.ok_to_apply:
        if total_student_count and len(keep_rows) + len(remove_rows) != total_student_count:
            print(
                f"  WARNING: keep+remove ({len(keep_rows) + len(remove_rows)}) "
                f"!= total students ({total_student_count})"
            )
        if remove_rows:
            print("Resolution OK (all keep tokens matched, no ambiguous names). Apply only after export + backup.")
        else:
            print("Resolution OK; nothing to remove.")
    else:
        print("Do not apply until unmatched/ambiguous issues are resolved.")


def _add_keep_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--no-default-keep",
        action="store_true",
        help="Do not load built-in default student names; use only --keep-file / --keep-names.",
    )
    p.add_argument("--keep-file", type=str, default=None, help="Text file: one keep name or student UUID per line (# comments ok).")
    p.add_argument("--keep-names", type=str, default=None, help="Extra comma-separated keep names or UUIDs.")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    argv = argv if argv is not None else sys.argv[1:]

    parser = argparse.ArgumentParser(description="Whitelist-based student purge (preview vs apply).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_prev = sub.add_parser("preview", help="Show KEEP / REMOVE and linked counts (no DB writes).")
    _add_keep_args(p_prev)

    p_apply = sub.add_parser("apply", help="Export snapshot then remove non-whitelist students (destructive).")
    _add_keep_args(p_apply)
    p_apply.add_argument("--export-dir", type=str, required=True, help="Directory for JSON/CSV snapshot before delete.")
    p_apply.add_argument("--i-understand", action="store_true", help="Required acknowledgement for destructive apply.")
    p_apply.add_argument("--clean-audit-logs", action="store_true", help="Delete audit_logs rows for removed student UUIDs.")

    args = parser.parse_args(argv)

    try:
        from app.database.config import SessionLocal
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    from app.models import Student
    from app.services.student_whitelist_cleanup import load_keep_tokens, resolve_keep_students, students_to_remove

    tokens = load_keep_tokens(
        use_builtin_defaults=not args.no_default_keep,
        keep_file=args.keep_file,
        keep_names=args.keep_names,
    )
    if not tokens:
        print("No keep tokens: use built-in defaults or pass --keep-file / --keep-names.", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        resolution = resolve_keep_students(db, tokens)
        keep_rows = list(resolution.keep_students)
        keep_ids = set(resolution.keep_student_ids)
        if resolution.ok_to_apply:
            remove_rows = students_to_remove(db, keep_ids)
            remove_ids = {r[0] for r in remove_rows}
            impact = compute_remove_impact(db, remove_ids)
        else:
            remove_rows = []
            remove_ids = set()
            impact = RemoveImpact()
            print(
                "\n*** REMOVE counts not computed until every keep token matches exactly one student "
                "(fix unmatched / ambiguous above). ***\n"
            )
        all_students = [(s.id, s.name, s.gmail_address) for s in db.query(Student).all()]

        manifest = {
            "keep_tokens": tokens,
            "keep_student_ids": [str(x) for x in sorted(keep_ids, key=str)],
            "remove_student_ids": [str(x[0]) for x in remove_rows],
            "unmatched_tokens": resolution.unmatched_tokens,
            "ambiguous_tokens": {k: [str(x[0]) for x in v] for k, v in resolution.ambiguous_tokens.items()},
        }

        _print_report(
            resolution=resolution,
            keep_rows=keep_rows,
            remove_rows=remove_rows,
            impact=impact,
            total_student_count=len(all_students),
        )

        if args.command == "preview":
            db.rollback()
            return 0

        # apply
        if not args.i_understand:
            print("\nRefusing apply without --i-understand.", file=sys.stderr)
            return 2
        if not resolution.ok_to_apply:
            print("\nRefusing apply: fix unmatched or ambiguous keep tokens first.", file=sys.stderr)
            return 2
        if not remove_ids:
            print("\nNothing to remove; no commit.")
            db.rollback()
            return 0

        export_root = run_export_remove_snapshot(
            db,
            export_dir=Path(args.export_dir),
            remove_rows=remove_rows,
            impact=impact,
            resolution_manifest=manifest,
        )
        print(f"\nPre-delete snapshot: {export_root}")

        run_delete_removed_students(
            db,
            remove_ids,
            impact.orphan_campaign_ids,
            clean_audit_logs=args.clean_audit_logs,
        )
        db.commit()
        print("Committed: non-whitelist students and dependent rows removed.")
        return 0
    except Exception:
        db.rollback()
        logger.exception("Whitelist cleanup failed")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
