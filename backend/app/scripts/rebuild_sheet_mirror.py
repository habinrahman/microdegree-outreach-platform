"""
Rebuild Replies / Failures / Bounces from DB (source of truth).

Uses sheet_sync.rebuild_sheet_full(): clear tabs, reset export flags, batched sync + validation.
Does not modify Blocked HRs (use sync_blocked_hrs separately).

  python -m app.scripts.rebuild_sheet_mirror --yes
"""
from __future__ import annotations

import argparse

from app.database.config import SessionLocal
from app.services.sheet_sync import rebuild_sheet_full


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--yes",
        action="store_true",
        help="Required: confirm clearing sheet tabs and resetting export flags.",
    )
    args = p.parse_args()
    if not args.yes:
        print("Refusing to run without --yes (destructive to sheet data rows).")
        return 2

    db = SessionLocal()
    try:
        result = rebuild_sheet_full(db, include_demo=False)
        print("rebuild_sheet_full result:", result)
        if result and result.get("all_ok"):
            print("Mirror validation: OK")
            return 0
        print("Mirror validation: see errors in logs / result above")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
