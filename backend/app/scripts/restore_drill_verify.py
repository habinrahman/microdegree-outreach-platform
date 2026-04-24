"""
Restore drill (verify-only): validate a pg_dump custom file with pg_restore --list.

  python -m app.scripts.restore_drill_verify --dump ./backups/microdegree_outreach_20260101.dump

Does not restore data. Exit 0 if archive is readable.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(description="Verify pg_dump -Fc archive (pg_restore --list).")
    p.add_argument("--dump", type=str, required=True, help="Path to .dump file")
    args = p.parse_args(argv)

    from app.services.backup_pg import verify_pg_dump_custom_format

    path = Path(args.dump)
    res = verify_pg_dump_custom_format(path)
    print(json.dumps({"dump": str(path.resolve()), "verify": res}, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
