"""
One-time Google Sheet Replies tab repair/migration.

Creates a legacy backup tab if the current Replies tab is corrupted, then rebuilds
Replies from DB using the canonical lean schema + normalized rows.

Usage (backend cwd):
  python -m app.scripts.rebuild_replies_sheet --yes
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(description="Rebuild Replies tab (sheet repair).")
    p.add_argument("--yes", action="store_true", help="Required acknowledgement (creates backup tab, rewrites Replies).")
    p.add_argument("--force", action="store_true", help="Force rebuild even if Replies header looks canonical.")
    p.add_argument("--include-demo", action="store_true", help="Include demo rows in DB backfill.")
    args = p.parse_args(argv)

    if not args.yes:
        print("Refusing to run without --yes (this rewrites the Replies sheet tab).", file=sys.stderr)
        return 2

    from app.database.config import SessionLocal
    from app.services.sheet_sync import rebuild_replies_sheet

    db = SessionLocal()
    try:
        rep = rebuild_replies_sheet(db, include_demo=bool(args.include_demo), force=bool(args.force))
        print(rep)
        return 0 if rep.get("ok") else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

