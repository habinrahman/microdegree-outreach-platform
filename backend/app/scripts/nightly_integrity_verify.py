"""
Nightly integrity verification (cron-friendly).

  python -m app.scripts.nightly_integrity_verify

Exit 0 if integrity_ok; exit 1 otherwise. Prints JSON to stdout.
"""
from __future__ import annotations

import json
import logging
import sys

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        from app.database.config import SessionLocal
        from app.services.db_integrity_checks import run_corruption_integrity_checks
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        rep = run_corruption_integrity_checks(db)
        print(json.dumps(rep, indent=2))
        return 0 if rep.get("integrity_ok") else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
