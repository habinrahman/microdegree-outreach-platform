"""
Restore ``hr_contacts`` rows from an ``hr_whitelist_cleanup_*`` snapshot (CSV/JSONL).

Only **inserts** missing rows; never updates existing contacts. Idempotent: safe to re-run.

Commands:
  python -m app.scripts.restore_hr_contacts_from_snapshot preview --snapshot-dir PATH
  python -m app.scripts.restore_hr_contacts_from_snapshot restore --snapshot-dir PATH --i-understand
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class RestorePlan:
    rows_in_snapshot: int
    would_insert: int
    skip_id_exists: int
    skip_email_exists: int
    skip_invalid_row: int
    details_insert: list[tuple[str, str, str]]  # id, email, name (cap len for print)
    details_skip: list[str]


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def load_hr_snapshot_rows(snapshot_dir: Path) -> list[dict[str, Any]]:
    """Load rows from ``hr_contacts_to_remove.jsonl`` or ``.csv`` (JSONL preferred)."""
    jsonl = snapshot_dir / "hr_contacts_to_remove.jsonl"
    csv_path = snapshot_dir / "hr_contacts_to_remove.csv"
    if jsonl.is_file():
        rows: list[dict[str, Any]] = []
        with jsonl.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
        return rows
    if csv_path.is_file():
        with csv_path.open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    raise FileNotFoundError(
        f"No hr_contacts_to_remove.jsonl or hr_contacts_to_remove.csv under {snapshot_dir}"
    )


def _validate_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    try:
        hid = raw.get("id")
        if not hid:
            return None
        UUID(str(hid))
        email = _norm_email(str(raw.get("email", "")))
        if not email:
            return None
        name = (raw.get("name") or "").strip()
        if not name:
            return None
        company = (raw.get("company") or "").strip() or "Unknown"
        return {"id": UUID(str(hid)), "email": email, "name": name, "company": company}
    except (ValueError, TypeError):
        return None


def build_plan(db: Session, rows: list[dict[str, Any]]) -> RestorePlan:
    from app.models import HRContact

    would_insert = 0
    skip_id = 0
    skip_email = 0
    skip_invalid = 0
    details_insert: list[tuple[str, str, str]] = []
    details_skip: list[str] = []

    existing_emails = {r[0].strip().lower() for r in db.query(HRContact.email).all() if r[0]}
    existing_ids = {r[0] for r in db.query(HRContact.id).all()}

    for raw in rows:
        v = _validate_row(raw)
        if not v:
            skip_invalid += 1
            details_skip.append(f"invalid_row:{str(raw)[:120]}")
            continue
        hid, email, name, company = v["id"], v["email"], v["name"], v["company"]

        if hid in existing_ids:
            skip_id += 1
            details_skip.append(f"id_exists:{hid}")
            continue
        if email in existing_emails:
            skip_email += 1
            details_skip.append(f"email_exists:{email}")
            continue

        would_insert += 1
        details_insert.append((str(hid), email, name[:60]))
        existing_ids.add(hid)
        existing_emails.add(email)

    return RestorePlan(
        rows_in_snapshot=len(rows),
        would_insert=would_insert,
        skip_id_exists=skip_id,
        skip_email_exists=skip_email,
        skip_invalid_row=skip_invalid,
        details_insert=details_insert,
        details_skip=details_skip[:50],
    )


def apply_restore(db: Session, rows: list[dict[str, Any]]) -> tuple[int, int, int, int, int]:
    """Execute inserts; returns (inserted, skip_id, skip_email, skip_invalid, skip_integrity)."""
    from app.models import HRContact

    inserted = 0
    skip_id = skip_email = skip_invalid = skip_integrity = 0

    existing_emails = {r[0].strip().lower() for r in db.query(HRContact.email).all() if r[0]}
    existing_ids = {r[0] for r in db.query(HRContact.id).all()}

    for raw in rows:
        v = _validate_row(raw)
        if not v:
            skip_invalid += 1
            continue
        hid, email, name, company = v["id"], v["email"], v["name"], v["company"]

        if hid in existing_ids:
            skip_id += 1
            continue
        if email in existing_emails:
            skip_email += 1
            continue

        try:
            with db.begin_nested():
                db.add(
                    HRContact(
                        id=hid,
                        name=name[:255],
                        company=company[:255],
                        email=email,
                        status="active",
                        is_valid=True,
                        is_demo=False,
                    )
                )
                db.flush()
        except IntegrityError:
            # Unique ``email`` / PK race; idempotent re-run.
            skip_integrity += 1
            continue
        inserted += 1
        existing_ids.add(hid)
        existing_emails.add(email)

    return inserted, skip_id, skip_email, skip_invalid, skip_integrity


def _print_plan(plan: RestorePlan, snapshot_dir: Path) -> None:
    print(f"Snapshot: {snapshot_dir.resolve()}\n")
    print("--- Preview ---")
    print(f"  Rows in snapshot:     {plan.rows_in_snapshot}")
    print(f"  Would INSERT:         {plan.would_insert}")
    print(f"  Skip (id exists):     {plan.skip_id_exists}")
    print(f"  Skip (email exists):  {plan.skip_email_exists}")
    print(f"  Skip (invalid row):   {plan.skip_invalid_row}")
    if plan.details_insert:
        print("\n  Inserts (id, email, name):")
        for t in plan.details_insert[:40]:
            print(f"    {t[0]}  {t[1]!r}  {t[2]!r}")
        if len(plan.details_insert) > 40:
            print(f"    ... {len(plan.details_insert) - 40} more")
    if plan.details_skip:
        print("\n  Sample skips:")
        for s in plan.details_skip[:20]:
            print(f"    {s}")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    argv = argv if argv is not None else sys.argv[1:]

    p = argparse.ArgumentParser(description="Restore hr_contacts from whitelist cleanup snapshot.")
    sub = p.add_subparsers(dest="command", required=True)

    p_prev = sub.add_parser("preview", help="Dry-run counts (no DB writes).")
    p_prev.add_argument("--snapshot-dir", type=str, required=True, help="Path to hr_whitelist_cleanup_* folder.")

    p_rest = sub.add_parser("restore", help="Insert missing hr_contacts from snapshot.")
    p_rest.add_argument("--snapshot-dir", type=str, required=True, help="Path to hr_whitelist_cleanup_* folder.")
    p_rest.add_argument("--i-understand", action="store_true", help="Required for destructive-ish DB writes.")

    args = p.parse_args(argv)
    snap = Path(args.snapshot_dir)
    if not snap.is_dir():
        print(f"Not a directory: {snap}", file=sys.stderr)
        return 2

    try:
        rows = load_hr_snapshot_rows(snap)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2

    manifest = snap / "manifest.json"
    if manifest.is_file():
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
            print(f"manifest generated_at_utc: {m.get('generated_at_utc', '?')}\n")
        except json.JSONDecodeError:
            pass

    try:
        from app.database.config import SessionLocal
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        plan = build_plan(db, rows)
        _print_plan(plan, snap)

        if args.command == "preview":
            db.rollback()
            return 0

        if not args.i_understand:
            print("\nRefusing restore without --i-understand.", file=sys.stderr)
            return 2

        if plan.would_insert == 0:
            print("\nNothing to insert; no commit.")
            db.rollback()
            return 0

        inserted, sk_id, sk_em, sk_inv, sk_int = apply_restore(db, rows)
        db.commit()
        print("\n--- Restore complete ---")
        print(f"  Inserted:              {inserted}")
        print(f"  Skipped id exists:     {sk_id}")
        print(f"  Skipped email exists:  {sk_em}")
        print(f"  Skipped invalid:       {sk_inv}")
        print(f"  Skipped DB constraint: {sk_int}")
        return 0
    except Exception:
        db.rollback()
        logger.exception("Restore failed")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
