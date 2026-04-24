"""
Whitelist HR cleanup: KEEP HRs tied to configured real students (outreach anchor) plus
explicit keep emails/UUIDs; remove all other HR contacts and dependent rows.

Commands:
  python -m app.scripts.cleanup_keep_hr_whitelist preview
  python -m app.scripts.cleanup_keep_hr_whitelist apply --export-dir ./snap --i-understand

Does not delete ``students``. HR scores / analytics are computed on read.
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
class HRRemoveImpact:
    remove_hr_count: int = 0
    assignment_count: int = 0
    email_campaign_count: int = 0
    response_count: int = 0
    interview_count: int = 0
    notification_count: int = 0
    hr_ignore_count: int = 0
    orphan_campaign_ids: list[str] = field(default_factory=list)
    blocked_hr_count: int = 0
    email_campaign_ids: list[str] = field(default_factory=list)


def compute_remove_impact_hr(db: Session, remove_hr_ids: set[UUID]) -> HRRemoveImpact:
    from app.models import Assignment, BlockedHR, EmailCampaign, HRContact, HRIgnored, Interview, Notification, Response

    out = HRRemoveImpact()
    if not remove_hr_ids:
        return out

    out.remove_hr_count = len(remove_hr_ids)

    ec_rows = (
        db.query(EmailCampaign.id, EmailCampaign.campaign_id)
        .filter(EmailCampaign.hr_id.in_(remove_hr_ids))
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

    out.assignment_count = db.query(Assignment).filter(Assignment.hr_id.in_(remove_hr_ids)).count()
    out.hr_ignore_count = db.query(HRIgnored).filter(HRIgnored.hr_id.in_(remove_hr_ids)).count()
    out.interview_count = db.query(Interview).filter(Interview.hr_id.in_(remove_hr_ids)).count()

    resp_parts = [Response.hr_id.in_(remove_hr_ids)]
    if ec_ids:
        resp_parts.append(Response.source_campaign_id.in_(ec_ids))
    out.response_count = db.query(Response).filter(or_(*resp_parts)).count()

    notif = 0
    if ec_ids:
        for ch in _chunked(ec_ids):
            notif += db.query(Notification).filter(Notification.reply_for_campaign_id.in_(ch)).count()
    out.notification_count = notif

    elower: list[str] = []
    for ch in _chunked(list(remove_hr_ids)):
        elower.extend(r[0].strip().lower() for r in db.query(HRContact.email).filter(HRContact.id.in_(ch)).all() if r[0])
    for i in range(0, len(elower), 400):
        part = elower[i : i + 400]
        out.blocked_hr_count += db.query(BlockedHR).filter(BlockedHR.email.in_(part)).count()

    return out


def run_export_hr_remove_snapshot(
    db: Session,
    *,
    export_dir: Path,
    remove_rows: list[tuple[UUID, str, str, str]],
    impact: HRRemoveImpact,
    resolution_manifest: dict[str, Any],
) -> Path:
    from app.models import Assignment, EmailCampaign

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    root = export_dir / f"hr_whitelist_cleanup_{ts}"
    root.mkdir(parents=True, exist_ok=True)

    (root / "manifest.json").write_text(
        json.dumps({"generated_at_utc": datetime.now(timezone.utc).isoformat(), **resolution_manifest}, indent=2, default=str),
        encoding="utf-8",
    )

    rows_rm = [{"id": str(i), "email": e, "name": n, "company": c} for i, e, n, c in remove_rows]
    _export_jsonl(root / "hr_contacts_to_remove.jsonl", rows_rm)
    _export_csv(root / "hr_contacts_to_remove.csv", ["id", "email", "name", "company"], rows_rm)

    remove_ids = {r[0] for r in remove_rows}
    rows_a: list[dict[str, Any]] = []
    if remove_ids:
        for a in db.query(Assignment).filter(Assignment.hr_id.in_(remove_ids)).all():
            rows_a.append({"id": str(a.id), "student_id": str(a.student_id), "hr_id": str(a.hr_id), "status": a.status})
    _export_jsonl(root / "assignments_to_remove.jsonl", rows_a)

    rows_ec: list[dict[str, Any]] = []
    if remove_ids:
        for c in db.query(EmailCampaign).filter(EmailCampaign.hr_id.in_(remove_ids)).all():
            rows_ec.append(
                {
                    "id": str(c.id),
                    "student_id": str(c.student_id),
                    "hr_id": str(c.hr_id),
                    "campaign_id": str(c.campaign_id) if c.campaign_id else None,
                    "sequence_number": c.sequence_number,
                    "status": c.status,
                }
            )
    _export_jsonl(root / "email_campaigns_to_remove.jsonl", rows_ec)

    (root / "impact.json").write_text(json.dumps(asdict(impact), indent=2), encoding="utf-8")
    logger.info("Snapshot written to %s", root)
    return root


def run_delete_removed_hrs(
    db: Session,
    remove_hr_ids: set[UUID],
    orphan_campaign_ids: list[str],
    *,
    clean_blocked_hrs: bool,
    clean_audit_logs: bool,
) -> None:
    from app.models import (
        Assignment,
        AuditLog,
        BlockedHR,
        Campaign,
        EmailCampaign,
        HRContact,
        HRIgnored,
        Interview,
        Notification,
        Response,
    )

    if not remove_hr_ids:
        return

    blocked_emails: list[str] = []
    if clean_blocked_hrs:
        for ch in _chunked(list(remove_hr_ids)):
            blocked_emails.extend(
                r[0].strip().lower() for r in db.query(HRContact.email).filter(HRContact.id.in_(ch)).all() if r[0]
            )

    ec_ids: list[UUID] = [
        r[0] for r in db.query(EmailCampaign.id).filter(EmailCampaign.hr_id.in_(remove_hr_ids)).all()
    ]

    if ec_ids:
        for ch in _chunked(ec_ids):
            db.query(Response).filter(Response.source_campaign_id.in_(ch)).delete(synchronize_session=False)
    db.query(Response).filter(Response.hr_id.in_(remove_hr_ids)).delete(synchronize_session=False)

    if ec_ids:
        for ch in _chunked(ec_ids):
            db.query(Notification).filter(Notification.reply_for_campaign_id.in_(ch)).delete(synchronize_session=False)

    db.query(EmailCampaign).filter(EmailCampaign.hr_id.in_(remove_hr_ids)).delete(synchronize_session=False)
    db.query(Assignment).filter(Assignment.hr_id.in_(remove_hr_ids)).delete(synchronize_session=False)
    db.query(Interview).filter(Interview.hr_id.in_(remove_hr_ids)).delete(synchronize_session=False)
    db.query(HRIgnored).filter(HRIgnored.hr_id.in_(remove_hr_ids)).delete(synchronize_session=False)

    for cid_str in orphan_campaign_ids:
        cid = UUID(cid_str)
        if db.query(EmailCampaign).filter(EmailCampaign.campaign_id == cid).count() == 0:
            db.query(Campaign).filter(Campaign.id == cid).delete(synchronize_session=False)

    db.query(HRContact).filter(HRContact.id.in_(remove_hr_ids)).delete(synchronize_session=False)

    if clean_blocked_hrs and blocked_emails:
        for i in range(0, len(blocked_emails), 400):
            part = blocked_emails[i : i + 400]
            db.query(BlockedHR).filter(BlockedHR.email.in_(part)).delete(synchronize_session=False)

    if clean_audit_logs:
        all_str = [str(u) for u in remove_hr_ids]
        for ch in _chunked_str(all_str):
            db.query(AuditLog).filter(AuditLog.entity_id.in_(ch)).delete(synchronize_session=False)

    db.flush()


def _print_report(
    *,
    resolution,
    keep_rows: list[tuple[UUID, str, str, str]],
    remove_rows: list[tuple[UUID, str, str, str]],
    impact: HRRemoveImpact,
    student_anchor_summary: dict[str, Any],
    total_hr_count: int,
) -> None:
    print("=== HR whitelist cleanup ===\n")

    print("--- Student anchor (outreach history) ---")
    for k, v in student_anchor_summary.items():
        print(f"  {k}: {v}")

    print("\n--- KEEP (anchor ∪ explicit) ---")
    if not keep_rows:
        print("  (none — refusing apply until at least one HR is kept)")
    for hid, em, name, co in keep_rows[:200]:
        tag = "explicit" if hid in resolution.explicit_hr_ids else "anchor"
        print(f"  [{tag}] {hid}  |  {em!r}  |  {name!r}  |  {co!r}")
    if len(keep_rows) > 200:
        print(f"  ... {len(keep_rows) - 200} more")

    print("\n--- REMOVE (not kept) ---")
    if not remove_rows:
        print("  (none)")
    else:
        print(f"  count: {len(remove_rows)}")
        for hid, em, name, co in remove_rows[:80]:
            print(f"  {hid}  |  {em!r}  |  {name!r}  |  {co!r}")
        if len(remove_rows) > 80:
            print(f"  ... {len(remove_rows) - 80} more (see export CSV)")

    print("\n--- Linked rows removed with these HRs ---")
    print(f"  assignments:           {impact.assignment_count}")
    print(f"  email_campaigns:       {impact.email_campaign_count}")
    print(f"  responses:             {impact.response_count}")
    print(f"  interviews:            {impact.interview_count}")
    print(f"  notifications:         {impact.notification_count}")
    print(f"  hr_ignores:            {impact.hr_ignore_count}")
    print(f"  orphan campaigns:      {len(impact.orphan_campaign_ids)}")
    print(f"  blocked_hrs (matched): {impact.blocked_hr_count}")

    if resolution.unmatched_explicit_tokens:
        print("\n*** BLOCKING: unmatched explicit keep tokens (email / UUID) ***")
        for t in resolution.unmatched_explicit_tokens:
            print(f"  - {t!r}")
            sug = resolution.fuzzy_suggestions.get(t, [])
            if sug:
                print("    Suggestions (ILIKE on email):")
                for hid, em, name, co in sug:
                    print(f"      {hid}  {em!r}  {name!r}")

    if total_hr_count and len(keep_rows) + len(remove_rows) != total_hr_count:
        print(
            f"\n  WARNING: keep+remove ({len(keep_rows) + len(remove_rows)}) "
            f"!= total hr_contacts ({total_hr_count})"
        )

    print("\n--- Confirm every KEEP HR is intentional ---")
    if resolution.ok_to_apply:
        if remove_rows:
            print("Resolution OK for apply (explicit tokens resolved; keep set non-empty). Export + review REMOVE.")
        else:
            print("Resolution OK; nothing to remove.")
    else:
        if not resolution.keep_hr_ids:
            print("Refusing apply: keep set is empty (enable student anchor and/or fix explicit keeps).")
        else:
            print("Refusing apply: fix unmatched explicit keep tokens.")


def _add_hr_keep_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--no-student-anchor",
        action="store_true",
        help="Do not auto-keep HRs linked to default real student names (see student_whitelist_cleanup).",
    )
    p.add_argument(
        "--student-anchor-keep-file",
        type=str,
        default=None,
        help="Optional: alternate student name/UUID list file for anchor (same format as student cleanup).",
    )
    p.add_argument(
        "--student-anchor-keep-names",
        type=str,
        default=None,
        help="Optional: comma-separated extra student names/UUIDs for anchor.",
    )
    p.add_argument(
        "--use-builtin-hr-emails",
        action="store_true",
        help="Include DEFAULT_HR_KEEP_EMAILS from hr_whitelist_cleanup (usually empty).",
    )
    p.add_argument("--keep-file", type=str, default=None, help="One HR email or hr_contacts UUID per line (# comments ok).")
    p.add_argument("--keep-emails", type=str, default=None, help="Comma-separated HR emails and/or UUIDs to always keep.")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    argv = argv if argv is not None else sys.argv[1:]

    parser = argparse.ArgumentParser(description="Whitelist-based HR purge (preview vs apply).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_prev = sub.add_parser("preview", help="Show KEEP / REMOVE and linked counts (no DB writes).")
    _add_hr_keep_args(p_prev)

    p_apply = sub.add_parser("apply", help="Export snapshot then remove non-whitelist HRs (destructive).")
    _add_hr_keep_args(p_apply)
    p_apply.add_argument("--export-dir", type=str, required=True, help="Directory for JSON/CSV snapshot before delete.")
    p_apply.add_argument("--i-understand", action="store_true", help="Required acknowledgement for destructive apply.")
    p_apply.add_argument("--no-clean-blocked-hrs", action="store_true", help="Leave blocked_hrs rows even if email matches a removed HR.")
    p_apply.add_argument("--clean-audit-logs", action="store_true", help="Delete audit_logs rows whose entity_id matches removed HR UUIDs.")

    args = parser.parse_args(argv)

    try:
        from app.database.config import SessionLocal
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    from app.models import HRContact
    from app.services.hr_whitelist_cleanup import hrs_to_remove, load_explicit_hr_keep_tokens, resolve_keep_hrs
    from app.services.student_whitelist_cleanup import load_keep_tokens, resolve_keep_students

    explicit_tokens = load_explicit_hr_keep_tokens(
        use_builtin_hr_emails=args.use_builtin_hr_emails,
        keep_file=args.keep_file,
        keep_emails=args.keep_emails,
    )

    db = SessionLocal()
    try:
        anchor_student_ids: set[UUID] = set()
        st_unmatched: list[str] = []
        st_ambiguous: dict[str, list[tuple[UUID, str, str]]] = {}
        if not args.no_student_anchor:
            st_tokens = load_keep_tokens(
                use_builtin_defaults=True,
                keep_file=args.student_anchor_keep_file,
                keep_names=args.student_anchor_keep_names,
            )
            st_res = resolve_keep_students(db, st_tokens)
            anchor_student_ids = set(st_res.keep_student_ids)
            st_unmatched = list(st_res.unmatched_tokens)
            st_ambiguous = dict(st_res.ambiguous_tokens)

        resolution = resolve_keep_hrs(db, explicit_tokens=explicit_tokens, anchor_student_ids=anchor_student_ids)
        keep_rows = list(resolution.keep_hrs)
        keep_ids = set(resolution.keep_hr_ids)

        if resolution.ok_to_apply:
            remove_rows = hrs_to_remove(db, keep_ids)
            remove_ids = {r[0] for r in remove_rows}
            impact = compute_remove_impact_hr(db, remove_ids)
        else:
            remove_rows = []
            remove_ids = set()
            impact = HRRemoveImpact()
            if not resolution.unmatched_explicit_tokens and not resolution.keep_hr_ids:
                print("\n*** keep set empty: enable student anchor and/or add --keep-emails / --keep-file ***\n")
            elif resolution.unmatched_explicit_tokens:
                print("\n*** REMOVE list not computed until explicit keep tokens all resolve. ***\n")

        total_hr = db.query(HRContact).count()
        student_anchor_summary = {
            "student_anchor_enabled": not args.no_student_anchor,
            "anchor_student_count": len(anchor_student_ids),
            "anchor_hr_count": len(resolution.anchor_hr_ids),
            "explicit_hr_count": len(resolution.explicit_hr_ids),
            "student_anchor_unmatched_tokens": st_unmatched,
            "student_anchor_ambiguous": {k: [str(x[0]) for x in v] for k, v in st_ambiguous.items()},
        }

        _print_report(
            resolution=resolution,
            keep_rows=keep_rows,
            remove_rows=remove_rows,
            impact=impact,
            student_anchor_summary=student_anchor_summary,
            total_hr_count=total_hr,
        )

        if st_unmatched or st_ambiguous:
            print(
                "\nNote: student anchor had unmatched/ambiguous tokens; "
                "anchor HRs are still computed from *matched* students only. "
                "Fix student names or use --student-anchor-keep-file for a precise list.\n"
            )

        manifest = {
            "explicit_tokens": explicit_tokens,
            "keep_hr_ids": [str(x) for x in sorted(keep_ids, key=str)],
            "remove_hr_ids": [str(x[0]) for x in remove_rows],
            "unmatched_explicit_tokens": resolution.unmatched_explicit_tokens,
            "student_anchor_summary": student_anchor_summary,
        }

        if args.command == "preview":
            db.rollback()
            return 0

        if not args.i_understand:
            print("\nRefusing apply without --i-understand.", file=sys.stderr)
            return 2
        if not resolution.ok_to_apply:
            print("\nRefusing apply: resolve blocking issues above.", file=sys.stderr)
            return 2
        if not remove_ids:
            print("\nNothing to remove; no commit.")
            db.rollback()
            return 0

        export_root = run_export_hr_remove_snapshot(
            db,
            export_dir=Path(args.export_dir),
            remove_rows=remove_rows,
            impact=impact,
            resolution_manifest=manifest,
        )
        print(f"\nPre-delete snapshot: {export_root}")

        run_delete_removed_hrs(
            db,
            remove_ids,
            impact.orphan_campaign_ids,
            clean_blocked_hrs=not args.no_clean_blocked_hrs,
            clean_audit_logs=args.clean_audit_logs,
        )
        db.commit()
        print("Committed: non-whitelist HR contacts and dependent rows removed.")
        return 0
    except Exception:
        db.rollback()
        logger.exception("HR whitelist cleanup failed")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
