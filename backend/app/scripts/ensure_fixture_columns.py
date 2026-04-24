"""
CLI: ensure ``students.is_fixture_test_data`` and ``hr_contacts.is_fixture_test_data`` exist.

Uses ``DATABASE_URL`` (same as the API). Idempotent; safe when Alembic / Supabase SQL editor are unavailable.

Examples:
  python -m app.scripts.ensure_fixture_columns --verify-only
  python -m app.scripts.ensure_fixture_columns
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from app.database.config import engine
from app.database.fixture_column_bootstrap import ensure_fixture_columns_bootstrap, verify_fixture_columns

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--verify-only",
        action="store_true",
        help="Only print verification JSON; do not run DDL.",
    )
    args = p.parse_args(argv)

    before = verify_fixture_columns(engine)
    print("=== BEFORE ===")
    print(json.dumps(before, indent=2, default=str))

    if args.verify_only:
        ok = bool(before.get("fixture_columns_present"))
        print(f"\nverify_only: fixture_columns_present={ok}")
        return 0 if ok else 1

    result = ensure_fixture_columns_bootstrap(engine, verify_only=False, strict=True)
    print("\n=== ENSURE RESULT ===")
    print(json.dumps(result, indent=2, default=str))

    after = verify_fixture_columns(engine)
    print("\n=== AFTER ===")
    print(json.dumps(after, indent=2, default=str))

    if not after.get("fixture_columns_present"):
        print("ERROR: columns still missing after bootstrap.", file=sys.stderr)
        return 1
    print("\nOK: fixture columns present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
