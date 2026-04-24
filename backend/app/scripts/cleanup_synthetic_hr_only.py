"""
Delete **only** ``hr_contacts`` rows that match an explicit synthetic pattern list
(see ``app.services.synthetic_hr_cleanup``). Preview → export → apply.

Does not delete students. FK order reuses ``cleanup_keep_hr_whitelist`` helpers.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.synthetic_hr_audit import SyntheticHRAuditResult, run_synthetic_hr_audit

logger = logging.getLogger(__name__)


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


def _scan_synthetic_hrs(db: Session) -> tuple[list[tuple[UUID, str, str, str]], Counter[str], dict[str, list[tuple[str, str, str]]]]:
    """Returns (remove_rows, primary_bucket_counts, samples_by_bucket)."""
    from app.models import HRContact
    from app.services.synthetic_hr_cleanup import (
        is_synthetic_hr,
        primary_synthetic_bucket,
        synthetic_match_reasons,
    )

    remove: list[tuple[UUID, str, str, str]] = []
    buckets: Counter[str] = Counter()
    samples: dict[str, list[tuple[str, str, str]]] = {}

    for h in db.query(HRContact).order_by(HRContact.created_at.desc()).all():
        if not is_synthetic_hr(email=h.email, name=h.name, company=h.company):
            continue
        remove.append((h.id, h.email, h.name, h.company))
        pk = primary_synthetic_bucket(email=h.email, name=h.name, company=h.company) or "unknown"
        buckets[pk] += 1
        reasons = ";".join(synthetic_match_reasons(email=h.email, name=h.name, company=h.company))
        samples.setdefault(pk, [])
        if len(samples[pk]) < 8:
            samples[pk].append((h.email, h.name, h.company, reasons))

    return remove, buckets, samples


def _write_export(
    db: Session,
    export_dir: Path,
    remove_rows: list[tuple[UUID, str, str, str]],
    buckets: Counter[str],
    samples: dict[str, list[tuple[str, str, str]]],
) -> tuple[Path, Any]:
    from app.scripts.cleanup_keep_hr_whitelist import HRRemoveImpact, compute_remove_impact_hr
    from app.services.synthetic_hr_cleanup import pattern_version

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    root = export_dir / f"synthetic_hr_cleanup_{ts}"
    root.mkdir(parents=True, exist_ok=True)

    remove_ids = {r[0] for r in remove_rows}
    impact: HRRemoveImpact | None = compute_remove_impact_hr(db, remove_ids) if remove_ids else None

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "pattern_version": pattern_version(),
        "synthetic_hr_count": len(remove_rows),
        "counts_by_primary_pattern": dict(buckets),
        "sample_rows_by_bucket": {k: [{"email": a[0], "name": a[1], "company": a[2], "reasons": a[3]} for a in v] for k, v in samples.items()},
        "impact": asdict(impact) if impact else {},
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    rows_rm = [{"id": str(i), "email": e, "name": n, "company": c} for i, e, n, c in remove_rows]
    _export_jsonl(root / "synthetic_hr_contacts_to_remove.jsonl", rows_rm)
    _export_csv(root / "synthetic_hr_contacts_to_remove.csv", ["id", "email", "name", "company"], rows_rm)
    if impact:
        (root / "impact.json").write_text(json.dumps(asdict(impact), indent=2), encoding="utf-8")

    logger.info("Snapshot written to %s", root)
    return root, impact


def _print_audit(audit: SyntheticHRAuditResult) -> None:
    print(f"  synthetic_hr_remaining:              {audit.synthetic_hr_count}")
    print(f"  orphan_assignments:                  {audit.orphan_assignments}")
    print(f"  orphan_campaigns_missing_student:    {audit.orphan_campaigns_missing_student}")
    print(f"  email_campaigns_missing_student:     {audit.email_campaigns_missing_student}")
    print(f"  email_campaigns_missing_hr:         {audit.email_campaigns_missing_hr}")
    print(f"  email_campaigns_broken_campaign_fk: {audit.email_campaigns_broken_campaign_fk}")
    print(f"  audit_ok:                            {audit.ok}")


def _print_preview(remove_rows: list[tuple[UUID, str, str, str]], buckets: Counter[str], samples: dict[str, list[tuple[str, str, str]]]) -> None:
    print("=== Synthetic HR-only purge (explicit patterns) ===\n")
    print(f"Total HR rows to delete: {len(remove_rows)}\n")
    print("--- Counts by primary pattern ---")
    for k, v in sorted(buckets.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {k}: {v}")
    print("\n--- Sample rows (up to 8 per bucket) ---")
    for k in sorted(samples.keys()):
        print(f"  [{k}]")
        for email, name, company, reasons in samples[k]:
            print(f"    {email!r} | {name!r} | {company!r} | {reasons}")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    argv = argv if argv is not None else sys.argv[1:]

    p = argparse.ArgumentParser(description="Purge only synthetic-pattern hr_contacts.")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("preview", help="Dry-run: counts and samples (no DB writes).")

    p_apply = sub.add_parser("apply", help="Export snapshot then delete matching HRs.")
    p_apply.add_argument("--export-dir", type=str, required=True, help="Parent directory for synthetic_hr_cleanup_* snapshot.")
    p_apply.add_argument("--i-understand", action="store_true", help="Required to perform deletes.")
    p_apply.add_argument("--no-clean-blocked-hrs", action="store_true", help="Keep blocked_hrs even if email matches removed HR.")
    p_apply.add_argument("--clean-audit-logs", action="store_true", help="Remove audit_logs rows for deleted HR UUIDs.")

    args = p.parse_args(argv)

    try:
        from app.database.config import SessionLocal
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    from app.services.synthetic_hr_cleanup import assert_safe_real_domain_examples

    assert_safe_real_domain_examples()

    db = SessionLocal()
    try:
        remove_rows, buckets, samples = _scan_synthetic_hrs(db)
        _print_preview(remove_rows, buckets, samples)

        audit = run_synthetic_hr_audit(db)
        print("\n--- Referential integrity audit (current DB) ---")
        _print_audit(audit)

        if args.command == "preview":
            db.rollback()
            return 0

        if not args.i_understand:
            print("\nRefusing apply without --i-understand.", file=sys.stderr)
            return 2
        if not remove_rows:
            print("\nNothing to delete.")
            db.rollback()
            return 0

        export_root, impact = _write_export(db, Path(args.export_dir), remove_rows, buckets, samples)
        print(f"\nPre-delete snapshot: {export_root}")

        from app.scripts.cleanup_keep_hr_whitelist import run_delete_removed_hrs

        remove_ids = {r[0] for r in remove_rows}
        run_delete_removed_hrs(
            db,
            remove_ids,
            impact.orphan_campaign_ids,
            clean_blocked_hrs=not args.no_clean_blocked_hrs,
            clean_audit_logs=args.clean_audit_logs,
        )
        db.commit()
        print(f"Committed: removed {len(remove_rows)} synthetic hr_contacts.")
        audit_after = run_synthetic_hr_audit(db)
        print("\n--- Post-apply integrity audit ---")
        _print_audit(audit_after)
        if not audit_after.ok:
            logger.warning("Post-apply audit not clean: %s", audit_after)
        return 0
    except Exception:
        db.rollback()
        logger.exception("Synthetic HR cleanup failed")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
