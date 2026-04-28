"""
Export replies to a local CSV (spreadsheet-safe, rectangular).

Usage (backend cwd):
  python -m app.scripts.export_replies_csv --out ./exports/replies.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(description="Export replies CSV (safe quoting, stable columns).")
    p.add_argument("--out", type=str, required=True, help="Output CSV path.")
    p.add_argument("--include-demo", action="store_true", help="Include demo students/HRs.")
    p.add_argument("--limit", type=int, default=5000, help="Max rows (default 5000).")
    args = p.parse_args(argv)

    from app.database.config import SessionLocal
    from app.services.reply_export import iter_reply_export_rows, write_reply_export_csv

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        with out.open("w", encoding="utf-8", newline="") as f:
            n = write_reply_export_csv(
                f,
                iter_reply_export_rows(db, include_demo=bool(args.include_demo), limit=int(args.limit)),
            )
        print(f"ok rows={n} path={out}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

